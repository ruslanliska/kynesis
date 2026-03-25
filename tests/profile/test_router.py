import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from app.profile.models import Profile
from tests.conftest import TEST_USER_ID


def _make_profile(user_id: str = TEST_USER_ID) -> Profile:
    now = datetime.now(timezone.utc)
    return Profile(
        id=uuid.uuid4(),
        user_id=uuid.UUID(user_id),
        display_name="Test User",
        full_name=None,
        avatar_url=None,
        phone=None,
        company=None,
        preferences={},
        created_at=now,
        updated_at=now,
    )


async def test_get_profile_returns_200(
    async_client: AsyncClient, valid_token: str
) -> None:
    profile = _make_profile()

    with patch(
        "app.profile.router.get_profile_by_user_id",
        return_value=profile,
    ):
        response = await async_client.get(
            "/api/v1/profile",
            headers={"Authorization": f"Bearer {valid_token}"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["user_id"] == TEST_USER_ID
    assert data["display_name"] == "Test User"
    assert "created_at" in data
    assert "updated_at" in data


async def test_get_profile_returns_404_when_not_found(
    async_client: AsyncClient, valid_token: str
) -> None:
    with patch(
        "app.profile.router.get_profile_by_user_id",
        return_value=None,
    ):
        response = await async_client.get(
            "/api/v1/profile",
            headers={"Authorization": f"Bearer {valid_token}"},
        )

    assert response.status_code == 404
    assert response.json()["detail"] == "Profile not found"


async def test_get_profile_returns_401_without_token(
    async_client: AsyncClient,
) -> None:
    response = await async_client.get("/api/v1/profile")
    assert response.status_code == 401


async def test_get_profile_returns_401_with_expired_token(
    async_client: AsyncClient, expired_token: str
) -> None:
    response = await async_client.get(
        "/api/v1/profile",
        headers={"Authorization": f"Bearer {expired_token}"},
    )
    assert response.status_code == 401


async def test_patch_profile_returns_200(
    async_client: AsyncClient, valid_token: str
) -> None:
    profile = _make_profile()
    profile.display_name = "Updated Name"

    with patch(
        "app.profile.router.update_display_name",
        return_value=profile,
    ):
        response = await async_client.patch(
            "/api/v1/profile",
            headers={"Authorization": f"Bearer {valid_token}"},
            json={"display_name": "Updated Name"},
        )

    assert response.status_code == 200
    assert response.json()["display_name"] == "Updated Name"


async def test_patch_profile_returns_422_with_empty_name(
    async_client: AsyncClient, valid_token: str
) -> None:
    response = await async_client.patch(
        "/api/v1/profile",
        headers={"Authorization": f"Bearer {valid_token}"},
        json={"display_name": ""},
    )
    assert response.status_code == 422


async def test_patch_profile_returns_422_with_long_name(
    async_client: AsyncClient, valid_token: str
) -> None:
    response = await async_client.patch(
        "/api/v1/profile",
        headers={"Authorization": f"Bearer {valid_token}"},
        json={"display_name": "x" * 101},
    )
    assert response.status_code == 422


async def test_patch_profile_returns_404_when_not_found(
    async_client: AsyncClient, valid_token: str
) -> None:
    with patch(
        "app.profile.router.update_display_name",
        return_value=None,
    ):
        response = await async_client.patch(
            "/api/v1/profile",
            headers={"Authorization": f"Bearer {valid_token}"},
            json={"display_name": "New Name"},
        )

    assert response.status_code == 404


async def test_patch_profile_returns_401_without_token(
    async_client: AsyncClient,
) -> None:
    response = await async_client.patch(
        "/api/v1/profile",
        json={"display_name": "Test"},
    )
    assert response.status_code == 401


async def test_patch_profile_strips_whitespace(
    async_client: AsyncClient, valid_token: str
) -> None:
    profile = _make_profile()
    profile.display_name = "Trimmed"

    with patch(
        "app.profile.router.update_display_name",
        return_value=profile,
    ) as mock_update:
        response = await async_client.patch(
            "/api/v1/profile",
            headers={"Authorization": f"Bearer {valid_token}"},
            json={"display_name": "  Trimmed  "},
        )

    assert response.status_code == 200
    mock_update.assert_awaited_once()
    # Verify the display_name was stripped before being passed to the service
    call_args = mock_update.call_args
    # positional args: (db, user_id, display_name)
    assert call_args[0][2] == "Trimmed"
