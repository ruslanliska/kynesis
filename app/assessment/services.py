from dataclasses import dataclass
from functools import lru_cache

import logfire
from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext

from app.assessment.schemas import (
    AssessmentRequest,
    AssessmentResult,
    CriterionScore,
    Scorecard,
)
from app.core.ai_provider import get_ai_model


class AIScoreOutput(BaseModel):
    """Structured output the AI agent must produce for each criterion."""

    scores: list[CriterionScore]
    overall_feedback: str


@dataclass
class AssessmentDeps:
    scorecard: Scorecard
    knowledge_base_context: str | None = None


def _build_assessment_agent() -> Agent[AssessmentDeps, AIScoreOutput]:
    agent = Agent(
        get_ai_model(),
        result_type=AIScoreOutput,
        deps_type=AssessmentDeps,
        retries=3,
        system_prompt=(
            "You are an expert QA evaluator. You evaluate content against scorecard criteria "
            "and produce structured assessment scores.\n\n"
            "For each criterion, you MUST:\n"
            "1. Read the criterion name and description carefully\n"
            "2. Evaluate the provided content against that criterion\n"
            "3. Assign a score from 0 to the criterion's max_score\n"
            "4. Provide specific, actionable feedback citing evidence from the content\n\n"
            "Be fair, precise, and cite specific examples from the content."
        ),
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

    @agent.result_validator
    async def validate_scores(
        ctx: RunContext[AssessmentDeps], result: AIScoreOutput
    ) -> AIScoreOutput:
        scorecard = ctx.deps.scorecard
        criterion_ids = {c.id for c in scorecard.criteria}
        result_ids = {s.criterion_id for s in result.scores}

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
        for score in result.scores:
            criterion = criteria_map[score.criterion_id]
            if score.score > criterion.max_score:
                raise ValueError(
                    f"Score {score.score} for '{score.criterion_name}' exceeds "
                    f"max_score {criterion.max_score}. Please correct."
                )

        return result

    return agent


@lru_cache
def get_assessment_agent() -> Agent[AssessmentDeps, AIScoreOutput]:
    return _build_assessment_agent()


def calculate_weighted_score(
    scores: list[CriterionScore], scorecard: Scorecard
) -> float:
    criteria_map = {c.id: c for c in scorecard.criteria}
    total_weight = sum(c.weight for c in scorecard.criteria)

    if total_weight == 0:
        return 0.0

    weighted_sum = sum(
        (s.score / criteria_map[s.criterion_id].max_score) * criteria_map[s.criterion_id].weight
        for s in scores
    )

    return round(weighted_sum / total_weight * 100, 2)


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

        ai_output = result.data
        total_score = calculate_weighted_score(ai_output.scores, request.scorecard)

        return AssessmentResult(
            scorecard_id=request.scorecard.id,
            scorecard_name=request.scorecard.name,
            subject=request.subject,
            scores=ai_output.scores,
            total_score=total_score,
            overall_feedback=ai_output.overall_feedback,
            knowledge_base_used=knowledge_base_context is not None,
        )
