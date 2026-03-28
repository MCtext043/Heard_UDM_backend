"""Правила названий и полноты данных события перед сохранением в БД."""

from __future__ import annotations

import json
import re
from typing import Any

from app.config import settings

# Рекламные / шаблонные заголовки Яндекс.Афиши и билетных витрин
_RE_BUY_TICKETS = re.compile(
    r"(?:^|\s)(?:купить|заказать)\s+билет",
    re.IGNORECASE,
)
_RE_TICKETS_ON = re.compile(r"^билеты?\s+на\s+", re.IGNORECASE)
_RE_PRICE_SNIPPET = re.compile(r"\bот\s+[\d\s]+(?:₽|руб)", re.IGNORECASE)
_RE_TICKETS_WORD = re.compile(r"\bбилет(?:ы|ов|ами)?\s+(?:на|в)\s+", re.IGNORECASE)

_RUBRIC_TITLE_PREFIX: dict[str, str] = {
    "concert": "Концерт",
    "theatre_show": "Спектакль",
    "theatre": "Театральное событие",
    "exhibition": "Выставка",
    "standup": "Стендап",
    "kids": "Детское мероприятие",
    "party": "Вечеринка",
    "show": "Шоу",
    "cinema": "Кинопоказ",
    "sport": "Спортивное событие",
}


def extract_yandex_performance_core(*, og_title: str, og_description: str) -> str:
    """
    Имя постановки/артиста без «Билеты на…», дат и площадки.
    Сначала первая часть description до запятой (если не про покупку), иначе — из title.
    """
    desc = (og_description or "").strip()
    title = (og_title or "").strip()
    for suf in (
        " — Яндекс Афиша",
        " — Яндекс Афиша",
        " - Яндекс Афиша",
        " - Yandex Afisha",
    ):
        if title.endswith(suf):
            title = title[: -len(suf)].strip()

    parts = [p.strip() for p in desc.split(",") if p.strip()]
    core = ""
    if parts and "купить" not in parts[0].lower() and "билет" not in parts[0].lower():
        core = parts[0]

    m = re.search(r"Билеты\s+на\s+[«\"]([^»\"]+)[»\"]", title, re.IGNORECASE)
    if m and len(m.group(1).strip()) > 1:
        core = m.group(1).strip()

    if not core:
        m2 = re.search(r"[«\"]([^»\"]{2,200})[»\"]", title)
        if m2:
            core = m2.group(1).strip()

    if not core:
        core = re.sub(r"^\s*Билеты\s+на\s+", "", title, flags=re.IGNORECASE)
        core = re.sub(r"^[«\"]\s*|\s*[»\"]$", "", core).strip()

    core = re.sub(r"\s+\d{2}\.\d{2}\.\d{4}.*$", "", core).strip()
    core = re.sub(r"\s+дк\s+.*$", "", core, flags=re.IGNORECASE).strip()
    core = re.sub(r"\s+—\s*.*$", "", core).strip()
    return core[:400]


def format_typed_event_name(core: str, rubric: str) -> str:
    """Человекочитаемое имя: «Спектакль — «Название»», а не текст про покупку билетов."""
    label = _RUBRIC_TITLE_PREFIX.get((rubric or "").lower(), "Событие")
    c = (core or "").strip()
    if not c:
        return ""
    return f"{label} — «{c}»"[:512]


def name_rejects_ticket_marketing(name: str) -> bool:
    """True, если название похоже на рекламу билетов и не должно попадать в БД."""
    s = (name or "").strip()
    if not s:
        return True
    low = s.lower()
    if _RE_BUY_TICKETS.search(low):
        return True
    if _RE_TICKETS_ON.search(low):
        return True
    if _RE_TICKETS_WORD.search(low):
        return True
    if _RE_PRICE_SNIPPET.search(low):
        return True
    if "яндекс афиш" in low and "билет" in low:
        return True
    return False


def description_min_length_ok(description: str | None) -> bool:
    n = max(0, settings.event_completeness_min_description_len)
    return len((description or "").strip()) >= n


def slugify_event_name(name: str) -> str:
    s = re.sub(r"[^\w\s\-—а-яА-ЯёЁ]", "", (name or "").lower(), flags=re.U)
    s = re.sub(r"[\s—]+", "-", s.strip())
    s = s.strip("-")[:200]
    return s or "event"


def event_dict_meets_storage_rules(data: dict[str, Any]) -> bool:
    """Проверка полей без ORM-объекта (для Pydantic / черновиков)."""
    try:
        validate_event_dict_for_storage(data)
    except ValueError:
        return False
    return True


def _gallery_urls_from_data(data: dict[str, Any]) -> list[str]:
    from app.schemas.event import merge_event_image_urls

    img = (data.get("img_url") or "").strip()
    raw_json = data.get("image_urls_json")
    if isinstance(data.get("image_urls"), list):
        raw_json = json.dumps(
            [str(u).strip() for u in data["image_urls"] if u and str(u).strip()],
            ensure_ascii=False,
        )
    return merge_event_image_urls(raw_json if isinstance(raw_json, str) else None, img)


def validate_event_dict_for_storage(data: dict[str, Any]) -> None:
    """
    Минимум для хранения в БД: название, slug и хотя бы одна валидная картинка.
    Описание, дата, место, ссылка, тип — опционально (дольше наполняются импортом/админкой).
    """
    if not (data.get("name") or "").strip():
        raise ValueError("Укажите название события")
    if settings.event_completeness_reject_ticket_marketing and name_rejects_ticket_marketing(
        str(data.get("name"))
    ):
        raise ValueError(
            "Название не должно быть текстом про покупку билетов; укажите название мероприятия "
            "(например: «Концерт — «Группа»» или «Спектакль — «Название»»)."
        )
    if not (data.get("slug") or "").strip():
        raise ValueError("Укажите slug (короткий идентификатор в URL)")
    urls = _gallery_urls_from_data(data)
    if len(urls) < max(1, settings.event_completeness_min_gallery_urls):
        raise ValueError("Нужна минимум одна картинка в галерее (img_url или image_urls)")
    if settings.event_completeness_require_description and not description_min_length_ok(
        str(data.get("description") or "")
    ):
        n = settings.event_completeness_min_description_len
        raise ValueError(f"Описание должно быть не короче {n} символов")
    if settings.event_completeness_require_extras:
        for k, label in (
            ("age", "age"),
            ("rating", "rating"),
            ("schedule", "schedule"),
            ("status", "status"),
        ):
            if not (data.get(k) or "").strip():
                raise ValueError(f"Заполните поле {label}")
