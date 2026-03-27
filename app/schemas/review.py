from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class ReviewPhotoOut(BaseModel):
    id: UUID
    url: str
    sort_order: int

    model_config = {"from_attributes": True}


class ReviewOut(BaseModel):
    id: UUID
    event_id: UUID
    user_id: UUID
    rating: int
    text: str
    user_name: str
    review_date: str | None
    avatar_url: str | None
    created_at: datetime
    photos: list[ReviewPhotoOut] = []

    model_config = {"from_attributes": True}


class ReviewCreate(BaseModel):
    rating: int = Field(ge=1, le=5)
    text: str = ""
    photo_urls: list[str] = []


class FavoriteStatusResponse(BaseModel):
    favorites: dict[str, bool]
