import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

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


class DeepSeekConfig(BaseModel):
    api_key: str = ""
    base_url: str = "https://api.deepseek.com/v1"


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


class AssessmentConfig(BaseModel):
    """Two-stage reasoning pipeline configuration (feature 003-reasoning-aggregation)."""

    reasoning_model: str = "deepseek-reasoner"
    structuring_model: str = "deepseek-chat"
    structuring_temperature: float = 0.1
    reasoning_retries: int = 1
    structuring_retries: int = 3
    request_timeout_seconds: int = 180
    structuring_reserved_seconds: int = 15
    failure_policy: Literal["strict", "fallback"] = "fallback"


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
    deepseek: DeepSeekConfig = DeepSeekConfig()
    pinecone: PineconeConfig = PineconeConfig()
    logfire: LogfireConfig = LogfireConfig()
    langsmith: LangSmithConfig = LangSmithConfig()
    assessment: AssessmentConfig = AssessmentConfig()


@lru_cache
def get_settings() -> Settings:
    return Settings()
