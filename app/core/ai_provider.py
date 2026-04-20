import logging
from functools import lru_cache

from langchain_deepseek import ChatDeepSeek
from langchain_openai import ChatOpenAI
from openai import AsyncOpenAI
from pinecone import Pinecone

from app.core.config import get_settings

logger = logging.getLogger(__name__)

OPENAI_DEFAULT_MODEL = "gpt-4o"
DEEPSEEK_DEFAULT_MODEL = "deepseek-chat"

# ---------------------------------------------------------------------------
# Infra clients
# ---------------------------------------------------------------------------


@lru_cache
def get_pinecone_client() -> Pinecone:
    return Pinecone(api_key=get_settings().pinecone.api_key)


def get_pinecone_index_name() -> str:
    return get_settings().pinecone.index_name


@lru_cache
def get_openai_client() -> AsyncOpenAI:
    """Raw AsyncOpenAI — used by Whisper transcription and Vision OCR."""
    settings = get_settings()
    client = AsyncOpenAI(api_key=settings.openai.api_key)

    if settings.langsmith.tracing and settings.langsmith.api_key:
        from langsmith.utils import get_env_var
        get_env_var.cache_clear()
        from langsmith.wrappers import wrap_openai
        client = wrap_openai(client)

    return client


# ---------------------------------------------------------------------------
# LangChain chat models
# ---------------------------------------------------------------------------


@lru_cache
def get_openai() -> ChatOpenAI:
    return ChatOpenAI(model=OPENAI_DEFAULT_MODEL, api_key=get_settings().openai.api_key)


@lru_cache
def get_deepseek() -> ChatDeepSeek:
    return ChatDeepSeek(model=DEEPSEEK_DEFAULT_MODEL, api_key=get_settings().deepseek.api_key)


# ---------------------------------------------------------------------------
# LLM factory — change DEFAULT_LLM_PROVIDER to switch all services at once.
# ---------------------------------------------------------------------------

DEFAULT_LLM_PROVIDER = "deepseek"  # "openai" | "deepseek"


def get_llm(provider: str | None = None) -> ChatDeepSeek | ChatOpenAI:
    """Return the configured LLM. Pass provider to override the default."""
    p = provider or DEFAULT_LLM_PROVIDER
    return get_deepseek() if p == "deepseek" else get_openai()


# ---------------------------------------------------------------------------
# Two-stage reasoning pipeline factories (feature 003-reasoning-aggregation)
# ---------------------------------------------------------------------------


@lru_cache
def get_reasoning_llm() -> ChatDeepSeek | ChatOpenAI:
    """Reasoning-stage LLM. Uses settings.assessment.reasoning_model.

    Defaults to DeepSeek R1 (`deepseek-reasoner`) which exposes the full thinking
    trace via response.additional_kwargs['reasoning_content'] — required for
    LangSmith visibility per FR-008 and US2 Acceptance Scenario 3.
    """
    settings = get_settings()
    model = settings.assessment.reasoning_model
    if model.startswith("gpt-") or model.startswith("o1") or model.startswith("o3") or model.startswith("o4"):
        return ChatOpenAI(model=model, api_key=settings.openai.api_key)
    return ChatDeepSeek(model=model, api_key=settings.deepseek.api_key)


@lru_cache
def get_structuring_llm() -> ChatDeepSeek | ChatOpenAI:
    """Structuring-stage LLM — formatter only, low temperature per FR-013.

    Temperature is pinned to settings.assessment.structuring_temperature (≤ 0.2)
    so output is a near-deterministic transcription of the reasoner's conclusions.
    """
    settings = get_settings()
    model = settings.assessment.structuring_model
    temperature = settings.assessment.structuring_temperature
    if model.startswith("gpt-"):
        return ChatOpenAI(model=model, api_key=settings.openai.api_key, temperature=temperature)
    return ChatDeepSeek(model=model, api_key=settings.deepseek.api_key, temperature=temperature)
