from datetime import datetime, timezone

import asyncio
import json
import logging
import re
import time

import logfire
from langchain_core.messages import HumanMessage, SystemMessage
from langsmith import traceable
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

from app.assessment.schemas import (
    AggregatedReasoning,
    AIProvider,
    AssessmentRequest,
    AssessmentResult,
    ContentType,
    OverallResult,
    PASS_THRESHOLD,
    QuestionResult,
    ReasoningQuestionRecord,
    SectionResult,
    StageOutcome,
)
from app.core.ai_provider import get_llm, get_reasoning_llm, get_structuring_llm
from app.core.config import get_settings
from app.core.errors import (
    PipelineTimeoutError,
    ReasoningCoverageError,
    ReasoningPayloadTooLargeError,
    ReasoningUnavailableError,
)
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
    """Return (section_results, overall_score_pct, total_earned_points, hard_critical_failure).

    `overall_score_pct` is a true 0-100 percentage of question points earned, independent
    of the user-configured `scorecard.max_score` scale. This keeps the result correct even
    if a scorecard is ever submitted with `max_score != Σ question.max_points`.
    """
    ai_map = {q.question_id: q for q in ai_questions}
    section_results: list[SectionResult] = []
    total_earned = 0.0
    total_max_points = 0
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
        total_max_points += section_max
        raw = (section_earned / section_max * 100) if section_max > 0 else 100.0
        section_results.append(
            SectionResult(
                section_id=section.id,
                section_name=section.name,
                score=round(max(0.0, min(raw, 100.0)), 1),
                weight=section.weight,
            )
        )

    overall = (total_earned / total_max_points * 100) if total_max_points > 0 else 0.0
    return section_results, round(max(0.0, min(overall, 100.0)), 1), round(total_earned, 1), hard_critical_failure


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

MAX_RETRIES = 3


