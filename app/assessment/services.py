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
    CriterionResult,
    OverallResult,
    Scorecard,
)
from app.core.ai_provider import get_ai_model


# --- Chain-of-Thought structured output ---
# The AI must fill fields in order: evidence → reasoning → score → comment → suggestions
# This forces the model to THINK before SCORING.


class AICriterionOutput(BaseModel):
    """Chain-of-thought output per criterion. Fields are ordered to force reasoning before scoring."""

    criterion_id: str

    # Step 1: Extract — what raw evidence exists in the content?
    evidence: list[str] = Field(
        description=(
            "Direct quotes, timestamps, or data points from the content relevant to this criterion. "
            "Each item must be a verbatim excerpt or precise observation. "
            "If timestamps exist, include calculated durations (e.g., '10:00:47Z to 10:01:05Z = 18 seconds')."
        ),
    )

    # Step 2: Reason — what does the evidence mean?
    reasoning: str = Field(
        description=(
            "Analysis of the evidence against the criterion. "
            "What does the evidence prove? What is missing? Any contradictions? "
            "This MUST be written before deciding on a score."
        ),
    )

    # Step 3: Score — only after evidence + reasoning
    score: float = Field(
        ge=0,
        description="Score based ONLY on what the evidence and reasoning support.",
    )

    # Step 4: Comment — human-readable summary
    comment: str = Field(
        description="Concise assessment referencing specific evidence. No claims without backing.",
    )

    # Step 5: Suggest — actionable improvements
    suggestions: str | None = Field(
        default=None,
        description="Concrete suggestions if score < max_score. Null if score is perfect.",
    )


class AIScoreOutput(BaseModel):
    """Full chain-of-thought assessment output."""

    # Think first: overall observations before per-criterion analysis
    content_analysis: str = Field(
        description=(
            "Brief factual summary of the content: type, length, key participants, "
            "timeline (if timestamps present), and any notable structural features. "
            "This grounds the entire assessment in observable facts."
        ),
    )

    criteria: list[AICriterionOutput]

    # Synthesize after all criteria are evaluated
    summary: str = Field(
        description=(
            "Executive summary synthesizing patterns across all criteria. "
            "Reference the strongest and weakest areas with specific evidence."
        ),
    )


@dataclass
class AssessmentDeps:
    scorecard: Scorecard
    knowledge_base_context: str | None = None


