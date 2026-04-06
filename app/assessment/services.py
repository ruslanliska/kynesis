from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache

import logfire
from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext

from app.assessment.schemas import (
    PASS_THRESHOLD,
    AssessmentRequest,
    AssessmentResult,
    OverallResult,
    QuestionResult,
    SectionResult,
)
from app.assessment.schemas import AIProvider
from app.core.ai_provider import get_ai_model, get_deepseek_model
from app.scorecards.schemas import (
    CriticalType,
    ScorecardDefinition,
    ScorecardQuestion,
    ScoringMode,
    ScoringType,
)


# --- Chain-of-Thought structured output ---
# The AI must fill fields in order: evidence → reasoning → answer → comment → suggestions
# This forces the model to THINK before SCORING.


class AIQuestionOutput(BaseModel):
    """Chain-of-thought output per question. Fields are ordered to force reasoning before answering."""

    question_id: str

    # For binary / scale questions: the ID of the chosen option
    selected_option_id: str | None = Field(
        default=None,
        description=(
            "The ID of the selected answer option. Required for binary and scale questions. "
            "Must be one of the option IDs listed for this question."
        ),
    )

    # For numeric questions: a value between 0 and max_points
    numeric_value: float | None = Field(
        default=None,
        description=(
            "The numeric score for this question. Required for numeric scoring type. "
            "Must be between 0 and the question's maxPoints."
        ),
    )

    # Step 1: Extract — what raw evidence exists in the content?
    evidence: list[str] = Field(
        description=(
            "Direct quotes, timestamps, or data points from the content relevant to this question. "
            "Each item must be a verbatim excerpt or precise observation. "
            "If timestamps exist, include calculated durations (e.g., '10:00:47Z to 10:01:05Z = 18 seconds')."
        ),
    )

    # Step 2: Reason — what does the evidence mean?
    reasoning: str = Field(
        description=(
            "Analysis of the evidence against the question. "
            "What does the evidence prove? What is missing? Any contradictions? "
            "This MUST be written before selecting an answer."
        ),
    )

    # Step 3: Comment — human-readable summary
    comment: str = Field(
        description="Concise assessment referencing specific evidence. No claims without backing.",
    )

    # Step 4: Suggest — actionable improvements
    suggestions: str | None = Field(
        default=None,
        description="Concrete suggestions if full points not achieved. Null if perfect.",
    )


class AIScoreOutput(BaseModel):
    """Full chain-of-thought assessment output."""

    # Think first: overall observations before per-question analysis
    content_analysis: str = Field(
        description=(
            "Brief factual summary of the content: type, length, key participants, "
            "timeline (if timestamps present), and any notable structural features. "
            "This grounds the entire assessment in observable facts."
        ),
    )

    questions: list[AIQuestionOutput]

    # Synthesize after all questions are evaluated
    summary: str = Field(
        description=(
            "Executive summary synthesizing patterns across all sections and questions. "
            "Reference the strongest and weakest areas with specific evidence."
        ),
    )


@dataclass
class AssessmentDeps:
    scorecard: ScorecardDefinition
    knowledge_base_context: str | None = None


SYSTEM_PROMPT = (
    "You are a rigorous QA auditor performing evidence-based assessments.\n\n"

    "## CHAIN-OF-THOUGHT PROCESS\n\n"
    "You MUST think step-by-step for every question. The structured output enforces this:\n\n"
    "1. **content_analysis** — First, summarize what you're looking at: content type, "
    "participants, timeline, length. Establish facts before judging.\n\n"
    "2. For EACH question:\n"
    "   a. **evidence** — Extract ALL relevant quotes, timestamps, data points verbatim. "
    "If timestamps exist, CALCULATE exact durations (e.g., '10:00:47Z → 10:01:32Z = 45s'). "
    "Never paraphrase when you can quote.\n"
    "   b. **reasoning** — Analyze what the evidence proves and what's missing. "
    "Check for contradictions. This is your thinking step — be thorough.\n"
    "   c. **selected_option_id or numeric_value** — Only NOW select an answer, "
    "justified solely by your reasoning.\n"
    "   d. **comment** — Summarize for a human reader. Every claim must trace back to evidence.\n"
    "   e. **suggestions** — Actionable improvements tied to specific gaps. "
    "Null only if full points achieved.\n\n"
    "3. **summary** — After ALL questions, synthesize cross-cutting patterns.\n\n"

    "## ANSWER SELECTION\n\n"
    "- **Binary / Scale questions**: Set `selected_option_id` to EXACTLY one of the provided "
    "option IDs. Do NOT invent or guess option IDs.\n"
    "- **Numeric questions**: Set `numeric_value` to a number between 0 and maxPoints. "
    "Leave `selected_option_id` null.\n"
    "- **Tag-only questions**: Set `selected_option_id` to one of the provided option IDs "
    "(for categorization only — no point impact).\n\n"

    "## CRITICAL RULES\n\n"
    "- NEVER claim something happened without a matching entry in your evidence list.\n"
    "- If timestamps are present, you MUST compute actual time differences. "
    "'Responded quickly' is NOT acceptable — '18 seconds' IS.\n"
    "- Your reasoning field must be filled BEFORE selecting an answer. If your reasoning "
    "contradicts your selection, fix the selection.\n"
    "- When evidence is ambiguous or absent, state that explicitly and score conservatively.\n"
    "- Cross-verify: after writing your comment, re-read your evidence list. "
    "If the comment claims something not in the evidence, delete the claim.\n"
    "- Questions marked HARD CRITICAL auto-fail the entire assessment if scored 0. "
    "Be especially rigorous with evidence before awarding 0 on these.\n"
)


