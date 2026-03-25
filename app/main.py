from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

import logfire
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.database import get_engine
from app.profile.router import router as profile_router
from app.assessment.router import router as assessment_router
from app.knowledge_base.router import router as knowledge_base_router
from app.insights.router import router as insights_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield
    await get_engine().dispose()


def create_app() -> FastAPI:
    application = FastAPI(title="Kynesis API", lifespan=lifespan)

    settings = get_settings()

    # Logfire observability
    if settings.logfire.token:
        logfire.configure(
            service_name="kynesis-api",
            token=settings.logfire.token,
            send_to_logfire=True,
        )
    else:
        logfire.configure(send_to_logfire=False)
    logfire.instrument_fastapi(application)

    # LangSmith — set env vars so the SDK picks them up
    if settings.langsmith.tracing and settings.langsmith.api_key:
        from langsmith import utils as ls_utils

        ls_utils.tracing_is_enabled()  # trigger import
        import os

        os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")
        os.environ.setdefault("LANGCHAIN_API_KEY", settings.langsmith.api_key)
        os.environ.setdefault("LANGCHAIN_PROJECT", settings.langsmith.project)
        os.environ.setdefault("LANGCHAIN_ENDPOINT", settings.langsmith.endpoint)

    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )

    application.include_router(profile_router)
    application.include_router(assessment_router)
    application.include_router(knowledge_base_router)
    application.include_router(insights_router)

    @application.get("/api/v1/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return application


app = create_app()
