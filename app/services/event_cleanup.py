"""Очистка тестовых/битых данных и устаревших событий."""

from __future__ import annotations

import re

from sqlalchemy.orm import Session

from app.models import Event, HomeCategory
from app.schemas.event import merge_event_image_urls, pack_event_gallery_for_storage
from app.services.event_freshness import is_event_clearly_past

_RE_SMOKE_NAME = re.compile(
    r"(?i)\b(smoke|smokecat|live\s*smoke|admin\s*smoke|test\s*cat|pytest)\b",
)
_RE_HASHISH = re.compile(r"(?i)\b[0-9a-f]{8,}\b")
_RE_TEST_URL = re.compile(r"(?i)(?:^|://)(?:www\.)?example\.com(?:/|$)")


def _is_test_event(ev: Event) -> bool:
    name = (ev.name or "").strip()
    url = (ev.url or "").strip()
    img = (ev.img_url or "").strip()
    if _RE_SMOKE_NAME.search(name):
        return True
    if _RE_TEST_URL.search(url) or _RE_TEST_URL.search(img):
        return True
    # Titles like "Admin smoke ab12cd..." / "Live smoke deadbeef"
    if re.search(r"(?i)\bsmoke\b", name) and _RE_HASHISH.search(name):
        return True
    return False


def _is_test_category(cat: HomeCategory) -> bool:
    blob = f"{cat.name or ''} {cat.type or ''}"
    if _RE_SMOKE_NAME.search(blob):
        return True
    # Keep seeded IT / Искусство / История; drop random hash-looking smoke cats.
    if re.search(r"(?i)^smokecat\b", (cat.name or "").strip()):
        return True
    return False


def purge_test_data(db: Session) -> dict[str, int]:
    events_deleted = 0
    for ev in db.query(Event).all():
        if _is_test_event(ev):
            db.delete(ev)
            events_deleted += 1

    cats_deleted = 0
    for cat in db.query(HomeCategory).all():
        if _is_test_category(cat):
            db.delete(cat)
            cats_deleted += 1

    if events_deleted or cats_deleted:
        db.commit()
    return {"events_deleted": events_deleted, "categories_deleted": cats_deleted}


def purge_past_events(db: Session) -> int:
    deleted = 0
    for ev in db.query(Event).all():
        if is_event_clearly_past(ev):
            db.delete(ev)
            deleted += 1
    if deleted:
        db.commit()
    return deleted


def repair_event_images(db: Session) -> dict[str, int]:
    """Перепаковывает галерею и выравнивает img_url; удаляет события без валидных картинок."""
    repaired = 0
    deleted = 0
    for ev in db.query(Event).all():
        gallery = merge_event_image_urls(ev.image_urls_json, ev.img_url)
        if not gallery:
            db.delete(ev)
            deleted += 1
            continue
        img_u, gallery_json = pack_event_gallery_for_storage(gallery[0], gallery)
        if not img_u:
            db.delete(ev)
            deleted += 1
            continue
        if ev.img_url != img_u or ev.image_urls_json != gallery_json:
            ev.img_url = img_u
            ev.image_urls_json = gallery_json
            repaired += 1
    if repaired or deleted:
        db.commit()
    return {"repaired": repaired, "deleted_no_image": deleted}
