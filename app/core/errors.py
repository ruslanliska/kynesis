from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse


class AIProviderError(HTTPException):
    def __init__(self, detail: str = "AI provider returned invalid output. Please retry.") -> None:
        super().__init__(status_code=502, detail=detail)


class AIRateLimitError(HTTPException):
    def __init__(self, detail: str = "AI usage limit exceeded. Try again later.") -> None:
        super().__init__(status_code=429, detail=detail)


class ValidationError(HTTPException):
    def __init__(self, detail: str) -> None:
        super().__init__(status_code=422, detail=detail)


class NotFoundError(HTTPException):
    def __init__(self, detail: str) -> None:
        super().__init__(status_code=404, detail=detail)


class PipelineTimeoutError(HTTPException):
    """Overall 180s ceiling breached — feature 003 FR-012."""

    def __init__(self, seconds: int) -> None:
        super().__init__(
            status_code=504,
            detail=f"Assessment pipeline timed out after {seconds}s.",
        )


class ReasoningUnavailableError(HTTPException):
    """Reasoning stage exhausted retries under strict policy — feature 003 FR-010."""

    def __init__(self) -> None:
        super().__init__(
            status_code=502,
            detail="Reasoning stage failed after retries.",
        )


class ReasoningPayloadTooLargeError(HTTPException):
    """Aggregated reasoning exceeds structuring-model input budget — feature 003 FR-014."""

    def __init__(self) -> None:
        super().__init__(
            status_code=413,
            detail=(
                "Reasoning payload too large for the structuring model. "
                "Reduce scorecard question count or content length and retry."
            ),
        )


class ReasoningCoverageError(Exception):
    """Reasoning stage returned rationale for fewer questions than the scorecard contains.

    Internal only — caught by the orchestrator as a retryable reasoning-stage failure;
    never reaches the HTTP response.
    """

    def __init__(self, missing_question_ids: set[str]) -> None:
        self.missing_question_ids = missing_question_ids
        super().__init__(
            f"Reasoning stage missing rationale for questions: {sorted(missing_question_ids)}"
        )


async def generic_exception_handler(_request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content={"detail": "An unexpected error occurred."},
    )
