import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.database import get_db
from app.profile.schemas import ProfileResponse, ProfileUpdate
from app.profile.services import get_profile_by_user_id, update_display_name

router = APIRouter(prefix="/api/v1", tags=["profile"])


@router.get("/profile", response_model=ProfileResponse)
async def get_profile(
    current_user: dict[str, Any] = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProfileResponse:
    user_id = uuid.UUID(current_user["sub"])
    profile = await get_profile_by_user_id(db, user_id)
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Profile not found",
        )
    return ProfileResponse.model_validate(profile)


@router.patch("/profile", response_model=ProfileResponse)
async def patch_profile(
    body: ProfileUpdate,
    current_user: dict[str, Any] = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProfileResponse:
    user_id = uuid.UUID(current_user["sub"])
    profile = await update_display_name(db, user_id, body.display_name)
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Profile not found",
        )
    return ProfileResponse.model_validate(profile)
