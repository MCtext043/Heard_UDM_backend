"""Импорт событий с afisha.yandex.ru (Ижевск и др.): разметка Open Graph на карточках."""

from __future__ import annotations

import html as html_lib
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
from app.utils.event_validation import (
    event_dict_meets_storage_rules,
    extract_yandex_performance_core,
    format_typed_event_name,
    name_rejects_ticket_marketing,
)

_YANDEX_TITLE_SUFFIXES = (
    " — Яндекс Афиша",
    " — Яндекс Афиша",
    " - Яндекс Афиша",
    " - Yandex Afisha",
)


def _strip_yandex_title_suffix(raw: str) -> str:
    t = (raw or "").strip()
    for suf in _YANDEX_TITLE_SUFFIXES:
        if t.endswith(suf):
            t = t[: -len(suf)].strip()
    return t

_log = logging.getLogger(__name__)

_RE_EVENT_PATH = re.compile(
    r"/(?P<city>[a-z0-9\-]+)/"
    r"(?P<rub>concert|theatre_show|theatre|exhibition|kids|standup|party|show|cinema|sport)/"
    r"(?P<slug>[a-z0-9\-]+)",
    re.IGNORECASE,
)
_RE_META_CONTENT = re.compile(
    r'<meta\s+property="(?P<prop>og:[^"]+)"\s+content="(?P<val>[^"]*)"\s*/?>',
    re.IGNORECASE,
)
_RE_EXTRA_IMG = re.compile(
    r"https://avatars\.mds\.yandex\.net/get-afishanew/\d+/[a-f0-9]+/\d+x\d+[^\"\s]*",
    re.IGNORECASE,
)
_RE_DATE_DM = re.compile(r"(\d{2}\.\d{2}\.\d{4})")
_RE_AGE = re.compile(r"\b(\d{1,2})\+\b")


def _ua() -> dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 Chrome/120 Safari/537.36 TechnostrelkaIngest/1.0"
        ),
        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.9",
    }


def _type_for_rubric(rub: str) -> str:
    r = rub.lower()
    if r in ("exhibition",):
        return "История"
    if r in ("kids", "sport"):
        return "Парк"
    if r in ("cinema",):
        return "Кино"
    return "Искусство"


