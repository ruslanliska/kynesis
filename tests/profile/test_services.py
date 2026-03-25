import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.ext.asyncio import AsyncSession

from app.profile.models import Profile
from app.profile.services import get_profile_by_user_id, update_display_name


def _make_profile(user_id: uuid.UUID | None = None) -> Profile:
    now = datetime.now(timezone.utc)
    profile = Profile(
        id=uuid.uuid4(),
        user_id=user_id or uuid.uuid4(),
        display_name="Test User",
        full_name=None,
        avatar_url=None,
        phone=None,
        company=None,
        preferences={},
        created_at=now,
        updated_at=now,
    )
    return profile


async def test_get_profile_by_user_id_returns_profile() -> None:
    user_id = uuid.uuid4()
    profile = _make_profile(user_id)

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = profile

    db = AsyncMock(spec=AsyncSession)
    db.execute.return_value = mock_result

    result = await get_profile_by_user_id(db, user_id)
    assert result is profile
    assert result.user_id == user_id


async def test_get_profile_by_user_id_returns_none_when_not_found() -> None:
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None

    db = AsyncMock(spec=AsyncSession)
    db.execute.return_value = mock_result

    result = await get_profile_by_user_id(db, uuid.uuid4())
    assert result is None


async def test_update_display_name_updates_and_returns_profile() -> None:
    user_id = uuid.uuid4()
    profile = _make_profile(user_id)

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = profile

    db = AsyncMock(spec=AsyncSession)
    db.execute.return_value = mock_result

    result = await update_display_name(db, user_id, "New Name")
    assert result is not None
    assert result.display_name == "New Name"
    db.commit.assert_awaited_once()
    db.refresh.assert_awaited_once_with(profile)


async def test_update_display_name_returns_none_when_not_found() -> None:
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None

    db = AsyncMock(spec=AsyncSession)
    db.execute.return_value = mock_result

    result = await update_display_name(db, uuid.uuid4(), "New Name")
    assert result is None
    db.commit.assert_not_awaited()
