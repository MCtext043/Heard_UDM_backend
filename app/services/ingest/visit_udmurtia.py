"""Импорт событий с visitudmurtia.org (календарь → карточки)."""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Event
from app.schemas.event import pack_event_gallery_for_storage
from app.services.ingest.dates_ru import parse_russian_date_span
from app.services.ingest.quality import strict_event_ok
from app.services.ingest.textutils import strip_html
from app.utils.categories import review_bucket_for_type

_log = logging.getLogger(__name__)

_RE_ANNOUNCE_HREF = re.compile(
    r'<a[^>]+class="[^"]*\bannouncement\b[^"]*"[^>]+href="([^"]+)"',
    re.IGNORECASE,
)
_RE_ANNOUNCE_HREF_ALT = re.compile(
    r'<a[^>]+href="(/kalendar-sobytij/[^"]+)"[^>]+class="[^"]*\bannouncement\b',
    re.IGNORECASE,
)
_RE_TITLE = re.compile(r'<div class="cover__title">([^<]*)</div>', re.IGNORECASE)
_RE_DATE_LABEL = re.compile(r'<div class="cover__date-label">([^<]+)</div>', re.IGNORECASE)
_RE_PLACE_BLOCK = re.compile(
    r'contacts__key">\s*Место проведения\s*</div>\s*<div class="contacts__value">\s*([\s\S]*?)</div>',
    re.IGNORECASE,
)
_RE_IMG_DATA = re.compile(
    r'<img[^>]+(?:data-src|src)="(/upload/[^"]+)"[^>]*>',
    re.IGNORECASE,
)
_RE_IMG_COVER = re.compile(
    r'<img[^>]+class="[^"]*cover__img[^"]*"[^>]+(?:data-src|src)="([^"]+)"',
    re.IGNORECASE,
)


def _ua() -> dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 (compatible; TechnostrelkaIngest/1.0) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.9",
    }


def _type_from_title(title: str) -> str:
    t = title.lower()
    if any(
        x in t
        for x in (
            "фестивал",
            "концерт",
            "спектакль",
            "театр",
            "кино",
            "выставк",
            "музей",
            "ночь в",
            "акци",
        )
    ):
        return "Искусство"
    if any(x in t for x in ("спорт", "марафон", "турнир", "лыж", "футбол")):
        return "Парк"
    if any(x in t for x in ("этно", "народ", "традиц", "культур", "музей", "истор")):
        return "История"
    return "Искусство"


def _collect_paths(html: str) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for rx in (_RE_ANNOUNCE_HREF, _RE_ANNOUNCE_HREF_ALT):
        for m in rx.finditer(html):
            path = (m.group(1) or "").split("?", 1)[0].strip()
            if not path.startswith("/kalendar-sobytij/"):
                continue
            tail = path.rstrip("/").split("/")[-1].lower()
            if tail in ("", "kalendar-sobytij", "filter", "apply", "clear"):
                continue
            if "filter" in path.lower():
                continue
            if path not in seen:
                seen.add(path)
                out.append(path)
    return out


def _abs_url(base: str, path: str) -> str:
    if path.startswith("http://") or path.startswith("https://"):
        return path
    return urljoin(base.rstrip("/") + "/", path.lstrip("/"))


def _parse_detail(html: str, page_url: str) -> dict[str, Any]:
    base_root = f"{urlparse(page_url).scheme}://{urlparse(page_url).netloc}"
    tm = _RE_TITLE.search(html)
    title = (tm.group(1).strip() if tm else "")[:512]
    dm = _RE_DATE_LABEL.search(html)
    date_label = (dm.group(1).strip() if dm else "")[:512]
    pm = _RE_PLACE_BLOCK.search(html)
    place_html = pm.group(1) if pm else ""
    place = strip_html(place_html, 800)[:512] if place_html else ""

    desc_parts: list[str] = []
    for block in re.finditer(
        r'<div class="col-md-8">\s*((?:<p>[\s\S]*?</p>\s*)+)',
        html,
        re.IGNORECASE,
    ):
        inner = block.group(1)
        for p in re.finditer(r"<p>([\s\S]*?)</p>", inner, re.IGNORECASE):
            t = strip_html(p.group(1), 4000)
            if t:
                desc_parts.append(t)
    description = "\n\n".join(desc_parts)[:8000] if desc_parts else ""

    imgs: list[str] = []
    seen: set[str] = set()
    cap = max(1, settings.visit_udm_max_images_per_event)
    cm = _RE_IMG_COVER.search(html)
    if cm:
        u = _abs_url(base_root, cm.group(1).strip())
        if u not in seen:
            seen.add(u)
            imgs.append(u)
    for im in _RE_IMG_DATA.finditer(html):
        u = _abs_url(base_root, im.group(1).strip())
        if "nopic" in u.lower():
            continue
        if u not in seen:
            seen.add(u)
            imgs.append(u)
        if len(imgs) >= cap:
            break
    imgs = imgs[:cap]
    return {
        "title": title,
        "date_label": date_label,
        "place": place,
        "description": description,
        "image_urls": imgs,
    }


