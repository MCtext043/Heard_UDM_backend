"""Проверка URL картинок событий (отсекаем плейсхолдеры adm.izh.ru и прочий мусор)."""

from __future__ import annotations

import re
from urllib.parse import urlparse

# Пустая заглушка без файла: …/res_ru/0_event_<id>_<n> (часто не картинка и без расширения).
_RE_ADM_IZH_RES_RU_VOID = re.compile(
    r"/res_ru/0_event_\d+(?:_\d+)?/?(?:\?.*)?$",
    re.IGNORECASE,
)
# Только adm.izh.ru /res_ru/: нужен «файл» с расширением; прочие CDN могут без .jpg в пути.
_RE_IMAGE_FILE_EXT = re.compile(
    r"\.(jpe?g|png|gif|webp|bmp|svg)$",
    re.IGNORECASE,
)


def is_valid_event_image_url(url: str | None) -> bool:
    u = (url or "").strip()
    if not u or len(u) > 2048:
        return False
    low = u.lower()
    if low.startswith("javascript:") or low.startswith("data:"):
        return False
    try:
        parsed = urlparse(u)
    except Exception:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    if not parsed.netloc.strip():
        return False
    path = (parsed.path or "").rstrip("/")
    if not path:
        return False
    host = parsed.netloc.lower()
    # Reject obvious placeholder / test hosts (never show on cards).
    if host in {
        "example.com",
        "www.example.com",
        "placehold.co",
        "via.placeholder.com",
        "placeholder.com",
    }:
        return False
    if host.endswith(".example.com"):
        return False
    if "adm.izh.ru" in host and "/res_ru/" in path.lower():
        if _RE_ADM_IZH_RES_RU_VOID.search(path):
            return False
        if not _RE_IMAGE_FILE_EXT.search(path):
            return False
    return True


def filter_valid_event_image_urls(urls: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in urls:
        u = (raw or "").strip()
        if not u or u in seen:
            continue
        if not is_valid_event_image_url(u):
            continue
        seen.add(u)
        out.append(u)
    return out
