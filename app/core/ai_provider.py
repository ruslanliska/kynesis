from functools import lru_cache

from openai import AsyncOpenAI
from pinecone import Pinecone
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from app.core.config import get_settings


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
        from langsmith.wrappers import wrap_openai

        client = wrap_openai(client)

    return client


@lru_cache
def get_openai_provider() -> OpenAIProvider:
    return OpenAIProvider(openai_client=get_openai_client())


def get_ai_model(model: str = "gpt-4o") -> OpenAIChatModel:
    return OpenAIChatModel(model, provider=get_openai_provider())
