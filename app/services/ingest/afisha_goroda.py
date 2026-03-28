"""Импорт событий с izh.afishagoroda.ru (Next.js __NEXT_DATA__)."""

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
from app.services.ingest.dates_ru import parse_iso_dates
from app.services.ingest.quality import strict_event_ok
from app.services.ingest.textutils import strip_html
from app.utils.categories import review_bucket_for_type

_log = logging.getLogger(__name__)

_RE_NEXT_DATA = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">([\s\S]*?)</script>',
    re.IGNORECASE,
)
_RE_EVENT_LINKS = re.compile(r'href="(/events/[a-z0-9][a-z0-9\-]*)"', re.IGNORECASE)


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
    if any(x in t for x in ("спектакль", "театр", "балет", "опер", "музыкал", "комеди")):
        return "Искусство"
    if any(x in t for x in ("концерт", "фестивал", "dj", "клуб")):
        return "Искусство"
    if any(x in t for x in ("выставк", "галере", "музей")):
        return "История"
    if any(x in t for x in ("спорт", "матч", "игра ")):
        return "Парк"
    return "Искусство"


def _extract_next(html: str) -> dict[str, Any] | None:
    m = _RE_NEXT_DATA.search(html)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


def _collect_iso_datetimes(obj: Any, out: list[str], depth: int = 0) -> None:
    if depth > 14:
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            lk = str(k).lower()
            if lk in (
                "starttime",
                "start_time",
                "datetime",
                "date",
                "begindate",
                "enddate",
                "showdate",
            ) and isinstance(v, str) and len(v) >= 10:
                out.append(v)
            _collect_iso_datetimes(v, out, depth + 1)
    elif isinstance(obj, list):
        for it in obj[:400]:
            _collect_iso_datetimes(it, out, depth + 1)