async def run_legacy_assessment(
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

    section_results, overall_score, _, hard_critical_failure = calculate_scores(
        ai_output.questions, request.scorecard
    )

    if hard_critical_failure:
        overall_score = 0.0

    if request.scorecard.passing_threshold is not None:
        threshold_pct = (
            request.scorecard.passing_threshold / request.scorecard.max_score * 100
            if request.scorecard.max_score > 0
            else 0.0
        )
        passed: bool | None = (
            not hard_critical_failure and overall_score >= threshold_pct
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


# ---------------------------------------------------------------------------
# Two-stage reasoning pipeline (feature 003-reasoning-aggregation)
# ---------------------------------------------------------------------------

_REASONING_SYSTEM_PROMPT = """\
You are a rigorous QA auditor producing a deep, evidence-grounded reasoning pass.

## YOUR TASK
Analyse the content below against EVERY question on the scorecard. Produce a thorough rationale for each question BEFORE any score is computed by the downstream formatter.

## OUTPUT FORMAT — STRICT
For every question in the scorecard, emit a block of the form:

### Q: <question_id>
<Your analysis: what the evidence says, which evidence is relevant (verbatim quotes),
what is missing, and the answer the evidence best supports — naming the exact option_id
or numeric value. At least 50 characters, ideally 2–6 sentences.>

Use the EXACT question id from the scorecard as `<question_id>` (do not paraphrase).
Do not merge questions. Do not add commentary outside the `### Q:` blocks.

## RULES
- Never claim something happened without verbatim evidence from the content.
- For HARD CRITICAL questions, explicitly state whether the evidence supports awarding points.
- Compute actual time differences when timestamps exist.
- Score conservatively when evidence is absent or ambiguous.
"""


_STRUCTURING_SYSTEM_PROMPT = """\
You are a TRANSCRIBER. Your sole job is to serialise a prior reasoning analysis into
the structured response schema. You MUST NOT re-evaluate, second-guess, or contradict
the reasoning.

## RULES — BINDING
1. The reasoning below is AUTHORITATIVE prior analysis. Transcribe its conclusions.
   Do not re-evaluate, override scores, or introduce new evidence.
2. Every `evidence` quote MUST appear verbatim in either the rationale or the source
   content. Do not invent evidence.
3. `selected_option_id` / `numeric_value` for each question MUST match the answer
   indicated by the rationale for that question.
4. `comment` MUST NOT assert facts absent from or contradicted by the rationale.
5. Temperature is low by design; prefer the reasoner's wording over paraphrase.
6. For HARD CRITICAL questions, preserve the reasoner's verdict exactly — a
   hard-critical zero MUST NOT be softened.
"""


# Char-to-token heuristic. DeepSeek/GPT context windows are large, but we want a
# conservative ceiling to catch pathological inputs before a network round-trip.
# 400_000 chars ≈ 100k tokens at ~4 chars/token — well under deepseek-chat's
# 128k input window, leaving room for system prompt + structured-output schema.
_STRUCTURING_PROMPT_CHAR_BUDGET = 400_000


_Q_HEADER_RE = re.compile(r"^###\s*Q:\s*(\S.*?)\s*$", re.MULTILINE)


def parse_reasoning_response(
    text: str, scorecard: ScorecardDefinition
) -> list[ReasoningQuestionRecord]:
    """Parse `### Q: <id>` blocks from a reasoner's response.

    Unknown or misformatted headers raise ValueError. Missing questions are
    detected by the caller (coverage check).
    """
    expected_ids = {q.id for s in scorecard.sections for q in s.questions}

    matches = list(_Q_HEADER_RE.finditer(text))
    if not matches:
        raise ValueError(
            "Reasoning response contained no '### Q: <id>' blocks; cannot parse."
        )

    records: list[ReasoningQuestionRecord] = []
    seen: set[str] = set()
    for idx, match in enumerate(matches):
        qid = match.group(1).strip()
        if qid not in expected_ids:
            raise ValueError(
                f"Reasoning response references unknown question id: {qid!r}"
            )
        if qid in seen:
            raise ValueError(
                f"Reasoning response contains duplicate block for question id: {qid!r}"
            )
        seen.add(qid)
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        rationale = text[start:end].strip()
        if not rationale:
            records.append(
                ReasoningQuestionRecord(question_id=qid, rationale="", status="missing")
            )
        else:
            records.append(
                ReasoningQuestionRecord(question_id=qid, rationale=rationale, status="ok")
            )

    return records


@traceable(name="reasoning_stage", run_type="chain")
async def reasoning_stage(
    request: AssessmentRequest,
    knowledge_base_context: str | None = None,
) -> AggregatedReasoning:
    """First stage — produce per-question rationale via the reasoning model.

    On coverage failure (any scorecard question missing from the response) raises
    ReasoningCoverageError — the orchestrator treats this as a retryable reasoning
    failure.
    """
    llm = get_reasoning_llm()
    scorecard_context = _build_scorecard_context(request.scorecard, knowledge_base_context)
    messages = [
        SystemMessage(content=_REASONING_SYSTEM_PROMPT + "\n\n" + scorecard_context),
        HumanMessage(content=f"Evaluate the following content:\n\n{request.content}"),
    ]

    with logfire.span("reasoning_stage", scorecard_id=request.scorecard.id):
        response = await llm.ainvoke(messages)

    text = response.content if isinstance(response.content, str) else str(response.content)
    thinking_trace = None
    if hasattr(response, "additional_kwargs") and isinstance(response.additional_kwargs, dict):
        trace = response.additional_kwargs.get("reasoning_content")
        if isinstance(trace, str) and trace.strip():
            thinking_trace = trace

    records = parse_reasoning_response(text, request.scorecard)

    # Coverage check — must have one record per scorecard question.
    expected_ids = {q.id for s in request.scorecard.sections for q in s.questions}
    produced_ids = {r.question_id for r in records}
    missing = expected_ids - produced_ids
    if missing:
        raise ReasoningCoverageError(missing)

    # Attach thinking trace to every record (single-call reasoning per plan).
    if thinking_trace is not None:
        records = [
            ReasoningQuestionRecord(
                question_id=r.question_id,
                rationale=r.rationale,
                thinking_trace=thinking_trace,
                status=r.status,
            )
            for r in records
        ]

    return AggregatedReasoning(
        scorecard_id=request.scorecard.id,
        content_type=request.content_type,
        content_preview=request.content[:500],
        records=records,
        full_trace_available=all(r.status == "ok" for r in records) and thinking_trace is not None,
    )


def _format_reasoning_for_structuring(reasoning: AggregatedReasoning) -> str:
    lines = ["## Prior Reasoning (authoritative — transcribe, do not re-evaluate)", ""]
    for r in reasoning.records:
        lines.append(f"### Q: {r.question_id}")
        lines.append(r.rationale)
        lines.append("")
    return "\n".join(lines)


@traceable(name="structuring_stage", run_type="chain")
async def structuring_stage(
    request: AssessmentRequest,
    reasoning: AggregatedReasoning,
    knowledge_base_context: str | None = None,
) -> "AIScoreOutput":
    """Second stage — serialise the reasoner's conclusions into AIScoreOutput.

    Runs at low temperature (pinned via get_structuring_llm). Retries on
    validation failure, reusing the same reasoning artifact across retries.
    Raises ReasoningPayloadTooLargeError pre-emptively when the prompt size
    exceeds the structuring model's input budget (FR-014) — no LLM call made.
    """
    settings = get_settings()
    llm = get_structuring_llm()
    chain = llm.with_structured_output(AIScoreOutput)

    scorecard_context = _build_scorecard_context(request.scorecard, knowledge_base_context)
    reasoning_block = _format_reasoning_for_structuring(reasoning)

    system_prompt = (
        _STRUCTURING_SYSTEM_PROMPT
        + "\n\n"
        + scorecard_context
        + "\n\n"
        + reasoning_block
    )
    user_prompt = f"Evaluate the following content:\n\n{request.content}"

    # FR-014: pre-flight oversize rejection. Compare total prompt chars against
    # the conservative budget BEFORE any network call.
    total_chars = len(system_prompt) + len(user_prompt)
    if total_chars > _STRUCTURING_PROMPT_CHAR_BUDGET:
        raise ReasoningPayloadTooLargeError()

    messages: list[SystemMessage | HumanMessage] = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_prompt),
    ]

    max_attempts = settings.assessment.structuring_retries + 1
    last_error: Exception | None = None
    for attempt in range(max_attempts):
        with logfire.span(
            "structuring_stage", scorecard_id=request.scorecard.id, attempt=attempt + 1
        ):
            try:
                ai_output = await chain.ainvoke(messages)
                _validate_output(ai_output, request.scorecard)
                return ai_output
            except Exception as e:  # noqa: BLE001 — we append feedback and retry
                last_error = e
                logfire.warn(
                    "Structuring attempt failed",
                    attempt=attempt + 1,
                    error=str(e),
                )
                if attempt < max_attempts - 1:
                    messages.append(
                        HumanMessage(
                            content=(
                                f"Validation error: {e}\n"
                                "Please fix and respond again with the complete corrected output. "
                                "Remember: transcribe the reasoning above; do not re-evaluate."
                            )
                        )
                    )

    # Exhausted all attempts.
    failing_qids: list[str] = []
    msg = str(last_error) if last_error else "unknown"
    raise AIProviderError(
        detail=(
            f"Assessment could not be scored after {max_attempts} structuring attempts. "
            f"Last error: {msg}"
        )
    )


