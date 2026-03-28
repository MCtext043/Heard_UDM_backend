"""Проверка «заполненности» события и массовое удаление неполных записей."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.config import settings
from app.models import Event
from app.schemas.event import merge_event_image_urls
from app.utils.event_validation import description_min_length_ok, name_rejects_ticket_marketing


def is_event_complete(ev: Event) -> bool:
    """
    Для ленты достаточно: название, slug и ≥1 валидный URL картинки (обложка или галерея).
    Прочие поля опциональны. Дополнительно: event_completeness_require_description / require_extras.
    """
    if not (ev.name or "").strip():
        return False
    if settings.event_completeness_reject_ticket_marketing and name_rejects_ticket_marketing(
        ev.name
    ):
        return False
    if not (ev.slug or "").strip():
        return False
    urls = merge_event_image_urls(ev.image_urls_json, ev.img_url)
    if len(urls) < max(1, settings.event_completeness_min_gallery_urls):
        return False
    if settings.event_completeness_require_description and not description_min_length_ok(
        ev.description
    ):
        return False
    if settings.event_completeness_require_extras:
        if not (ev.age or "").strip():
            return False
        if not (ev.rating or "").strip():
            return False
        if not (ev.schedule or "").strip():
            return False
        if not (ev.status or "").strip():
            return False
    return True


def purge_incomplete_events(db: Session) -> int:
    """Удаляет события, не проходящие is_event_complete. Возвращает число удалённых строк."""
    if not settings.event_completeness_enabled:
        return 0
    deleted = 0
    for ev in db.query(Event).all():
        if not is_event_complete(ev):
            db.delete(ev)
            deleted += 1
    if deleted:
        db.commit()
    return deleted