def _pick_event_dict(pp: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(pp, dict):
        return None
    for key in ("event", "eventData", "item", "model", "data"):
        v = pp.get(key)
        if isinstance(v, dict) and (v.get("title") or v.get("name")):
            return v
    if pp.get("title") or pp.get("name"):
        return pp
    return None


def _event_images(e: dict[str, Any], base: str, cap: int) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()

    def add(u: str | None) -> None:
        if not u or not isinstance(u, str):
            return
        u = u.strip()
        if u.startswith("//"):
            u = "https:" + u
        if u.startswith("/"):
            u = urljoin(base, u)
        if u not in seen and u.startswith("http"):
            seen.add(u)
            urls.append(u)

    img = e.get("image")
    if isinstance(img, str):
        add(img)
    elif isinstance(img, dict):
        add(img.get("url") or img.get("src"))
    for ph in e.get("photos") or e.get("images") or []:
        if isinstance(ph, str):
            add(ph)
        elif isinstance(ph, dict):
            add(ph.get("url") or ph.get("src"))
    poster = e.get("poster")
    if isinstance(poster, dict):
        add(poster.get("url") or poster.get("src"))
    return urls[:cap]


def _event_place_line(e: dict[str, Any]) -> str:
    pl = e.get("place") or e.get("venue") or e.get("location")
    parts: list[str] = []
    if isinstance(pl, dict):
        t = (pl.get("title") or pl.get("name") or "").strip()
        ad = (pl.get("address") or "").strip()
        if t:
            parts.append(t)
        if ad:
            parts.append(ad)
    elif isinstance(pl, str) and pl.strip():
        parts.append(pl.strip())
    addr = e.get("address")
    if isinstance(addr, str) and addr.strip():
        parts.append(addr.strip())
    return ", ".join(parts)[:512]


def _event_description(e: dict[str, Any]) -> str:
    for key in ("description", "text", "body", "content", "annotation", "shortDescription"):
        v = e.get(key)
        if isinstance(v, str) and v.strip():
            return strip_html(v, 8000)
    return ""


def _event_title(e: dict[str, Any]) -> str:
    return (e.get("title") or e.get("name") or "").strip()[:512]


def _slugs_from_listing(html: str) -> list[str]:
    data = _extract_next(html)
    slugs: list[str] = []
    seen: set[str] = set()
    if data:
        pp = data.get("props", {}).get("pageProps", {})
        for key in ("events", "initialEvents", "items", "eventsList"):
            arr = pp.get(key)
            if isinstance(arr, list):
                for it in arr:
                    if isinstance(it, dict):
                        s = it.get("slug") or it.get("code")
                        if isinstance(s, str) and s and s not in seen:
                            seen.add(s)
                            slugs.append(s)
        if not slugs:
            for key in ("dehydratedState",):
                _collect_slugs_from_queries(pp.get(key), slugs, seen)

    if not slugs:
        for m in _RE_EVENT_LINKS.finditer(html):
            path = m.group(1)
            tail = path.rstrip("/").split("/")[-1].lower()
            if tail in ("events", ""):
                continue
            if tail not in seen:
                seen.add(tail)
                slugs.append(tail)
    return slugs


def _collect_slugs_from_queries(node: Any, slugs: list[str], seen: set[str], depth: int = 0) -> None:
    if depth > 12 or node is None:
        return
    if isinstance(node, dict):
        if "slug" in node and isinstance(node["slug"], str):
            s = node["slug"]
            if s and s not in seen:
                seen.add(s)
                slugs.append(s)
        for v in node.values():
            _collect_slugs_from_queries(v, slugs, seen, depth + 1)
    elif isinstance(node, list):
        for it in node[:200]:
            _collect_slugs_from_queries(it, slugs, seen, depth + 1)


def ingest_afisha_goroda(db: Session) -> dict[str, int]:
    stats = {
        "afisha_upserted": 0,
        "afisha_skipped": 0,
        "afisha_detail_fetched": 0,
    }
    if not settings.afisha_goroda_enabled:
        return stats
    base = settings.afisha_goroda_base_url.rstrip("/")
    list_url = urljoin(base + "/", settings.afisha_goroda_events_path.lstrip("/"))
    timeout = httpx.Timeout(settings.ingest_http_timeout)
    verify = settings.afisha_goroda_verify_ssl
    today = datetime.now(settings.ingest_tz).date()
    cap_img = max(1, settings.afisha_goroda_max_images_per_event)

    try:
        with httpx.Client(timeout=timeout, follow_redirects=True, headers=_ua(), verify=verify) as client:
            lr = client.get(list_url)
            if lr.status_code != 200:
                _log.warning("afisha listing HTTP %s", lr.status_code)
                return stats
            slugs = _slugs_from_listing(lr.text)[: max(1, settings.afisha_goroda_max_slugs)]
            budget = max(0, settings.afisha_goroda_max_detail_fetches)

            for slug in slugs:
                if budget <= 0:
                    break
                page_url = f"{base}/events/{slug}"
                try:
                    dr = client.get(page_url)
                except (httpx.HTTPError, OSError) as ex:
                    _log.debug("afisha detail %s: %s", slug, ex)
                    stats["afisha_skipped"] += 1
                    continue
                if dr.status_code != 200:
                    stats["afisha_skipped"] += 1
                    continue
                stats["afisha_detail_fetched"] += 1
                budget -= 1
                if settings.afisha_goroda_detail_delay_sec > 0:
                    time.sleep(settings.afisha_goroda_detail_delay_sec)

                data = _extract_next(dr.text)
                if not data:
                    stats["afisha_skipped"] += 1
                    continue
                pp = data.get("props", {}).get("pageProps", {})
                e = _pick_event_dict(pp)
                if not e:
                    stats["afisha_skipped"] += 1
                    continue

                title = _event_title(e)
                if not title:
                    stats["afisha_skipped"] += 1
                    continue

                desc_plain = _event_description(e)
                place = _event_place_line(e)
                imgs_raw = _event_images(e, base, cap_img)
                img_url, gallery_json = pack_event_gallery_for_storage(
                    imgs_raw[0] if imgs_raw else None,
                    imgs_raw,
                )
                imgs = json.loads(gallery_json) if gallery_json else []

                iso_vals: list[str] = []
                _collect_iso_datetimes(e, iso_vals)
                start_d, end_d = parse_iso_dates(iso_vals)

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
                    stats["afisha_skipped"] += 1
                    continue

                ev_type = _type_from_title(title)
                rb = review_bucket_for_type(ev_type)
                slug_base = f"afisha-{slug}"[:512]
                ingest_key = f"afisha_goroda:{slug}"[:160]

                date_parts = [x for x in iso_vals if x]
                date_caption = ""
                if date_parts:
                    date_caption = min(date_parts)[:200]

                defaults = {
                    "name": title,
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
                stats["afisha_upserted"] += 1

            db.commit()
    except (httpx.HTTPError, OSError) as ex:
        _log.warning("afisha ingest failed: %s", ex)
    return stats