async def _run_reasoning_with_retries(
    request: AssessmentRequest,
    knowledge_base_context: str | None,
) -> AggregatedReasoning:
    """Run reasoning_stage with settings.assessment.reasoning_retries + 1 attempts."""
    settings = get_settings()
    max_attempts = settings.assessment.reasoning_retries + 1
    last_error: Exception | None = None
    for attempt in range(max_attempts):
        try:
            return await reasoning_stage(request, knowledge_base_context)
        except Exception as e:  # noqa: BLE001 — retried or surfaced below
            last_error = e
            logfire.warn(
                "Reasoning attempt failed",
                attempt=attempt + 1,
                error=str(e),
            )
    # Reasoning exhausted — surface the last error to the orchestrator policy branch.
    raise last_error if last_error else RuntimeError("Reasoning stage failed with no error.")


def _compose_result(
    request: AssessmentRequest,
    ai_output: "AIScoreOutput",
    reasoning: AggregatedReasoning | None,
    mark_reasoning_unavailable: bool = False,
) -> AssessmentResult:
    """Shared result assembly — merges AIScoreOutput + calculate_scores + rationale.

    `reasoning` may be None when called from the fallback path or from a
    deliberately-chosen single-shot path; in that case every
    QuestionResult.rationale defaults to "". `mark_reasoning_unavailable`
    controls the OverallResult flag — set True only when the reasoning pipeline
    was requested and unavailable.
    """
    section_results, overall_score, _, hard_critical_failure = calculate_scores(
        ai_output.questions, request.scorecard
    )

    if hard_critical_failure:
        overall_score = 0.0

    if request.scorecard.passing_threshold is not None:
        threshold_pct = (
            request.scorecard.passing_threshold / request.scorecard.max_score * 100
            if request.scorecard.max_score > 0
            else 0.0
        )
        passed: bool | None = (
            not hard_critical_failure and overall_score >= threshold_pct
        )
    else:
        passed = None if not hard_critical_failure else False

    ai_map = {q.question_id: q for q in ai_output.questions}
    rationale_map: dict[str, str] = {}
    if reasoning is not None:
        rationale_map = {r.question_id: r.rationale for r in reasoning.records}

    question_results: list[QuestionResult] = []
    for section in request.scorecard.sections:
        for question in section.questions:
            earned = _question_earned(
                ai_map[question.id], question, request.scorecard.scoring_mode
            )
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
                    rationale=rationale_map.get(question.id, ""),
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
            reasoning_unavailable=mark_reasoning_unavailable,
        ),
        sections=section_results,
        questions=question_results,
    )