def _build_assessment_agent() -> Agent[AssessmentDeps, AIScoreOutput]:
    agent = Agent(
        get_ai_model(),
        output_type=AIScoreOutput,
        deps_type=AssessmentDeps,
        retries=3,
        system_prompt=SYSTEM_PROMPT,
    )

    @agent.system_prompt
    async def add_scorecard_context(ctx: RunContext[AssessmentDeps]) -> str:
        scorecard = ctx.deps.scorecard
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

                if question.scoring_type in (
                    ScoringType.binary, ScoringType.scale, ScoringType.tag_only
                ):
                    lines.append("Options:")
                    for opt in sorted(question.options, key=lambda o: o.order_index):
                        pts = (
                            f"+{opt.points_change}"
                            if opt.points_change >= 0
                            else str(opt.points_change)
                        )
                        lines.append(f"  - option_id: {opt.id!r} | {opt.label} | {pts} pts")
                    lines.append("► Set `selected_option_id` to one of the option_id values above.")
                elif question.scoring_type == ScoringType.numeric:
                    lines.append(
                        f"► Set `numeric_value` to a number between 0 and {question.max_points}."
                    )
                lines.append("")

        if ctx.deps.knowledge_base_context:
            lines += [
                "## Reference Knowledge Base Context",
                ctx.deps.knowledge_base_context,
                "Use this context to inform your evaluation.",
                "",
            ]

        return "\n".join(lines)

    @agent.output_validator
    async def validate_output(
        ctx: RunContext[AssessmentDeps], result: AIScoreOutput
    ) -> AIScoreOutput:
        scorecard = ctx.deps.scorecard

        question_map: dict[str, ScorecardQuestion] = {}
        for section in scorecard.sections:
            for q in section.questions:
                question_map[q.id] = q

        expected_ids = set(question_map.keys())
        result_ids = {q.question_id for q in result.questions}

        if result_ids != expected_ids:
            missing = expected_ids - result_ids
            extra = result_ids - expected_ids
            parts = []
            if missing:
                parts.append(f"Missing questions: {missing}")
            if extra:
                parts.append(f"Unexpected questions: {extra}")
            raise ValueError(
                f"Scores must match scorecard questions exactly. {'; '.join(parts)}"
            )

        for ai_q in result.questions:
            question = question_map[ai_q.question_id]

            if not ai_q.evidence and question.scoring_type != ScoringType.tag_only:
                raise ValueError(
                    f"Question '{question.text}' has no evidence extracted. "
                    "You must cite specific content before scoring."
                )

            if question.scoring_type in (ScoringType.binary, ScoringType.scale):
                if ai_q.selected_option_id is None:
                    raise ValueError(
                        f"Question '{question.text}' (binary/scale) requires selected_option_id."
                    )
                valid_ids = {o.id for o in question.options}
                if ai_q.selected_option_id not in valid_ids:
                    raise ValueError(
                        f"selected_option_id '{ai_q.selected_option_id}' for question "
                        f"'{question.text}' is not valid. Valid IDs: {valid_ids}"
                    )

            elif question.scoring_type == ScoringType.numeric:
                if ai_q.numeric_value is None:
                    raise ValueError(
                        f"Question '{question.text}' (numeric) requires numeric_value."
                    )
                if not (0 <= ai_q.numeric_value <= question.max_points):
                    raise ValueError(
                        f"numeric_value {ai_q.numeric_value} for '{question.text}' "
                        f"must be between 0 and {question.max_points}."
                    )

        return result

    return agent


