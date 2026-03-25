import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.profile.models import Profile


async def get_profile_by_user_id(
    db: AsyncSession, user_id: uuid.UUID
) -> Profile | None:
    result = await db.execute(
        select(Profile).where(Profile.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def update_display_name(
    db: AsyncSession, user_id: uuid.UUID, display_name: str
) -> Profile | None:
    profile = await get_profile_by_user_id(db, user_id)
    if profile is None:
        return None
    profile.display_name = display_name
    await db.commit()
    await db.refresh(profile)
    return profile
