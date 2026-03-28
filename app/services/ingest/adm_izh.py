"""Импорт событий из календаря adm.izh.ru (парсинг HTML страницы /i/calendar-calendar)."""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin

import httpx
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Event
from app.schemas.event import pack_event_gallery_for_storage
from app.services.ingest.textutils import strip_html
from app.utils.categories import review_bucket_for_type

_log = logging.getLogger(__name__)

# Блоки start / end / newid во встроенном JS (как на сайте).
_RE_EV_BLOCK = re.compile(
    r"start:\s*'([^']+)'\s*,\s*end:\s*'([^']+)'\s*,\s*newid:\s*'(\d+)'",
    re.MULTILINE,
)
# Пара «заголовок + блок картинок» в #data.
_RE_SPAN_IMG = re.compile(
    r'<span id="e_(\d+)">\s*([\s\S]*?)\s*</span>\s*<div id="i_\1"[^>]*>([\s\S]*?)</div>',
    re.IGNORECASE,
)
_RE_IMG_SRC = re.compile(r'src="([^"]+)"')
_RE_ADDR = re.compile(
    r"Адрес мероприятия</b>\s*&nbsp;\s*([^<]+?)\s*<br>",
    re.IGNORECASE,
)
_RE_DESC = re.compile(
    r"<b>до</b>&nbsp;[^<]+</div>\s*<div style=\"margin:10px[^\"]*\"></div>\s*"
    r'<div class="mb-3">([\s\S]*?)</div>\s*<div style="margin:10px[^\"]*"></div>\s*<div class="mb-3"><b>О событии</b>',
    re.IGNORECASE,
)


