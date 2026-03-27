from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser
from app.database import get_db
from app.models import DeviceToken, User, ViewedContent
from app.schemas.user import (
    DeviceTokenIn,
    ProgressIncrementRequest,
    ProgressOut,
    UserPublic,
    UserUpdate,
    ViewedContentIn,
)
from app.services import storage

router = APIRouter()


@router.get("/me", response_model=UserPublic)
def read_me(user: CurrentUser) -> User:
    return user


@router.patch("/me", response_model=UserPublic)
def update_me(
    body: UserUpdate,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> User:
    data = body.model_dump(exclude_unset=True)
    for key, value in data.items():
        setattr(user, key, value)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/me/avatar", response_model=UserPublic)
async def upload_avatar(
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
    file: UploadFile = File(...),
) -> User:
    url = await storage.save_avatar(user.id, file)
    user.profile_image_url = url
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.get("/me/progress", response_model=ProgressOut)
def get_progress(user: CurrentUser) -> ProgressOut:
    return ProgressOut(
        progress=user.progress,
        score=user.score,
        last_updated=user.progress_last_updated,
    )


@router.post("/me/progress/increment", response_model=ProgressOut)
def increment_progress(
    body: ProgressIncrementRequest,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> ProgressOut:
    user.progress = min(body.cap_at, user.progress + body.delta)
    user.score += body.delta
    user.progress_last_updated = datetime.now(timezone.utc)
    db.add(user)
    db.commit()
    db.refresh(user)
    return ProgressOut(
        progress=user.progress,
        score=user.score,
        last_updated=user.progress_last_updated,
    )


@router.post("/me/viewed-content", status_code=status.HTTP_204_NO_CONTENT)
def track_viewed(
    body: ViewedContentIn,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> None:
    existing = db.query(ViewedContent).filter_by(user_id=user.id, content_id=body.content_id).first()
    if existing:
        existing.content_type = body.content_type
        existing.is_completed = body.is_completed
        existing.viewed_at = datetime.now(timezone.utc)
        db.add(existing)
    else:
        db.add(
            ViewedContent(
                user_id=user.id,
                content_id=body.content_id,
                content_type=body.content_type,
                is_completed=body.is_completed,
            )
        )
    db.commit()


@router.post("/me/device-tokens", status_code=status.HTTP_204_NO_CONTENT)
def register_device_token(
    body: DeviceTokenIn,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> None:
    row = db.query(DeviceToken).filter_by(user_id=user.id, token=body.token).first()
    if row is None:
        db.add(DeviceToken(user_id=user.id, token=body.token))
        db.commit()
