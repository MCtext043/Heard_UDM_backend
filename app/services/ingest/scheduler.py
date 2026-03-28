"""Периодический запуск импорта (фоновый процесс, sync SQLAlchemy session)."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.background import BackgroundScheduler

from app.config import settings
from app.database import SessionLocal
from app.services.ingest.runner import run_izhevsk_ingest

_log = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def _job() -> None:
    db = SessionLocal()
    try:
        stats = run_izhevsk_ingest(db, force=False)
        _log.info("izhevsk ingest finished: %s", stats)
    finally:
        db.close()


def start_ingest_scheduler() -> None:
    global _scheduler
    if not settings.ingest_enabled:
        _log.info("ingest disabled (INGEST_ENABLED=false)")
        return
    if _scheduler is not None:
        return
    _scheduler = BackgroundScheduler()
    minutes = max(15, int(settings.ingest_interval_minutes))
    _scheduler.add_job(
        _job,
        "interval",
        minutes=minutes,
        id="izhevsk_ingest",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )
    # Первый прогон вскоре после старта API
    _scheduler.add_job(
        _job,
        "date",
        run_date=datetime.now(timezone.utc) + timedelta(seconds=20),
        id="izhevsk_ingest_warmup",
        replace_existing=True,
    )
    _scheduler.start()
    _log.info("ingest scheduler started (every %s min)", minutes)


def shutdown_ingest_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
