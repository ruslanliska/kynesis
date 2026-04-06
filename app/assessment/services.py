from datetime import datetime, timezone

import json
import logging

import logfire
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

from app.assessment.schemas import (
    AIProvider,
    PASS_THRESHOLD,
    AssessmentRequest,
    AssessmentResult,
    OverallResult,
    QuestionResult,
    SectionResult,
)
from app.core.ai_provider import get_llm
from app.scorecards.schemas import (
    CriticalType,
    ScorecardDefinition,
    ScorecardQuestion,
    ScoringMode,
    ScoringType,
)


# ---------------------------------------------------------------------------
# Structured output schemas
# ---------------------------------------------------------------------------


class AIQuestionOutput(BaseModel):
    question_id: str = Field(description="Exact ID of the question being evaluated.")
    selected_option_id: str | None = Field(
        default=None,
        description=(
            "ID of the selected answer option. Required for binary and scale questions. "
            "Must exactly match one of the option IDs listed for this question."
        ),
    )
    numeric_value: float | None = Field(
        default=None,
        description=(
            "Numeric score. Required for numeric scoring type. "
            "Must be between 0 and the question's maxPoints."
        ),
    )
    evidence: list[str] = Field(
        description=(
            "Verbatim quotes or data points from the content. "
            "Include calculated durations if timestamps exist. "
            "Tag-only questions may leave this empty."
        ),
    )
    reasoning: str = Field(
        description="Analysis of the evidence. Write this BEFORE selecting an answer.",
    )
    comment: str = Field(
        description="Concise human-readable assessment. Every claim must trace to evidence.",
    )
    suggestions: str | None = Field(
        default=None,
        description="Actionable improvements. Null if full points achieved.",
    )


class AIScoreOutput(BaseModel):
    content_analysis: str = Field(
        description="Factual summary of the content: type, participants, timeline, length.",
    )
    questions: list[AIQuestionOutput]
    summary: str = Field(
        description="Executive summary across all sections. Reference strongest and weakest areas.",
    )


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a rigorous QA auditor performing evidence-based assessments.

## CHAIN-OF-THOUGHT PROCESS

1. **content_analysis** — Summarise the content: type, participants, timeline, length.

2. For EACH question:
   a. **evidence** — Extract ALL relevant verbatim quotes and timestamps. Calculate exact durations when timestamps exist (e.g. '10:00:47Z → 10:01:32Z = 45s').
   b. **reasoning** — Analyse what the evidence proves and what is missing. Write this BEFORE selecting an answer.
   c. **selected_option_id / numeric_value** — Select only after reasoning is complete.
   d. **comment** — Every claim must trace back to evidence.
   e. **suggestions** — Null only if full points achieved.

3. **summary** — Synthesise patterns after ALL questions.

## ANSWER SELECTION
- Binary / Scale: set selected_option_id to EXACTLY one of the listed option IDs.
- Numeric: set numeric_value between 0 and maxPoints. Leave selected_option_id null.
- Tag-only: set selected_option_id for categorisation only.

