import pytest
from httpx import AsyncClient


async def test_health_no_auth_required(async_client: AsyncClient) -> None:
    response = await async_client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_valid_token_accepted(async_client: AsyncClient, valid_token: str) -> None:
    response = await async_client.get(
        "/api/v1/health",
        headers={"Authorization": f"Bearer {valid_token}"},
    )
    assert response.status_code == 200


async def test_expired_token_rejected(async_client: AsyncClient, expired_token: str) -> None:
    # We need a protected endpoint to test auth rejection.
    # Health is unprotected, so we test against profile once it exists.
    # For now, test the auth dependency directly.
    from app.core.auth import get_current_user
    from app.core.config import Settings
    from fastapi.security import HTTPAuthorizationCredentials

    settings = Settings(
        SUPABASE_JWT_SECRET="test-jwt-secret-for-testing-only",
        DATABASE_URL="postgresql+asyncpg://test:test@localhost:5432/test",
        ALLOWED_ORIGINS=["http://localhost:5173"],
    )
    credentials = HTTPAuthorizationCredentials(
        scheme="Bearer", credentials=expired_token
    )

    with pytest.raises(Exception) as exc_info:
        await get_current_user(credentials=credentials, settings=settings)
    assert exc_info.value.status_code == 401


async def test_malformed_token_rejected(async_client: AsyncClient) -> None:
    from app.core.auth import get_current_user
    from app.core.config import Settings
    from fastapi.security import HTTPAuthorizationCredentials

    settings = Settings(
        SUPABASE_JWT_SECRET="test-jwt-secret-for-testing-only",
        DATABASE_URL="postgresql+asyncpg://test:test@localhost:5432/test",
        ALLOWED_ORIGINS=["http://localhost:5173"],
    )
    credentials = HTTPAuthorizationCredentials(
        scheme="Bearer", credentials="not.a.valid.jwt"
    )

    with pytest.raises(Exception) as exc_info:
        await get_current_user(credentials=credentials, settings=settings)
    assert exc_info.value.status_code == 401


async def test_wrong_audience_rejected(
    async_client: AsyncClient, wrong_audience_token: str
) -> None:
    from app.core.auth import get_current_user
    from app.core.config import Settings
    from fastapi.security import HTTPAuthorizationCredentials

    settings = Settings(
        SUPABASE_JWT_SECRET="test-jwt-secret-for-testing-only",
        DATABASE_URL="postgresql+asyncpg://test:test@localhost:5432/test",
        ALLOWED_ORIGINS=["http://localhost:5173"],
    )
    credentials = HTTPAuthorizationCredentials(
        scheme="Bearer", credentials=wrong_audience_token
    )

    with pytest.raises(Exception) as exc_info:
        await get_current_user(credentials=credentials, settings=settings)
    assert exc_info.value.status_code == 401


async def test_tampered_token_rejected(async_client: AsyncClient) -> None:
    from app.core.auth import get_current_user
    from app.core.config import Settings
    from fastapi.security import HTTPAuthorizationCredentials
    from jose import jwt

    # Sign with a different secret
    payload = {"sub": "some-id", "email": "test@test.com", "aud": "authenticated"}
    tampered = jwt.encode(payload, "wrong-secret", algorithm="HS256")

    settings = Settings(
        SUPABASE_JWT_SECRET="test-jwt-secret-for-testing-only",
        DATABASE_URL="postgresql+asyncpg://test:test@localhost:5432/test",
        ALLOWED_ORIGINS=["http://localhost:5173"],
    )
    credentials = HTTPAuthorizationCredentials(
        scheme="Bearer", credentials=tampered
    )

    with pytest.raises(Exception) as exc_info:
        await get_current_user(credentials=credentials, settings=settings)
    assert exc_info.value.status_code == 401


async def test_valid_token_returns_user_data(valid_token: str) -> None:
    from app.core.auth import get_current_user
    from app.core.config import Settings
    from fastapi.security import HTTPAuthorizationCredentials
    from tests.conftest import TEST_USER_EMAIL, TEST_USER_ID

    settings = Settings(
        SUPABASE_JWT_SECRET="test-jwt-secret-for-testing-only",
        DATABASE_URL="postgresql+asyncpg://test:test@localhost:5432/test",
        ALLOWED_ORIGINS=["http://localhost:5173"],
    )
    credentials = HTTPAuthorizationCredentials(
        scheme="Bearer", credentials=valid_token
    )

    user = await get_current_user(credentials=credentials, settings=settings)
    assert user["sub"] == TEST_USER_ID
    assert user["email"] == TEST_USER_EMAIL
