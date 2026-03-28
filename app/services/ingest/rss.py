"""Опциональные RSS-источники; по умолчанию фильтруем по ключевым словам Ижевска / Удмуртии."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from urllib.parse import urlparse

import feedparser
import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Event
from app.services.ingest.textutils import strip_html
from app.utils.categories import review_bucket_for_type

REGION_MARKERS = ("ижевск", "ижевска", "удмурт", "udmurt", "удмуртии", "udm")


def _iter_feed_urls() -> list[str]:
    raw = (settings.izhevsk_rss_feed_urls or "").strip()
    if not raw:
        return []
    return [u.strip() for u in raw.split(",") if u.strip()]


def _ingest_key_for_link(link: str, title: str) -> str:
    base = (link or title or "").encode("utf-8", errors="ignore")
    return f"rss:{hashlib.sha256(base).hexdigest()[:32]}"


def _mentions_region(text: str) -> bool:
    low = text.lower()
    return any(m in low for m in REGION_MARKERS)


def ingest_rss_izhevsk(db: Session) -> dict[str, int]:
    stats = {"rss_upserted": 0, "rss_skipped": 0}
    feeds = _iter_feed_urls()
    if not feeds:
        return stats

    timeout = httpx.Timeout(settings.ingest_http_timeout)

    for feed_url in feeds:
        try:
            with httpx.Client(timeout=timeout, follow_redirects=True) as client:
                r = client.get(feed_url, headers={"User-Agent": "TechnostrelkaIngest/1.0"})
            if r.status_code != 200:
                continue
            parsed = feedparser.parse(r.content)
        except (httpx.HTTPError, OSError):
            continue

        for entry in parsed.entries or []:
            link = getattr(entry, "link", None) or ""
            title = (getattr(entry, "title", None) or "").strip()
            summary = getattr(entry, "summary", None) or getattr(entry, "description", None) or ""
            if not title:
                stats["rss_skipped"] += 1
                continue
            blob = f"{title} {strip_html(summary, 2000)} {link}"
            if settings.rss_require_region_keyword and not _mentions_region(blob):
                stats["rss_skipped"] += 1
                continue
            ingest_key = _ingest_key_for_link(link, title)
            ev_type = "Искусство"
            rb = review_bucket_for_type(ev_type)
            date_caption = None
            if getattr(entry, "published", None):
                date_caption = str(entry.published)[:512]
            place = settings.default_event_place
            if link:
                netloc = urlparse(link).netloc
                if netloc:
                    place = f"{settings.default_event_place} (источник: {netloc})"[:512]

            defaults = {
                "name": title[:512],
                "slug": ingest_key.replace(":", "-")[:512],
                "description": strip_html(summary),
                "img_url": None,
                "date_caption": date_caption,
                "place": place[:512],
                "url": link or None,
                "age": None,
                "schedule": None,
                "status": None,
                "rating": None,
                "type": ev_type,
                "review_bucket": rb,
                "last_ingested_at": datetime.now(timezone.utc),
            }

            existing = db.query(Event).filter(Event.ingest_key == ingest_key).first()
            if existing:
                for k, v in defaults.items():
                    setattr(existing, k, v)
            else:
                db.add(Event(ingest_key=ingest_key, **defaults))
            stats["rss_upserted"] += 1

    db.commit()
    return stats
