import json
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


def merge_event_image_urls(raw_json: str | None, img_url: str | None) -> list[str]:
    urls: list[str] = []
    if raw_json:
        try:
            data = json.loads(raw_json)
            if isinstance(data, list):
                urls = [str(u).strip() for u in data if u and str(u).strip()]
        except json.JSONDecodeError:
            pass
    out: list[str] = []
    seen: set[str] = set()
    if img_url and img_url.strip():
        u = img_url.strip()
        out.append(u)
        seen.add(u)
    for u in urls:
        if u not in seen:
            out.append(u)
            seen.add(u)
    return out


class EventOut(BaseModel):
    id: UUID
    name: str
    slug: str | None
    img_url: str | None
    image_urls: list[str] = Field(default_factory=list)
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
    ingest_key: str | None = None
    last_ingested_at: datetime | None = None

    model_config = {"from_attributes": True}

    @model_validator(mode="before")
    @classmethod
    def _from_orm(cls, data: Any) -> Any:
        from app.models import Event as EventModel

        if isinstance(data, EventModel):
            return {
                "id": data.id,
                "name": data.name,
                "slug": data.slug,
                "img_url": data.img_url,
                "image_urls": merge_event_image_urls(data.image_urls_json, data.img_url),
                "description": data.description,
                "age": data.age,
                "date_caption": data.date_caption,
                "place": data.place,
                "url": data.url,
                "rating": data.rating,
                "schedule": data.schedule,
                "status": data.status,
                "type": data.type,
                "review_bucket": data.review_bucket,
                "created_at": data.created_at,
                "ingest_key": data.ingest_key,
                "last_ingested_at": data.last_ingested_at,
            }
        return data


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
    image_urls: list[str] | None = None
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
