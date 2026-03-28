"""Разбор дат в русских текстах афиш (день месяц год)."""

from __future__ import annotations

import re
from datetime import date
from typing import Iterable

_MONTHS: dict[str, int] = {
    "января": 1,
    "февраля": 2,
    "марта": 3,
    "апреля": 4,
    "мая": 5,
    "июня": 6,
    "июля": 7,
    "августа": 8,
    "сентября": 9,
    "октября": 10,
    "ноября": 11,
    "декабря": 12,
    "январь": 1,
    "февраль": 2,
    "март": 3,
    "апрель": 4,
    "июнь": 6,
    "июль": 7,
    "август": 8,
    "сентябрь": 9,
    "октябрь": 10,
    "ноябрь": 11,
    "декабрь": 12,
}

_RE_ONE = re.compile(
    r"(\d{1,2})\s+(" + "|".join(sorted(_MONTHS.keys(), key=len, reverse=True)) + r")\s+(\d{4})",
    re.IGNORECASE,
)


def _parse_one(m: re.Match[str]) -> date | None:
    d_s, mon_s, y_s = m.group(1), m.group(2).lower(), m.group(3)
    mon = _MONTHS.get(mon_s.lower())
    if not mon:
        return None
    try:
        return date(int(y_s), mon, int(d_s))
    except ValueError:
        return None


def parse_russian_date_span(raw: str | None) -> tuple[date | None, date | None]:
    """
    Возвращает (start, end) по строке вида «15 июля 2026» или «12 июня 2026 - 13 июня 2026».
    Если один день — end == start.
    """
    s = (raw or "").strip()
    if not s:
        return None, None
    parts = re.split(r"\s*[\-–—]\s*", s, maxsplit=1)
    dates: list[date] = []
    for part in parts:
        m = _RE_ONE.search(part)
        if m:
            d = _parse_one(m)
            if d:
                dates.append(d)
    if not dates:
        return None, None
    start = min(dates)
    end = max(dates)
    return start, end


def event_covers_today_or_future(
    start: date | None,
    end: date | None,
    today: date,
    *,
    days_past_grace: int = 0,
) -> bool:
    """Событие ещё актуально: конец >= today (или начало, если конца нет), с опциональной грацией в прошлое."""
    grace = days_past_grace
    t0 = today.toordinal() - grace
    if end is not None:
        return end.toordinal() >= t0
    if start is not None:
        return start.toordinal() >= t0
    return False


def parse_iso_dates(values: Iterable[str | None]) -> tuple[date | None, date | None]:
    """Минимальная/максимальная дата из ISO-подстрок."""
    from datetime import datetime

    found: list[date] = []
    for v in values:
        if not v or not isinstance(v, str):
            continue
        s = v.strip()
        if len(s) >= 10 and s[4] == "-" and s[7] == "-":
            try:
                found.append(datetime.fromisoformat(s.replace("Z", "+00:00")).date())
            except ValueError:
                continue
    if not found:
        return None, None
    return min(found), max(found)