def _parse_event_datetime(raw: str) -> datetime | None:
    s = (raw or "").strip()
    if not s:
        return None
    for fmt in ("%d.%m.%Y %H:%M", "%d.%m.%Y"):
        try:
            dt = datetime.strptime(s, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _type_from_title(title: str) -> str:
    t = title.lower()
    if any(
        x in t
        for x in (
            "концерт",
            "спектакль",
            "театр",
            "кино",
            "фильм",
            "выставк",
            "музей",
            "фестиваль",
            "ярмарк",
            "галере",
        )
    ):
        return "Искусство"
    if any(
        x in t
        for x in (
            "спорт",
            "турнир",
            "соревнован",
            "чемпионат",
            "пробег",
            "лыж",
            "футбол",
            "хоккей",
            "самбо",
            "дзюдо",
            "волейбол",
            "баскетбол",
            "кросс",
            "фестиваль единоборств",
        )
    ):
        return "Парк"
    if any(x in t for x in ("лекци", "образован", "школ", "олимпиад", "робототех", "квест", "игра «")):
        return "IT"
    if any(x in t for x in ("памят", "истор", "музей", "архив", "побед")):
        return "История"
    return "Искусство"


def _img_paths_from_html_fragment(fragment: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for p in _RE_IMG_SRC.findall(fragment or ""):
        s = (p or "").strip()
        if not s or "nopic" in s.lower():
            continue
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


def _parse_titles_and_images(html: str) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for m in _RE_SPAN_IMG.finditer(html):
        eid, title_html, div_inner = m.group(1), m.group(2), m.group(3)
        title = re.sub(r"\s+", " ", strip_html(title_html, 2000) or "").strip() or f"Событие {eid}"
        paths = _img_paths_from_html_fragment(div_inner)
        out[eid] = {"title": title, "img_paths": paths}
    return out


def _parse_schedule_rows(html: str) -> list[tuple[str, str, str]]:
    rows = _RE_EV_BLOCK.findall(html)
    return [(s.strip(), e.strip(), nid) for s, e, nid in rows]


def _absolute_url(base: str, path: str | None) -> str | None:
    if not path:
        return None
    p = path.strip()
    if not p or "nopic" in p.lower():
        return None
    if p.startswith("http://") or p.startswith("https://"):
        return p
    return urljoin(base.rstrip("/") + "/", p)


def _format_place_line(address_raw: str | None) -> str:
    line = re.sub(r"\s+", " ", (address_raw or "").strip())
    if not line:
        return settings.default_event_place[:512]
    low = line.lower()
    if "удмурт" in low or "udmurt" in low:
        return line[:512]
    if "ижевск" in low:
        return f"{line}, Удмуртская Респ., Россия"[:512]
    return f"{line}, г. Ижевск, Удмуртская Респ., Россия"[:512]


def _parse_detail_page(html: str) -> tuple[str | None, str | None, list[str]]:
    addr_m = _RE_ADDR.search(html)
    place_extra = addr_m.group(1).strip() if addr_m else None
    desc_m = _RE_DESC.search(html)
    description = None
    if desc_m:
        description = strip_html(desc_m.group(1), 8000)
    detail_paths = _parse_detail_image_paths(html)
    return place_extra, description, detail_paths


def _parse_detail_image_paths(html: str) -> list[str]:
    m = re.search(r'<div\s+class="eventWrap"[^>]*>', html, re.IGNORECASE)
    if not m:
        return []
    start = m.end()
    chunk = html[start : start + 48000]
    low_chunk = chunk.lower()
    cut = low_chunk.find("<b>о событии</b>")
    if cut > 0:
        chunk = chunk[:cut]
    return _img_paths_from_html_fragment(chunk)


def _build_image_urls(base: str, calendar_paths: list[str], detail_paths: list[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    cap = max(1, settings.adm_izh_max_images_per_event)
    for p in list(calendar_paths) + list(detail_paths):
        u = _absolute_url(base, p)
        if u and u not in seen:
            seen.add(u)
            merged.append(u)
            if len(merged) >= cap:
                break
    return merged


def ingest_adm_izh(db: Session) -> dict[str, int]:
    stats = {"adm_izh_upserted": 0, "adm_izh_detail_fetched": 0}
    base = settings.adm_izh_base_url.rstrip("/")
    cal_url = urljoin(base + "/", settings.adm_izh_calendar_path.lstrip("/"))
    timeout = httpx.Timeout(settings.adm_izh_timeout)

    try:
        with httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers=_ua(),
            verify=settings.adm_izh_verify_ssl,
        ) as client:
            r = client.get(cal_url)
            if r.status_code != 200:
                _log.warning("adm.izh calendar HTTP %s", r.status_code)
                return stats
            html = r.text

            by_id = _parse_titles_and_images(html)
            schedule = _parse_schedule_rows(html)
            if not schedule and not by_id:
                _log.warning("adm.izh: no events parsed from calendar page")
                return stats

            merged: dict[str, dict[str, Any]] = {}
            for start_s, end_s, eid in schedule:
                meta = by_id.get(eid, {})
                title = meta.get("title") or f"Событие {eid}"
                img_paths = list(meta.get("img_paths") or [])
                end_dt = _parse_event_datetime(end_s)
                start_dt = _parse_event_datetime(start_s)
                merged[eid] = {
                    "title": title,
                    "img_paths": img_paths,
                    "start_s": start_s,
                    "end_s": end_s,
                    "end_dt": end_dt or start_dt,
                    "start_dt": start_dt,
                }

            for eid, meta in by_id.items():
                if eid not in merged:
                    merged[eid] = {
                        "title": meta["title"],
                        "img_paths": list(meta.get("img_paths") or []),
                        "start_s": "",
                        "end_s": "",
                        "end_dt": None,
                        "start_dt": None,
                    }

            rows = list(merged.items())
            rows.sort(
                key=lambda x: x[1]["end_dt"] or datetime.min.replace(tzinfo=timezone.utc),
                reverse=True,
            )
            rows = rows[: settings.adm_izh_max_events]

            detail_budget = settings.adm_izh_max_detail_fetches if settings.adm_izh_fetch_details else 0

            for eid, data in rows:
                title = data["title"][:512]
                ev_type = _type_from_title(title)
                rb = review_bucket_for_type(ev_type)
                date_caption = ""
                if data["start_s"] and data["end_s"]:
                    date_caption = f"{data['start_s']} — {data['end_s']}"
                elif data["start_s"]:
                    date_caption = data["start_s"]
                cal_paths: list[str] = list(data.get("img_paths") or [])
                detail_paths: list[str] = []

                place = _format_place_line(None)
                description: str | None = None
                detail_url = f"{base}/i/calendar-viewevent?obj={eid}"

                if detail_budget > 0:
                    try:
                        dr = client.get(detail_url)
                        if dr.status_code == 200:
                            p_extra, desc, detail_paths = _parse_detail_page(dr.text)
                            place = _format_place_line(p_extra)
                            if desc:
                                description = desc
                            stats["adm_izh_detail_fetched"] += 1
                            detail_budget -= 1
                            if settings.adm_izh_detail_delay_sec > 0:
                                time.sleep(settings.adm_izh_detail_delay_sec)
                    except (httpx.HTTPError, OSError) as ex:
                        _log.debug("adm.izh detail %s: %s", eid, ex)

                image_urls = _build_image_urls(base, cal_paths, detail_paths)
                img_url, image_urls_json = pack_event_gallery_for_storage(
                    image_urls[0] if image_urls else None,
                    image_urls,
                )

                ingest_key = f"adm_izh:{eid}"
                slug_base = f"adm-izh-{eid}"[:512]
                defaults = {
                    "name": title,
                    "slug": slug_base,
                    "description": description,
                    "img_url": img_url,
                    "image_urls_json": image_urls_json,
                    "date_caption": date_caption[:512] if date_caption else None,
                    "place": place[:512],
                    "url": detail_url,
                    "age": None,
                    "schedule": None,
                    "status": None,
                    "rating": None,
                    "type": ev_type,
                    "review_bucket": rb,
                    "last_ingested_at": datetime.now(timezone.utc),
                }

                existing = (
                    db.query(Event)
                    .filter(or_(Event.ingest_key == ingest_key, Event.slug == slug_base))
                    .first()
                )
                if existing:
                    for k, v in defaults.items():
                        setattr(existing, k, v)
                else:
                    db.add(Event(ingest_key=ingest_key, **defaults))
                stats["adm_izh_upserted"] += 1

            db.commit()
            return stats
    except (httpx.HTTPError, OSError) as ex:
        _log.warning("adm.izh ingest failed: %s", ex)
        return stats


def _ua() -> dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 (compatible; TechnostrelkaIngest/1.0; +https://github.com/) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.9",
    }
