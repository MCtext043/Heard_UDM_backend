from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class UserPublic(BaseModel):
    id: UUID
    email: EmailStr
    username: str
    profile_image_url: str | None
    category_user: str | None
    post_text: str
    post_name_text: str
    post_images: str
    created_at: datetime

    model_config = {"from_attributes": True}


class UserUpdate(BaseModel):
    username: str | None = Field(None, max_length=120)
    category_user: str | None = Field(None, max_length=64)
    post_text: str | None = None
    post_name_text: str | None = None
    post_images: str | None = None


class ProgressOut(BaseModel):
    progress: int
    score: int
    last_updated: datetime | None


class ProgressIncrementRequest(BaseModel):
    delta: int = Field(default=1, ge=1, le=50)
    cap_at: int = Field(default=100, ge=1, le=100)


class ViewedContentIn(BaseModel):
    content_id: str = Field(max_length=256)
    content_type: str | None = Field(None, max_length=64)
    is_completed: bool = False


class DeviceTokenIn(BaseModel):
    token: str = Field(max_length=512)
