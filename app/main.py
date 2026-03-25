import logging
import os
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

# ── LangSmith env vars MUST be set before any langsmith import ──────────
# langsmith.utils.get_env_var is @lru_cache — if tracing_is_enabled()
# is called before these are set, the "false" result is cached forever.
from app.core.config import get_settings as _get_settings

_ls = _get_settings().langsmith
if _ls.tracing and _ls.api_key:
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_API_KEY"] = _ls.api_key
    os.environ["LANGCHAIN_PROJECT"] = _ls.project
    os.environ["LANGCHAIN_ENDPOINT"] = _ls.endpoint
del _ls
# ── End early LangSmith setup ──────────────────────────────────────────

import logfire
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.database import get_engine
from app.profile.router import router as profile_router
from app.assessment.router import router as assessment_router
from app.knowledge_base.router import router as knowledge_base_router
from app.insights.router import router as insights_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Verify LangSmith is actually reachable at startup
    settings = get_settings()
    if settings.langsmith.tracing and settings.langsmith.api_key:
        try:
            from langsmith import Client

            ls_client = Client()
            # Lightweight check — no data transfer
            if ls_client.info is not None:
                logger.info("LangSmith connection verified")
            else:
                logger.warning("LangSmith returned no server info")
        except Exception:
            logger.exception("LangSmith connection check failed")

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

    # Log LangSmith status (env vars already set at module level above)
    if settings.langsmith.tracing and settings.langsmith.api_key:
        logger.info(
            "LangSmith tracing enabled — project=%s endpoint=%s",
            settings.langsmith.project,
            settings.langsmith.endpoint,
        )
    else:
        logger.warning(
            "LangSmith tracing disabled (tracing=%s, api_key set=%s)",
            settings.langsmith.tracing,
            bool(settings.langsmith.api_key),
        )

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
