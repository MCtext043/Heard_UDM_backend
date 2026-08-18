"""Актуальность событий по date_caption / schedule."""

from __future__ import annotations

from datetime import date

from app.config import settings
from app.models import Event
from app.services.ingest.dates_ru import (
    event_covers_today_or_future,
    parse_russian_date_span,
)


def event_date_span(ev: Event) -> tuple[date | None, date | None]:
    start, end = parse_russian_date_span(ev.date_caption)
    if start or end:
        return start, end
    return parse_russian_date_span(ev.schedule)


def is_event_current(ev: Event, *, today: date | None = None) -> bool:
    """
    True если событие ещё актуально.
    Если дату распарсить нельзя — считаем актуальным (не скрываем из‑за битой подписи),
    но прошлые годы (2017 и т.п.) с распознанной датой отсекаем.
    """
    today = today or date.today()
    start, end = event_date_span(ev)
    if start is None and end is None:
        return True
    return event_covers_today_or_future(
        start,
        end,
        today,
        days_past_grace=settings.ingest_event_days_past_grace,
    )


def is_event_clearly_past(ev: Event, *, today: date | None = None) -> bool:
    """True только если дату удалось распарсить и событие уже в прошлом."""
    today = today or date.today()
    start, end = event_date_span(ev)
    if start is None and end is None:
        return False
    return not event_covers_today_or_future(
        start,
        end,
        today,
        days_past_grace=settings.ingest_event_days_past_grace,
    )