SYSTEM_PROMPT = (
    "You are a rigorous QA auditor performing evidence-based assessments.\n\n"

    "## CHAIN-OF-THOUGHT PROCESS\n\n"
    "You MUST think step-by-step for every criterion. The structured output enforces this:\n\n"
    "1. **content_analysis** — First, summarize what you're looking at: content type, "
    "participants, timeline, length. Establish facts before judging.\n\n"
    "2. For EACH criterion:\n"
    "   a. **evidence** — Extract ALL relevant quotes, timestamps, data points verbatim. "
    "If timestamps exist, CALCULATE exact durations (e.g., '10:00:47Z → 10:01:32Z = 45s'). "
    "Never paraphrase when you can quote.\n"
    "   b. **reasoning** — Analyze what the evidence proves and what's missing. "
    "Check for contradictions. This is your thinking step — be thorough.\n"
    "   c. **score** — Only NOW assign a score, justified by your reasoning. "
    "No evidence = low score, not an optimistic guess.\n"
    "   d. **comment** — Summarize for a human reader. Every claim must trace back to evidence.\n"
    "   e. **suggestions** — Actionable improvements tied to specific gaps. Null only if perfect.\n\n"
    "3. **summary** — After ALL criteria, synthesize cross-cutting patterns.\n\n"

    "## CRITICAL RULES\n\n"
    "- NEVER claim something happened without a matching entry in your evidence list.\n"
    "- If timestamps are present, you MUST compute actual time differences. "
    "'Responded quickly' is NOT acceptable — '18 seconds' IS.\n"
    "- Your reasoning field must be filled BEFORE your score. If your reasoning "
    "contradicts your score, fix the score.\n"
    "- When evidence is ambiguous or absent, state that explicitly and score conservatively.\n"
    "- Cross-verify: after writing your comment, re-read your evidence list. "
    "If the comment claims something not in the evidence, delete the claim.\n"
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
        criteria_text = "\n".join(
            f"- {c.name} (ID: {c.id}): {c.description} "
            f"[weight: {c.weight}, max_score: {c.max_score}]"
            for c in scorecard.criteria
        )
        prompt = f"Scorecard: {scorecard.name}\nCriteria:\n{criteria_text}"

        if ctx.deps.knowledge_base_context:
            prompt += (
                f"\n\nReference Knowledge Base Context:\n"
                f"{ctx.deps.knowledge_base_context}\n"
                f"Use this context to inform your evaluation."
            )

        return prompt

    @agent.output_validator
    async def validate_scores(
        ctx: RunContext[AssessmentDeps], result: AIScoreOutput
    ) -> AIScoreOutput:
        scorecard = ctx.deps.scorecard
        criterion_ids = {c.id for c in scorecard.criteria}
        result_ids = {s.criterion_id for s in result.criteria}

        if result_ids != criterion_ids:
            missing = criterion_ids - result_ids
            extra = result_ids - criterion_ids
            msg_parts = []
            if missing:
                msg_parts.append(f"Missing criteria: {missing}")
            if extra:
                msg_parts.append(f"Unexpected criteria: {extra}")
            raise ValueError(
                f"Scores must match scorecard criteria exactly. {'; '.join(msg_parts)}"
            )

        criteria_map = {c.id: c for c in scorecard.criteria}
        for score in result.criteria:
            criterion = criteria_map[score.criterion_id]
            if score.score > criterion.max_score:
                raise ValueError(
                    f"Score {score.score} for '{criterion.name}' exceeds "
                    f"max_score {criterion.max_score}. Please correct."
                )
            # Validate evidence is not empty
            if not score.evidence:
                raise ValueError(
                    f"Criterion '{criterion.name}' has no evidence extracted. "
                    f"You must cite specific content before scoring."
                )

        return result

    return agent


@lru_cache
def get_assessment_agent() -> Agent[AssessmentDeps, AIScoreOutput]:
    return _build_assessment_agent()


def calculate_weighted_score(
    ai_criteria: list[AICriterionOutput], scorecard: Scorecard
) -> float:
    criteria_map = {c.id: c for c in scorecard.criteria}
    total_weight = sum(c.weight for c in scorecard.criteria)

    if total_weight == 0:
        return 0.0

    weighted_sum = sum(
        (s.score / criteria_map[s.criterion_id].max_score) * criteria_map[s.criterion_id].weight
        for s in ai_criteria
    )

    return round(weighted_sum / total_weight * 100, 1)


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

        agent = get_assessment_agent()
        result = await agent.run(
            prompt,
            deps=deps,
            model=get_ai_model(),
        )

        ai_output = result.output
        overall_score = calculate_weighted_score(ai_output.criteria, request.scorecard)

        criteria_map = {c.id: c for c in request.scorecard.criteria}
        criteria_results = [
            CriterionResult(
                criterion_id=ai_c.criterion_id,
                score=ai_c.score,
                max_score=criteria_map[ai_c.criterion_id].max_score,
                passed=ai_c.score >= criteria_map[ai_c.criterion_id].max_score * PASS_THRESHOLD,
                comment=ai_c.comment,
                suggestions=ai_c.suggestions,
            )
            for ai_c in ai_output.criteria
        ]

        return AssessmentResult(
            scorecard_id=request.scorecard.id,
            scorecard_version=request.scorecard.version,
            content_type=request.content_type,
            assessed_at=datetime.now(timezone.utc),
            overall=OverallResult(
                score=overall_score,
                max_score=100,
                summary=ai_output.summary,
            ),
            criteria=criteria_results,
        )