def ingest_visit_udmurtia(db: Session) -> dict[str, int]:
    stats = {
        "visit_udm_upserted": 0,
        "visit_udm_skipped": 0,
        "visit_udm_detail_fetched": 0,
    }
    if not settings.visit_udm_enabled:
        return stats
    base = settings.visit_udm_base_url.rstrip("/")
    cal_url = urljoin(base + "/", settings.visit_udm_calendar_path.lstrip("/"))
    timeout = httpx.Timeout(settings.ingest_http_timeout)
    verify = settings.visit_udm_verify_ssl
    today = datetime.now(settings.ingest_tz).date()

    try:
        with httpx.Client(timeout=timeout, follow_redirects=True, headers=_ua(), verify=verify) as client:
            r = client.get(cal_url)
            if r.status_code != 200:
                _log.warning("visitudm calendar HTTP %s", r.status_code)
                return stats
            paths = _collect_paths(r.text)[: max(1, settings.visit_udm_max_list_links)]
            budget = max(0, settings.visit_udm_max_detail_fetches)

            for path in paths:
                if budget <= 0:
                    break
                page_url = _abs_url(base, path)
                try:
                    dr = client.get(page_url)
                except (httpx.HTTPError, OSError) as ex:
                    _log.debug("visitudm detail %s: %s", path, ex)
                    stats["visit_udm_skipped"] += 1
                    continue
                if dr.status_code != 200:
                    stats["visit_udm_skipped"] += 1
                    continue
                stats["visit_udm_detail_fetched"] += 1
                budget -= 1
                if settings.visit_udm_detail_delay_sec > 0:
                    time.sleep(settings.visit_udm_detail_delay_sec)

                meta = _parse_detail(dr.text, page_url)
                title = (meta["title"] or "").strip()
                if not title:
                    tm_fallback = re.search(r"<title>([^<]+)</title>", dr.text, re.I)
                    if tm_fallback:
                        title = strip_html(tm_fallback.group(1).split(".")[0], 500)
                if not title:
                    stats["visit_udm_skipped"] += 1
                    continue

                start_d, end_d = parse_russian_date_span(meta["date_label"])
                desc_plain = (meta["description"] or "").strip()
                imgs_raw = list(meta["image_urls"] or [])
                img_url, gallery_json = pack_event_gallery_for_storage(
                    imgs_raw[0] if imgs_raw else None,
                    imgs_raw,
                )
                imgs = json.loads(gallery_json) if gallery_json else []
                place = meta["place"] or ""

                if settings.ingest_strict_event_quality and not strict_event_ok(
                    description_plain=desc_plain,
                    image_urls=imgs,
                    place=place,
                    start=start_d,
                    end=end_d,
                    today=today,
                    min_desc_len=settings.ingest_min_description_len,
                    min_images=settings.ingest_min_images_per_event,
                    days_past_grace=settings.ingest_event_days_past_grace,
                ):
                    stats["visit_udm_skipped"] += 1
                    continue

                ev_type = _type_from_title(title)
                rb = review_bucket_for_type(ev_type)
                slug_tail = path.rstrip("/").split("/")[-1][:200]
                slug_base = f"visit-udm-{slug_tail}"[:512]
                ingest_key = f"visit_udm:{slug_tail}"[:160]
                date_caption = meta["date_label"] or ""

                defaults = {
                    "name": title[:512],
                    "slug": slug_base,
                    "description": desc_plain[:8000] if desc_plain else None,
                    "img_url": img_url,
                    "image_urls_json": gallery_json,
                    "date_caption": date_caption[:512] if date_caption else None,
                    "place": place[:512] if place else None,
                    "url": page_url[:2048],
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
                stats["visit_udm_upserted"] += 1

            db.commit()
    except (httpx.HTTPError, OSError) as ex:
        _log.warning("visitudm ingest failed: %s", ex)
    return stats
