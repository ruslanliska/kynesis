import logfire
from fastapi import APIRouter, Depends
from httpx import ConnectError, HTTPStatusError
from pydantic_ai.exceptions import UnexpectedModelBehavior, UsageLimitExceeded

from app.core.auth import verify_api_key
from app.core.errors import AIProviderError, AIRateLimitError
from app.insights.schemas import InsightReport, InsightRequest
from app.insights.services import generate_insights

router = APIRouter(prefix="/api/v1", tags=["insights"], dependencies=[Depends(verify_api_key)])


@router.post("/insights", response_model=InsightReport)
async def create_insights(request: InsightRequest) -> InsightReport:
    try:
        return await generate_insights(request.assessments)
    except UnexpectedModelBehavior as e:
        logfire.error("AI model returned invalid output", error=str(e))
        raise AIProviderError()
    except UsageLimitExceeded as e:
        logfire.warn("AI usage limit exceeded", error=str(e))
        raise AIRateLimitError()
    except (HTTPStatusError, ConnectError) as e:
        logfire.error("AI provider connection error", error=str(e))
        raise AIProviderError("AI provider unavailable.")
