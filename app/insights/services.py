import logfire
from langchain_core.messages import HumanMessage, SystemMessage

from app.assessment.schemas import AssessmentResult
from app.core.ai_provider import get_llm
from app.insights.schemas import InsightReport

_SYSTEM_PROMPT = (
    "You are an expert QA analytics specialist. Analyse assessment results to identify "
    "patterns, issues, strengths, weaknesses, and actionable recommendations.\n\n"
    "You MUST:\n"
    "1. Identify top issues — recurring low scores or problems across assessments\n"
    "2. Detect patterns — trends in scoring, common themes\n"
    "3. Provide prioritised recommendations with expected impact\n"
    "4. Identify strength areas (consistently high-scoring)\n"
    "5. Identify weak areas with improvement suggestions\n"
    "6. Write an executive summary (2-3 sentences)\n\n"
    "Be specific. Reference actual question names and score data. "
    "If assessments span multiple scorecards, differentiate patterns per scorecard "
    "while also identifying cross-scorecard trends."
)


def _format_assessments(assessments: list[AssessmentResult]) -> str:
    parts = []
    for i, a in enumerate(assessments, 1):
        scores_text = "\n".join(
            f"    - {q.question_id}: {q.score}/{q.max_points} "
            f"({'PASS' if q.passed else 'FAIL'}) — {q.comment}"
            for q in a.questions
        )
        parts.append(
            f"Assessment {i}: Scorecard {a.scorecard_id} (v{a.scorecard_version})\n"
            f"  Type: {a.content_type.value}\n"
            f"  Overall: {a.overall.score}/100\n"
            f"  Summary: {a.overall.summary}\n"
            f"  Questions:\n{scores_text}"
        )
    return "\n\n".join(parts)


async def generate_insights(assessments: list[AssessmentResult]) -> InsightReport:
    chain = get_llm().with_structured_output(InsightReport)

    messages = [
        SystemMessage(content=_SYSTEM_PROMPT),
        HumanMessage(
            content=(
                f"Analyse the following {len(assessments)} assessment results:\n\n"
                f"{_format_assessments(assessments)}"
            )
        ),
    ]

    with logfire.span("generate_insights", assessment_count=len(assessments)):
        return await chain.ainvoke(messages)