@traceable(name="assessment_pipeline", run_type="chain")
async def run_reasoning_assessment(
    request: AssessmentRequest,
    knowledge_base_context: str | None = None,
) -> AssessmentResult:
    """Two-stage orchestrator. Feature 003-reasoning-aggregation entrypoint.

    Enforces the 180s outer deadline. On reasoning-stage retry exhaustion:
      - failure_policy="fallback" → run legacy flow, label result reasoning_unavailable.
      - failure_policy="strict"   → raise ReasoningUnavailableError.
    """
    settings = get_settings()
    timeout_seconds = settings.assessment.request_timeout_seconds

    async def _inner() -> AssessmentResult:
        pipeline_start = time.monotonic()
        with logfire.span("assessment_pipeline", scorecard_id=request.scorecard.id):
            # --- Reasoning stage ---
            try:
                reasoning = await _run_reasoning_with_retries(request, knowledge_base_context)
            except (PipelineTimeoutError, ReasoningPayloadTooLargeError):
                raise
            except Exception as e:  # reasoning exhausted
                logfire.warn("Reasoning stage exhausted retries", error=str(e))
                return await _handle_reasoning_failure(request, knowledge_base_context)

            # Budget check before structuring stage.
            elapsed = time.monotonic() - pipeline_start
            remaining = timeout_seconds - elapsed
            if remaining < 10:
                raise PipelineTimeoutError(timeout_seconds)

            # --- Structuring stage ---
            ai_output = await structuring_stage(request, reasoning, knowledge_base_context)
            return _compose_result(request, ai_output, reasoning)

    try:
        return await asyncio.wait_for(_inner(), timeout=timeout_seconds)
    except asyncio.TimeoutError as e:
        raise PipelineTimeoutError(timeout_seconds) from e


async def _handle_reasoning_failure(
    request: AssessmentRequest,
    knowledge_base_context: str | None,
) -> AssessmentResult:
    """Apply FR-010 failure policy. Either fall back or raise."""
    settings = get_settings()
    if settings.assessment.failure_policy == "fallback":
        logfire.info("Falling back to legacy single-shot assessment")
        legacy_result = await run_legacy_assessment(request, knowledge_base_context)
        # Label the fallback result.
        legacy_result.overall = OverallResult(
            score=legacy_result.overall.score,
            max_score=legacy_result.overall.max_score,
            passed=legacy_result.overall.passed,
            hard_critical_failure=legacy_result.overall.hard_critical_failure,
            summary=legacy_result.overall.summary,
            reasoning_unavailable=True,
        )
        # Clear rationale on the fallback result — it didn't go through reasoning.
        legacy_result.questions = [
            QuestionResult(
                question_id=q.question_id,
                section_id=q.section_id,
                score=q.score,
                max_points=q.max_points,
                passed=q.passed,
                critical=q.critical,
                comment=q.comment,
                suggestions=q.suggestions,
                rationale="",
            )
            for q in legacy_result.questions
        ]
        return legacy_result
    # strict
    raise ReasoningUnavailableError()