def _parse_og(html: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for m in _RE_META_CONTENT.finditer(html):
        key = m.group("prop").strip().lower()
        val = html_lib.unescape(m.group("val").replace("&quot;", '"'))
        out[key] = val
    return out


def _collect_links_from_hub(html: str, allowed_city: str) -> list[tuple[str, str, str]]:
    """Список (city, rubric, slug) только для нужного города."""
    seen: set[tuple[str, str, str]] = set()
    out: list[tuple[str, str, str]] = []
    for m in _RE_EVENT_PATH.finditer(html):
        city, rub, slug = m.group("city").lower(), m.group("rub").lower(), m.group("slug").lower()
        if city != allowed_city.lower():
            continue
        if slug in ("places", "place", "artists", "venues"):
            continue
        key = (city, rub, slug)
        if key not in seen:
            seen.add(key)
            out.append((city, rub, slug))
    return out


def _parse_event_page(html: str, page_url: str, rub: str) -> dict[str, Any] | None:
    og = _parse_og(html)
    title = (og.get("og:title") or "").strip()
    desc = (og.get("og:description") or "").strip()
    image = (og.get("og:image") or "").strip()
    if not title or not desc or not image:
        return None

    core = extract_yandex_performance_core(og_title=title, og_description=desc)
    name = format_typed_event_name(core, rub)
    if name and settings.event_completeness_reject_ticket_marketing and name_rejects_ticket_marketing(
        name
    ):
        name = ""
    if not name:
        name = strip_html(_strip_yandex_title_suffix(title), 512)[:512]
    else:
        name = strip_html(name, 512)[:512]
    if not name:
        return None

    date_caption = ""
    dm = _RE_DATE_DM.search(title) or _RE_DATE_DM.search(desc)
    if dm:
        date_caption = dm.group(1)

    place = ""
    parts = [p.strip() for p in desc.split(",") if p.strip()]
    if len(parts) >= 2 and "купить" not in parts[1].lower():
        place = parts[1][:512]
    elif len(parts) >= 1:
        place = parts[0][:512]
    if "купить" in (place or "").lower():
        place = ""
    if place and "ижевск" not in place.lower() and len(place) < 400:
        place = f"{place}, Ижевск"

    age_m = _RE_AGE.search(desc) or _RE_AGE.search(title)
    age = f"{age_m.group(1)}+" if age_m else None

    imgs: list[str] = []
    if image.startswith("//"):
        image = "https:" + image
    imgs.append(image)
    for im in _RE_EXTRA_IMG.findall(html):
        if im not in imgs and len(imgs) < settings.yandex_afisha_max_images_per_event:
            imgs.append(im)

    ev_type = _type_for_rubric(rub)
    schedule = date_caption or None
    status = "Яндекс.Афиша"

    return {
        "name": name,
        "description": strip_html(desc, 8000),
        "date_caption": date_caption or None,
        "place": place[:512] if place else None,
        "img_url": imgs[0],
        "image_urls": imgs,
        "age": age,
        "schedule": schedule[:512] if schedule else None,
        "status": status[:64],
        "type": ev_type,
        "url": page_url[:2048],
    }


def ingest_yandex_afisha(db: Session) -> dict[str, int]:
    stats = {"yandex_afisha_upserted": 0, "yandex_afisha_skipped": 0, "yandex_afisha_detail_fetched": 0}
    if not settings.yandex_afisha_enabled:
        return stats
    base = settings.yandex_afisha_base_url.rstrip("/")
    city = settings.yandex_afisha_city_slug.strip().lower()
    timeout = httpx.Timeout(settings.ingest_http_timeout)
    verify = settings.yandex_afisha_verify_ssl

    hubs = [p.strip() for p in settings.yandex_afisha_hub_paths.split(",") if p.strip()]
    if not hubs:
        hubs = [f"/{city}/main"]

    links: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str, str]] = set()

    try:
        with httpx.Client(timeout=timeout, follow_redirects=True, headers=_ua(), verify=verify) as client:
            for path in hubs:
                url = path if path.startswith("http") else urljoin(base + "/", path.lstrip("/"))
                try:
                    r = client.get(url)
                except (httpx.HTTPError, OSError) as ex:
                    _log.debug("yandex afisha hub %s: %s", url, ex)
                    continue
                if r.status_code != 200:
                    continue
                for trip in _collect_links_from_hub(r.text, city):
                    if trip not in seen:
                        seen.add(trip)
                        links.append(trip)
                if settings.yandex_afisha_hub_delay_sec > 0:
                    time.sleep(settings.yandex_afisha_hub_delay_sec)

            links = links[: max(1, settings.yandex_afisha_max_events)]
            budget = max(0, settings.yandex_afisha_max_detail_fetches)

            for city_sl, rub, slug in links:
                if budget <= 0:
                    break
                page_url = f"{base}/{city_sl}/{rub}/{slug}"
                try:
                    dr = client.get(page_url)
                except (httpx.HTTPError, OSError) as ex:
                    _log.debug("yandex afisha detail %s: %s", page_url, ex)
                    stats["yandex_afisha_skipped"] += 1
                    continue
                if dr.status_code != 200:
                    stats["yandex_afisha_skipped"] += 1
                    continue
                stats["yandex_afisha_detail_fetched"] += 1
                budget -= 1
                if settings.yandex_afisha_detail_delay_sec > 0:
                    time.sleep(settings.yandex_afisha_detail_delay_sec)

                meta = _parse_event_page(dr.text, page_url, rub)
                if not meta:
                    stats["yandex_afisha_skipped"] += 1
                    continue

                title = meta["name"]
                rb = review_bucket_for_type(meta["type"])
                slug_base = f"yandex-afisha-{city_sl}-{rub}-{slug}"[:512]
                ingest_key = f"yandex_afisha:{city_sl}:{rub}:{slug}"[:160]
                imgs = list(meta.get("image_urls") or [])
                img_u, gallery_json = pack_event_gallery_for_storage(
                    meta.get("img_url") or (imgs[0] if imgs else None),
                    imgs,
                )

                defaults = {
                    "name": title,
                    "slug": slug_base,
                    "description": meta["description"][:8000] if meta["description"] else None,
                    "img_url": img_u,
                    "image_urls_json": gallery_json,
                    "date_caption": meta["date_caption"][:512] if meta["date_caption"] else None,
                    "place": meta["place"],
                    "url": meta["url"],
                    "age": meta.get("age"),
                    "schedule": meta.get("schedule"),
                    "status": meta.get("status"),
                    "rating": None,
                    "type": meta["type"],
                    "review_bucket": rb,
                    "last_ingested_at": datetime.now(timezone.utc),
                }
                if not event_dict_meets_storage_rules(defaults):
                    stats["yandex_afisha_skipped"] += 1
                    continue
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
                stats["yandex_afisha_upserted"] += 1

            db.commit()
    except (httpx.HTTPError, OSError) as ex:
        _log.warning("yandex afisha ingest failed: %s", ex)
    return stats
