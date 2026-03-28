"""Фильтры качества для импорта: описание, фото, адрес, даты."""

from __future__ import annotations

from datetime import date

from app.services.ingest.dates_ru import event_covers_today_or_future


def place_looks_specific(place: str | None, *, min_len: int = 12) -> bool:
    """
    Отсекаем «голый» город. Нужны улица, ДК/ТРЦ/venue в кавычках, населённый пункт с запятой и т.п.
    """
    pl = (place or "").strip()
    if len(pl) < min_len:
        return False
    low = pl.lower()
    bare = {"ижевск", "г. ижевск", "удмуртия", "удмуртской респ.", "россия"}
    if low in bare or low.replace("г.", "").strip() in bare:
        return False
    markers = (
        "ул.",
        "ул ",
        "просп.",
        "пр-т",
        "дк ",
        "дк«",
        "«",
        "трц",
        "наб.",
        "пл.",
        "пер.",
        "шоссе",
        "р-н",
        " район",
        "д. ",
        "с. ",
        "п. ",
        "пгт",
        "тер.",
        "комплекс",
        "музей",
        "театр",
        "филармон",
        "зоопарк",
        "клуб",
        "бар ",
        "центр",
        "кц ",
    )
    if any(m in low for m in markers):
        return True
    if "," in pl and len(pl) >= 18:
        return True
    return len(pl) >= 28


def strict_event_ok(
    *,
    description_plain: str,
    image_urls: list[str],
    place: str | None,
    start: date | None,
    end: date | None,
    today: date,
    min_desc_len: int = 40,
    min_images: int = 1,
    days_past_grace: int = 0,
) -> bool:
    if len((description_plain or "").strip()) < min_desc_len:
        return False
    if len([u for u in image_urls if u and str(u).strip()]) < min_images:
        return False
    if not place_looks_specific(place):
        return False
    if not event_covers_today_or_future(start, end, today, days_past_grace=days_past_grace):
        return False
    return True