# ---------------------------------------------------------------------------
# Image-assessment orchestrator (feature 004-image-assessment)
# ---------------------------------------------------------------------------


async def _run_vision_reasoning_with_retries(
    scorecard: ScorecardDefinition,
    image_bytes: bytes,
    filename: str,
    mime: str,
    knowledge_base_context: str | None,
) -> AggregatedReasoning:
    from app.assessment.image import vision_reasoning_stage

    settings = get_settings()
    max_attempts = settings.assessment.reasoning_retries + 1
    last_error: Exception | None = None
    for attempt in range(max_attempts):
        try:
            return await vision_reasoning_stage(
                scorecard, image_bytes, filename, mime, knowledge_base_context
            )
        except Exception as e:  # noqa: BLE001 — retried or surfaced below
            last_error = e
            logfire.warn(
                "Vision reasoning attempt failed",
                attempt=attempt + 1,
                error=str(e),
            )
    raise last_error if last_error else RuntimeError("Vision reasoning failed with no error.")


_IMAGE_CONTENT_PLACEHOLDER_TEMPLATE = (
    "[Image input — see vision-stage rationale for analysis. "
    "filename={filename}, size={size}B]"
)


@traceable(name="image_assessment", run_type="chain")
async def run_image_assessment(
    scorecard: ScorecardDefinition,
    image_bytes: bytes,
    filename: str,
    mime: str,
    use_knowledge_base: bool = False,
) -> AssessmentResult:
    """Feature 004 orchestrator — vision-based image assessment.

    Reuses the feature-003 structuring stage and result composition, with
    ``vision_reasoning_stage`` replacing the text reasoning stage. The overall
    wall-clock budget and fallback policy match ``run_reasoning_assessment``.
    """
    from app.assessment.image import image_describe_for_kb

    settings = get_settings()
    timeout_seconds = settings.assessment.request_timeout_seconds

    # Top-level Logfire span per data-model §6. Metadata only — no image bytes.
    with logfire.span(
        "image_assessment",
        scorecard_id=scorecard.id,
        filename=filename,
        mime=mime,
        size_bytes=len(image_bytes),
        use_knowledge_base=use_knowledge_base,
    ) as span:

        async def _inner() -> AssessmentResult:
            pipeline_start = time.monotonic()

            # --- Optional KB retrieval: describe-then-query ---
            knowledge_base_context: str | None = None
            kb_hit = False
            if use_knowledge_base:
                try:
                    description = await image_describe_for_kb(image_bytes, filename, mime)
                    from app.knowledge_base.services import get_rag_context

                    knowledge_base_context = await get_rag_context(scorecard.id, description)
                    kb_hit = bool(knowledge_base_context)
                except Exception as e:  # noqa: BLE001 — KB failure is non-fatal
                    logfire.warn("Knowledge base retrieval failed for image", error=str(e))
                    knowledge_base_context = None
            try:
                span.set_attribute("knowledge_base_hit", kb_hit)
            except Exception:  # pragma: no cover — span API differences
                pass

            # --- Build request artefact for reuse of structuring_stage ---
            # See data-model.md §5 — the ``content`` placeholder exists solely
            # to satisfy the ≥50-char Pydantic validator on AssessmentRequest.
            # It is never sent to the vision model and is not surfaced to users.
            placeholder = _IMAGE_CONTENT_PLACEHOLDER_TEMPLATE.format(
                filename=filename, size=len(image_bytes)
            )
            if len(placeholder) < 50:
                placeholder = placeholder.ljust(50, ".")
            request = AssessmentRequest(
                scorecard=scorecard,
                content=placeholder,
                content_type=ContentType.image,
                use_knowledge_base=use_knowledge_base,
            )

            # --- Vision reasoning stage ---
            try:
                reasoning = await _run_vision_reasoning_with_retries(
                    scorecard, image_bytes, filename, mime, knowledge_base_context
                )
            except (PipelineTimeoutError, ReasoningPayloadTooLargeError):
                raise
            except Exception as e:  # reasoning exhausted
                logfire.warn("Vision reasoning stage exhausted retries", error=str(e))
                if settings.assessment.failure_policy == "strict":
                    raise ReasoningUnavailableError()
                # Fallback (image path does NOT silently downgrade to OCR —
                # see research R9). Surface as AIProviderError (502) because
                # the failure is upstream.
                from app.core.errors import AIProviderError

                raise AIProviderError(
                    detail=(
                        "Image could not be evaluated reliably. "
                        "Please retry or use a different image."
                    )
                )

            # Budget check before structuring stage.
            elapsed = time.monotonic() - pipeline_start
            remaining = timeout_seconds - elapsed
            if remaining < 10:
                raise PipelineTimeoutError(timeout_seconds)

            # --- Structuring stage (reused unchanged) ---
            ai_output = await structuring_stage(request, reasoning, knowledge_base_context)
            return _compose_result(request, ai_output, reasoning)

        try:
            result = await asyncio.wait_for(_inner(), timeout=timeout_seconds)
            try:
                span.set_attribute("outcome", "ok")
            except Exception:  # pragma: no cover
                pass
            return result
        except asyncio.TimeoutError as e:
            raise PipelineTimeoutError(timeout_seconds) from e


