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


async def generic_exception_handler(_request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content={"detail": "An unexpected error occurred."},
    )
