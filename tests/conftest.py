import uuid
from collections.abc import AsyncGenerator
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from jose import jwt
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.database import get_db

TEST_JWT_SECRET = "test-jwt-secret-for-testing-only"
TEST_USER_ID = str(uuid.uuid4())
TEST_USER_EMAIL = "test@example.com"


TEST_API_KEY = "test-api-key-for-testing-only"


def _test_settings() -> Settings:
    return Settings(
        API_KEY=TEST_API_KEY,
        SUPABASE_JWT_SECRET=TEST_JWT_SECRET,
        DATABASE_URL="postgresql+asyncpg://test:test@localhost:5432/test",
        ALLOWED_ORIGINS=["http://localhost:5173"],
        AI_MODEL="openai:gpt-4o",
        OPENAI_API_KEY="test-openai-key",
        PINECONE_API_KEY="test-pinecone-key",
        PINECONE_INDEX_NAME="test-index",
        PINECONE_CLOUD="aws",
        PINECONE_REGION="us-east-1",
        LOGFIRE_TOKEN="",
        LOGFIRE_SEND_TO_LOGFIRE=False,
    )


# Override settings before any app import
get_settings.cache_clear()
import app.core.config
app.core.config.get_settings = _test_settings


def _make_token(
    sub: str = TEST_USER_ID,
    email: str = TEST_USER_EMAIL,
    aud: str = "authenticated",
    expired: bool = False,
) -> str:
    now = datetime.now(timezone.utc)
    exp = now - timedelta(hours=1) if expired else now + timedelta(hours=1)
    payload = {
        "sub": sub,
        "email": email,
        "aud": aud,
        "exp": exp,
        "iat": now,
        "role": "authenticated",
    }
    return jwt.encode(payload, TEST_JWT_SECRET, algorithm="HS256")


@pytest.fixture
def valid_token() -> str:
    return _make_token()


@pytest.fixture
def expired_token() -> str:
    return _make_token(expired=True)


@pytest.fixture
def wrong_audience_token() -> str:
    return _make_token(aud="anon")


@pytest.fixture
def mock_db_session() -> AsyncMock:
    session = AsyncMock(spec=AsyncSession)
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    return session


@pytest.fixture
def mock_pinecone_index() -> MagicMock:
    index = MagicMock()
    index.upsert = MagicMock()
    index.query = MagicMock(return_value={"matches": []})
    index.delete = MagicMock()
    return index


@pytest.fixture
def mock_pinecone_client(mock_pinecone_index: MagicMock) -> MagicMock:
    client = MagicMock()
    client.Index = MagicMock(return_value=mock_pinecone_index)
    return client


@pytest.fixture
async def async_client(
    mock_db_session: AsyncMock,
    mock_pinecone_client: MagicMock,
) -> AsyncGenerator[AsyncClient, None]:
    with (
        patch("app.core.ai_provider.get_pinecone_client", return_value=mock_pinecone_client),
        patch("app.main.logfire") as mock_logfire,
    ):
        mock_logfire.configure = MagicMock()
        mock_logfire.instrument_fastapi = MagicMock()

        from app.main import create_app

        app = create_app()
        app.dependency_overrides[get_settings] = _test_settings
        app.dependency_overrides[get_db] = lambda: mock_db_session

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client

        app.dependency_overrides.clear()
