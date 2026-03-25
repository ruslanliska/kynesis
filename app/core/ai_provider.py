from functools import lru_cache

from pinecone import Pinecone
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from app.core.config import get_settings


@lru_cache
def get_pinecone_client() -> Pinecone:
    settings = get_settings()
    return Pinecone(api_key=settings.PINECONE_API_KEY)


def get_pinecone_index_name() -> str:
    return get_settings().PINECONE_INDEX_NAME


@lru_cache
def get_openai_provider() -> OpenAIProvider:
    return OpenAIProvider(api_key=get_settings().OPENAI_API_KEY)


def get_ai_model(model: str = "gpt-4o") -> OpenAIChatModel:
    return OpenAIChatModel(model, provider=get_openai_provider())
