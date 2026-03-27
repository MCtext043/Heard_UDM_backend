from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class EventOut(BaseModel):
    id: UUID
    name: str
    slug: str | None
    img_url: str | None
    description: str | None
    age: str | None
    date_caption: str | None
    place: str | None
    url: str | None
    rating: str | None
    schedule: str | None
    status: str | None
    type: str | None
    review_bucket: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class HomeCategoryOut(BaseModel):
    id: UUID
    name: str
    type: str
    sort_order: int

    model_config = {"from_attributes": True}


class EventRatingSummary(BaseModel):
    average: float
    count: int


class EventCreate(BaseModel):
    name: str = Field(max_length=512)
    slug: str | None = Field(None, max_length=512)
    img_url: str | None = None
    description: str | None = None
    age: str | None = None
    date_caption: str | None = Field(None, max_length=512)
    place: str | None = None
    url: str | None = None
    rating: str | None = None
    schedule: str | None = None
    status: str | None = None
    type: str | None = None
    review_bucket: str | None = None


class HomeCategoryCreate(BaseModel):
    name: str = Field(max_length=120)
    type: str = Field(max_length=64)
    sort_order: int = 0


class Pagination(BaseModel):
    limit: int
    offset: int
    total: int
