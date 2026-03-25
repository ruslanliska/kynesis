import os
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel
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


class OpenAIConfig(BaseModel):
    api_key: str = ""


class PineconeConfig(BaseModel):
    api_key: str = ""
    index_name: str = "kynesis-kb"
    cloud: str = "aws"
    region: str = "us-east-1"


class LogfireConfig(BaseModel):
    token: str = ""
    send_to_logfire: bool = False


class LangSmithConfig(BaseModel):
    api_key: str = ""
    project: str = "kynesis"
    tracing: bool = False
    endpoint: str = "https://api.smith.langchain.com"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_env_files(),
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
    )

    # Environment
    ENV: str = "dev"
    DEBUG: bool = False

    # API Key auth
    API_KEY: str = ""

    # Retained for future use
    SUPABASE_JWT_SECRET: str = ""
    DATABASE_URL: str = ""
    ALLOWED_ORIGINS: list[str] = ["http://localhost:5173"]

    # Service configs
    openai: OpenAIConfig = OpenAIConfig()
    pinecone: PineconeConfig = PineconeConfig()
    logfire: LogfireConfig = LogfireConfig()
    langsmith: LangSmithConfig = LangSmithConfig()


@lru_cache
def get_settings() -> Settings:
    return Settings()
