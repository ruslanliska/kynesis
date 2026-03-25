import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ENV = os.getenv("ENV", "dev")


def _env_files() -> tuple[str, ...]:
    """Load .env first, then .env.{ENV} overrides on top."""
    base = Path(".env")
    overlay = Path(f".env.{ENV}")
    files: list[str] = []
    if base.exists():
        files.append(str(base))
    if overlay.exists():
        files.append(str(overlay))
    return tuple(files) or (".env",)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_env_files(),
        env_file_encoding="utf-8",
    )

    # Environment
    ENV: str = "dev"
    DEBUG: bool = False

    # API Key auth
    API_KEY: str = ""

    # Existing (retained for future use)
    SUPABASE_JWT_SECRET: str = ""
    DATABASE_URL: str = ""
    ALLOWED_ORIGINS: list[str] = ["http://localhost:5173"]

    # AI Provider
    OPENAI_API_KEY: str = ""

    # Pinecone
    PINECONE_API_KEY: str = ""
    PINECONE_INDEX_NAME: str = "kynesis-kb"
    PINECONE_CLOUD: str = "aws"
    PINECONE_REGION: str = "us-east-1"

    # Logfire
    LOGFIRE_TOKEN: str = ""
    LOGFIRE_SEND_TO_LOGFIRE: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
