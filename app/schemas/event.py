from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.utils.categories import review_bucket_for_type
from app.utils.image_urls import is_valid_event_image_url


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
        if is_valid_event_image_url(u):
            out.append(u)
            seen.add(u)
    for u in urls:
        if u in seen:
            continue
        if is_valid_event_image_url(u):
            out.append(u)
            seen.add(u)
    return out


def pack_event_gallery_for_storage(
    img_url: str | None,
    urls: list[str] | None,
) -> tuple[str | None, str | None]:
    """
    Единообразно чистит галерею перед записью в БД.
    Возвращает (img_url, image_urls_json) или (None, None), если не осталось ни одного валидного URL.
    """
    ulist = [str(u).strip() for u in (urls or []) if u and str(u).strip()]
    raw = json.dumps(ulist, ensure_ascii=False) if ulist else None
    merged = merge_event_image_urls(raw, img_url)
    if not merged:
        return None, None
    return merged[0], json.dumps(merged, ensure_ascii=False)


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
            gallery = merge_event_image_urls(data.image_urls_json, data.img_url)
            return {
                "id": data.id,
                "name": data.name,
                "slug": data.slug,
                # Always expose a real cover from the cleaned gallery (never raw placeholders).
                "img_url": gallery[0] if gallery else None,
                "image_urls": gallery,
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

    @model_validator(mode="after")
    def _validate_full_card(self) -> EventCreate:
        from app.utils.event_validation import slugify_event_name, validate_event_dict_for_storage

        slug = (self.slug or "").strip() or slugify_event_name(self.name)
        bucket = (self.review_bucket or "").strip() or (review_bucket_for_type(self.type) or "")
        gallery_json = None
        if self.image_urls:
            gallery_json = json.dumps(
                [u.strip() for u in self.image_urls if u and str(u).strip()],
                ensure_ascii=False,
            )
        validate_event_dict_for_storage(
            {
                "name": self.name.strip(),
                "slug": slug,
                "img_url": self.img_url,
                "description": self.description,
                "date_caption": self.date_caption,
                "place": self.place,
                "url": self.url,
                "type": self.type,
                "review_bucket": bucket,
                "image_urls_json": gallery_json,
            }
        )
        return self.model_copy(update={"slug": slug})


class HomeCategoryCreate(BaseModel):
    name: str = Field(max_length=120)
    type: str = Field(max_length=64)
    sort_order: int = 0


class Pagination(BaseModel):
    limit: int
    offset: int
    total: int