@traceable(name="image_assessment_legacy", run_type="chain")
async def run_legacy_image_assessment(
    scorecard: ScorecardDefinition,
    image_bytes: bytes,
    filename: str,
    mime: str,
    use_knowledge_base: bool = False,
) -> AssessmentResult:
    """Single-shot vision orchestrator — counterpart of ``run_legacy_assessment``
    for the image endpoint. Skips the reasoning/structuring split and calls the
    vision LLM once with structured output.
    """
    from app.assessment.image import image_describe_for_kb, vision_single_shot_assessment

    settings = get_settings()
    timeout_seconds = settings.assessment.request_timeout_seconds

    with logfire.span(
        "image_assessment",
        scorecard_id=scorecard.id,
        filename=filename,
        mime=mime,
        size_bytes=len(image_bytes),
        use_knowledge_base=use_knowledge_base,
        assessment_type="standard",
    ) as span:

        async def _inner() -> AssessmentResult:
            knowledge_base_context: str | None = None
            kb_hit = False
            if use_knowledge_base:
                try:
                    description = await image_describe_for_kb(image_bytes, filename, mime)
                    from app.knowledge_base.services import get_rag_context

                    knowledge_base_context = await get_rag_context(scorecard.id, description)
                    kb_hit = bool(knowledge_base_context)
                except Exception as e:  # noqa: BLE001 — KB failure is non-fatal
                    logfire.warn(
                        "Knowledge base retrieval failed for image (legacy)", error=str(e)
                    )
                    knowledge_base_context = None
            try:
                span.set_attribute("knowledge_base_hit", kb_hit)
            except Exception:  # pragma: no cover
                pass

            placeholder = _IMAGE_CONTENT_PLACEHOLDER_TEMPLATE.format(
                filename=filename, size=len(image_bytes)
            )
            if len(placeholder) < 50:
                placeholder = placeholder.ljust(50, ".")
            request = AssessmentRequest(
                scorecard=scorecard,
                content=placeholder,
                content_type=ContentType.image,
                use_knowledge_base=use_knowledge_base,
            )

            ai_output = await vision_single_shot_assessment(
                scorecard, image_bytes, filename, mime, knowledge_base_context
            )
            return _compose_result(request, ai_output, reasoning=None)

        try:
            result = await asyncio.wait_for(_inner(), timeout=timeout_seconds)
            try:
                span.set_attribute("outcome", "ok")
            except Exception:  # pragma: no cover
                pass
            return result
        except asyncio.TimeoutError as e:
            raise PipelineTimeoutError(timeout_seconds) from e
