import logging
import os
from functools import lru_cache

from openai import AsyncOpenAI
from pinecone import Pinecone
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from app.core.config import get_settings

logger = logging.getLogger(__name__)


@lru_cache
def get_pinecone_client() -> Pinecone:
    settings = get_settings()
    return Pinecone(api_key=settings.pinecone.api_key)


def get_pinecone_index_name() -> str:
    return get_settings().pinecone.index_name


@lru_cache
def get_openai_client() -> AsyncOpenAI:
    """Create OpenAI client, wrapped with LangSmith tracing if enabled."""
    settings = get_settings()
    client = AsyncOpenAI(api_key=settings.openai.api_key)

    if settings.langsmith.tracing and settings.langsmith.api_key:
        # Clear lru_cache on get_env_var so langsmith sees our env vars
        from langsmith.utils import get_env_var

        get_env_var.cache_clear()

        from langsmith.wrappers import wrap_openai

        client = wrap_openai(client)

        from langsmith.utils import tracing_is_enabled

        logger.info(
            "OpenAI client wrapped with LangSmith tracing "
            "(tracing_is_enabled=%s, LANGCHAIN_TRACING_V2=%s)",
            tracing_is_enabled(),
            os.environ.get("LANGCHAIN_TRACING_V2"),
        )
    else:
        logger.info("OpenAI client created without LangSmith wrapping")

    return client


@lru_cache
def get_openai_provider() -> OpenAIProvider:
    return OpenAIProvider(openai_client=get_openai_client())


def get_ai_model(model: str = "gpt-4o") -> OpenAIChatModel:
    return OpenAIChatModel(model, provider=get_openai_provider())


@lru_cache
def get_deepseek_client() -> AsyncOpenAI:
    settings = get_settings()
    return AsyncOpenAI(
        api_key=settings.deepseek.api_key,
        base_url=settings.deepseek.base_url,
    )


@lru_cache
def get_deepseek_provider() -> OpenAIProvider:
    return OpenAIProvider(openai_client=get_deepseek_client())


def get_deepseek_model(model: str = "deepseek-reasoner") -> OpenAIChatModel:
    return OpenAIChatModel(model, provider=get_deepseek_provider())