## CRITICAL RULES
- Never claim something happened without evidence.
- Compute actual time differences when timestamps exist.
- Score conservatively when evidence is absent or ambiguous.
- HARD CRITICAL questions auto-fail the entire assessment if scored 0.
"""


def _build_scorecard_context(
    scorecard: ScorecardDefinition,
    knowledge_base_context: str | None,
) -> str:
    lines = [f"## Scorecard: {scorecard.name}", ""]
    if scorecard.description:
        lines += [scorecard.description, ""]

    for section in scorecard.sections:
        weight_str = f" (weight: {section.weight}%)" if section.weight is not None else ""
        lines.append(f"### Section: {section.name}{weight_str}")
        if section.description:
            lines.append(section.description)
        lines.append("")

        for question in sorted(section.questions, key=lambda q: q.order_index):
            critical_str = (
                f", critical: {question.critical.value.upper()}"
                if question.critical != CriticalType.none
                else ""
            )
            lines.append(
                f"**Q (ID: {question.id!r})** "
                f"[{question.scoring_type.value}, max: {question.max_points}pts"
                f", {'required' if question.required else 'optional'}{critical_str}]"
            )
            lines.append(f"Text: {question.text}")
            if question.description:
                lines.append(f"Description: {question.description}")

            if question.scoring_type in (ScoringType.binary, ScoringType.scale, ScoringType.tag_only):
                lines.append("Options:")
                for opt in sorted(question.options, key=lambda o: o.order_index):
                    pts = f"+{opt.points_change}" if opt.points_change >= 0 else str(opt.points_change)
                    lines.append(f"  - option_id: {opt.id!r} | {opt.label} | {pts} pts")
                lines.append("► Set selected_option_id to one of the option_id values above.")
            elif question.scoring_type == ScoringType.numeric:
                lines.append(f"► Set numeric_value between 0 and {question.max_points}.")
            lines.append("")

    if knowledge_base_context:
        lines += ["## Reference Knowledge Base", knowledge_base_context, ""]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _validate_output(result: AIScoreOutput, scorecard: ScorecardDefinition) -> None:
    question_map: dict[str, ScorecardQuestion] = {
        q.id: q for s in scorecard.sections for q in s.questions
    }
    expected = set(question_map.keys())
    result_ids = {q.question_id for q in result.questions}

    if result_ids != expected:
        missing = expected - result_ids
        extra = result_ids - expected
        parts = []
        if missing:
            parts.append(f"Missing: {missing}")
        if extra:
            parts.append(f"Unexpected: {extra}")
        raise ValueError(f"Questions mismatch. {'; '.join(parts)}")

    for ai_q in result.questions:
        q = question_map[ai_q.question_id]

        if not ai_q.evidence and q.scoring_type != ScoringType.tag_only:
            raise ValueError(f"No evidence for '{q.text}'.")

        if q.scoring_type in (ScoringType.binary, ScoringType.scale):
            if ai_q.selected_option_id is None:
                raise ValueError(f"'{q.text}' requires selected_option_id.")
            valid = {o.id for o in q.options}
            if ai_q.selected_option_id not in valid:
                raise ValueError(
                    f"selected_option_id '{ai_q.selected_option_id}' for '{q.text}' invalid. "
                    f"Valid: {valid}"
                )
        elif q.scoring_type == ScoringType.numeric:
            if ai_q.numeric_value is None:
                raise ValueError(f"'{q.text}' requires numeric_value.")
            if not (0 <= ai_q.numeric_value <= q.max_points):
                raise ValueError(
                    f"numeric_value {ai_q.numeric_value} for '{q.text}' must be 0–{q.max_points}."
                )


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def _question_earned(
    ai_q: AIQuestionOutput,
    question: ScorecardQuestion,
    scoring_mode: ScoringMode,
) -> float:
    if question.scoring_type in (ScoringType.binary, ScoringType.scale):
        for opt in question.options:
            if opt.id == ai_q.selected_option_id:
                change = float(opt.points_change)
                earned = (
                    float(question.max_points) + change
                    if scoring_mode == ScoringMode.deduct
                    else change
                )
                return max(0.0, min(earned, float(question.max_points)))
        return float(question.max_points) if scoring_mode == ScoringMode.deduct else 0.0
    elif question.scoring_type == ScoringType.numeric:
        return max(0.0, min(float(ai_q.numeric_value or 0.0), float(question.max_points)))
    return 0.0  # tag_only


def calculate_scores(
    ai_questions: list[AIQuestionOutput],
    scorecard: ScorecardDefinition,
) -> tuple[list[SectionResult], float, float, bool]:
    """Return (section_results, overall_score_pct, total_earned_points, hard_critical_failure)."""
    ai_map = {q.question_id: q for q in ai_questions}
    section_results: list[SectionResult] = []
    total_earned = 0.0
    hard_critical_failure = False

    for section in scorecard.sections:
        section_earned = 0.0
        section_max = 0

        for question in section.questions:
            earned = _question_earned(ai_map[question.id], question, scorecard.scoring_mode)
            section_earned += earned
            section_max += question.max_points
            if question.critical == CriticalType.hard and earned == 0 and question.max_points > 0:
                hard_critical_failure = True

        total_earned += section_earned
        raw = (section_earned / section_max * 100) if section_max > 0 else 100.0
        section_results.append(
            SectionResult(
                section_id=section.id,
                section_name=section.name,
                score=round(max(0.0, min(raw, 100.0)), 1),
                weight=section.weight,
            )
        )

    overall = (total_earned / scorecard.max_score * 100) if scorecard.max_score > 0 else 0.0
    return section_results, round(max(0.0, min(overall, 100.0)), 1), round(total_earned, 1), hard_critical_failure


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

MAX_RETRIES = 3


async def run_assessment(
    request: AssessmentRequest,
    knowledge_base_context: str | None = None,
) -> AssessmentResult:
    llm = get_llm(provider=request.provider.value)
    chain = llm.with_structured_output(AIScoreOutput)

    scorecard_context = _build_scorecard_context(request.scorecard, knowledge_base_context)
    messages = [
        SystemMessage(content=_SYSTEM_PROMPT + "\n\n" + scorecard_context),
        HumanMessage(content=f"Evaluate the following content:\n\n{request.content}"),
    ]

    with logfire.span("run_assessment", scorecard_id=request.scorecard.id):
        ai_output: AIScoreOutput | None = None
        last_error: Exception | None = None

        for attempt in range(MAX_RETRIES):
            try:
                ai_output = await chain.ainvoke(messages)
                _validate_output(ai_output, request.scorecard)
                break
            except Exception as e:
                last_error = e
                logfire.warn("Assessment attempt failed", attempt=attempt + 1, error=str(e))
                if attempt < MAX_RETRIES - 1:
                    messages.append(
                        HumanMessage(
                            content=(
                                f"Validation error: {e}\n"
                                "Please fix and respond again with the complete corrected output."
                            )
                        )
                    )

        if ai_output is None:
            raise last_error or RuntimeError("Assessment failed after retries.")

    section_results, overall_score, total_earned, hard_critical_failure = calculate_scores(
        ai_output.questions, request.scorecard
    )

    if hard_critical_failure:
        overall_score = 0.0

    if request.scorecard.passing_threshold is not None:
        passed: bool | None = (
            not hard_critical_failure and total_earned >= request.scorecard.passing_threshold
        )
    else:
        passed = None if not hard_critical_failure else False

    ai_map = {q.question_id: q for q in ai_output.questions}
    question_results: list[QuestionResult] = []
    for section in request.scorecard.sections:
        for question in section.questions:
            earned = _question_earned(ai_map[question.id], question, request.scorecard.scoring_mode)
            question_results.append(
                QuestionResult(
                    question_id=question.id,
                    section_id=section.id,
                    score=earned,
                    max_points=question.max_points,
                    passed=earned >= question.max_points * PASS_THRESHOLD,
                    critical=question.critical,
                    comment=ai_map[question.id].comment,
                    suggestions=ai_map[question.id].suggestions,
                )
            )

    return AssessmentResult(
        scorecard_id=request.scorecard.id,
        scorecard_version=request.scorecard.version,
        content_type=request.content_type,
        assessed_at=datetime.now(timezone.utc),
        overall=OverallResult(
            score=overall_score,
            max_score=100,
            passed=passed,
            hard_critical_failure=hard_critical_failure,
            summary=ai_output.summary,
        ),
        sections=section_results,
        questions=question_results,
    )
