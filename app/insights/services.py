from functools import lru_cache

import logfire
from pydantic_ai import Agent

from app.assessment.schemas import AssessmentResult
from app.core.ai_provider import get_ai_model
from app.insights.schemas import InsightReport


def _build_insights_agent() -> Agent[None, InsightReport]:
    agent = Agent(
        get_ai_model(),
        result_type=InsightReport,
        retries=3,
        system_prompt=(
            "You are an expert QA analytics specialist. You analyze sets of assessment "
            "results to identify patterns, issues, strengths, weaknesses, and actionable "
            "recommendations.\n\n"
            "Given a set of assessment results, you MUST:\n"
            "1. Identify the top issues — recurring low scores or problems across assessments\n"
            "2. Detect patterns — trends in scoring, common themes\n"
            "3. Provide prioritized recommendations with expected impact\n"
            "4. Identify strength areas (consistently high-scoring criteria)\n"
            "5. Identify weak areas with improvement suggestions\n"
            "6. Write an executive summary (2-3 sentences)\n\n"
            "Be specific. Reference actual criterion names and score data. "
            "Frequency counts must reflect actual assessment data.\n\n"
            "If assessments span multiple scorecards, differentiate patterns per scorecard "
            "while also identifying cross-scorecard trends."
        ),
    )
    return agent


@lru_cache
def get_insights_agent() -> Agent[None, InsightReport]:
    return _build_insights_agent()


def _format_assessments_for_prompt(assessments: list[AssessmentResult]) -> str:
    parts = []
    for i, a in enumerate(assessments, 1):
        scores_text = "\n".join(
            f"    - {s.criterion_name}: {s.score}/{s.max_score} — {s.feedback}"
            for s in a.scores
        )
        parts.append(
            f"Assessment {i}: {a.subject} (Scorecard: {a.scorecard_name})\n"
            f"  Overall Score: {a.total_score}/100\n"
            f"  Scores:\n{scores_text}\n"
            f"  Overall Feedback: {a.overall_feedback}"
        )
    return "\n\n".join(parts)


async def generate_insights(assessments: list[AssessmentResult]) -> InsightReport:
    with logfire.span("generate_insights", assessment_count=len(assessments)):
        prompt = (
            f"Analyze the following {len(assessments)} assessment results and "
            f"provide structured insights:\n\n"
            f"{_format_assessments_for_prompt(assessments)}"
        )

        agent = get_insights_agent()
        result = await agent.run(prompt, model=get_ai_model())
        return result.data
