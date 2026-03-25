import logfire
from fastapi import APIRouter, Depends
from httpx import ConnectError, HTTPStatusError
from pydantic_ai.exceptions import UnexpectedModelBehavior, UsageLimitExceeded

from app.assessment.schemas import AssessmentRequest, AssessmentResult
from app.assessment.services import run_assessment
from app.core.auth import verify_api_key
from app.core.errors import AIProviderError, AIRateLimitError

router = APIRouter(prefix="/api/v1", tags=["assessments"], dependencies=[Depends(verify_api_key)])


@router.post("/assessments", response_model=AssessmentResult)
async def create_assessment(request: AssessmentRequest) -> AssessmentResult:
    knowledge_base_context: str | None = None
    kb_warning: str | None = None

    # Retrieve RAG context using scorecard ID as namespace
    if request.use_knowledge_base:
        from app.knowledge_base.services import get_rag_context

        knowledge_base_context = await get_rag_context(
            request.scorecard.id,
            request.content[:1000],  # Use first 1000 chars as query
        )
        if knowledge_base_context is None:
            kb_warning = "Knowledge base context was unavailable."

    try:
        result = await run_assessment(request, knowledge_base_context)
        if kb_warning:
            result.knowledge_base_warning = kb_warning
        return result
    except UnexpectedModelBehavior as e:
        logfire.error("AI model returned invalid output", error=str(e))
        raise AIProviderError()
    except UsageLimitExceeded as e:
        logfire.warn("AI usage limit exceeded", error=str(e))
        raise AIRateLimitError()
    except (HTTPStatusError, ConnectError) as e:
        logfire.error("AI provider connection error", error=str(e))
        raise AIProviderError("AI provider unavailable.")