@lru_cache
def get_assessment_agent() -> Agent[AssessmentDeps, AIScoreOutput]:
    return _build_assessment_agent()


def _calculate_question_earned_points(
    ai_q: AIQuestionOutput,
    question: ScorecardQuestion,
    scoring_mode: ScoringMode,
) -> float:
    """
    Add mode:    earned = points_change          (0 → max_points)
    Deduct mode: earned = max_points + points_change  (points_change ≤ 0)
    Tag-only:    earned = 0 (no score impact)
    """
    if question.scoring_type in (ScoringType.binary, ScoringType.scale):
        for opt in question.options:
            if opt.id == ai_q.selected_option_id:
                change = float(opt.points_change)
                if scoring_mode == ScoringMode.deduct:
                    earned = float(question.max_points) + change
                else:
                    earned = change
                return max(0.0, min(earned, float(question.max_points)))
        # Fallback: no match found
        return float(question.max_points) if scoring_mode == ScoringMode.deduct else 0.0
    elif question.scoring_type == ScoringType.numeric:
        return max(0.0, min(float(ai_q.numeric_value or 0.0), float(question.max_points)))
    else:  # tag_only — no score impact
        return 0.0


def calculate_scores(
    ai_questions: list[AIQuestionOutput],
    scorecard: ScorecardDefinition,
) -> tuple[list[SectionResult], float, bool]:
    """Return (section_results, overall_score_0_to_100, hard_critical_failure).

    Overall score = total_earned / scorecard.max_score * 100.
    Section scores are for display only (earned / section_max_points * 100).
    Tag-only questions contribute 0 to both earned and max, so they are excluded.
    """
    ai_map = {q.question_id: q for q in ai_questions}
    section_results: list[SectionResult] = []
    total_earned = 0.0
    hard_critical_failure = False

    for section in scorecard.sections:
        section_earned = 0.0
        section_max = 0

        for question in section.questions:
            ai_q = ai_map[question.id]
            earned = _calculate_question_earned_points(ai_q, question, scorecard.scoring_mode)
            section_earned += earned
            section_max += question.max_points

            if question.critical == CriticalType.hard and earned == 0 and question.max_points > 0:
                hard_critical_failure = True

        total_earned += section_earned
        raw_section = (section_earned / section_max * 100) if section_max > 0 else 100.0
        section_results.append(
            SectionResult(
                section_id=section.id,
                section_name=section.name,
                score=round(max(0.0, min(raw_section, 100.0)), 1),
                weight=section.weight,
            )
        )

    overall = (total_earned / scorecard.max_score * 100) if scorecard.max_score > 0 else 0.0
    return section_results, round(max(0.0, min(overall, 100.0)), 1), hard_critical_failure


async def run_assessment(
    request: AssessmentRequest,
    knowledge_base_context: str | None = None,
) -> AssessmentResult:
    with logfire.span("run_assessment", scorecard_id=request.scorecard.id):
        deps = AssessmentDeps(
            scorecard=request.scorecard,
            knowledge_base_context=knowledge_base_context,
        )

        prompt = f"Evaluate the following content:\n\n{request.content}"

        model = (
            get_deepseek_model()
            if request.provider == AIProvider.deepseek
            else get_ai_model()
        )

        agent = get_assessment_agent()
        result = await agent.run(prompt, deps=deps, model=model)

        ai_output = result.output
        section_results, overall_score, hard_critical_failure = calculate_scores(
            ai_output.questions, request.scorecard
        )

        # Build question results
        ai_map = {q.question_id: q for q in ai_output.questions}
        question_results: list[QuestionResult] = []
        for section in request.scorecard.sections:
            for question in section.questions:
                ai_q = ai_map[question.id]
                earned = _calculate_question_earned_points(ai_q, question, request.scorecard.scoring_mode)
                question_results.append(
                    QuestionResult(
                        question_id=question.id,
                        section_id=section.id,
                        score=earned,
                        max_points=question.max_points,
                        passed=earned >= question.max_points * PASS_THRESHOLD,
                        critical=question.critical,
                        comment=ai_q.comment,
                        suggestions=ai_q.suggestions,
                    )
                )

        # Hard critical failure overrides the score to 0
        if hard_critical_failure:
            overall_score = 0.0

        # Determine pass/fail
        if request.scorecard.passing_threshold is not None:
            passed: bool | None = overall_score >= request.scorecard.passing_threshold
        else:
            passed = None if not hard_critical_failure else False

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
