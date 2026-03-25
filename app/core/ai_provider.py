from functools import lru_cache

from pinecone import Pinecone

from app.core.config import get_settings


@lru_cache
def get_pinecone_client() -> Pinecone:
    settings = get_settings()
    return Pinecone(api_key=settings.PINECONE_API_KEY)


def get_pinecone_index_name() -> str:
    return get_settings().PINECONE_INDEX_NAME


def get_ai_model() -> str:
    return get_settings().AI_MODEL
