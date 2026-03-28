"""Полный цикл импорта для Ижевска."""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.config import settings
from app.services.ingest.adm_izh import ingest_adm_izh
from app.services.ingest.rss import ingest_rss_izhevsk

_log = logging.getLogger(__name__)


def run_izhevsk_ingest(db: Session, *, force: bool = False) -> dict[str, int]:
    if not force and not settings.ingest_enabled:
        return {"skipped": 1}
    out: dict[str, int] = {}
    try:
        out.update(ingest_rss_izhevsk(db))
    except Exception:
        _log.exception("RSS ingest failed")
        out["rss_error"] = 1
    try:
        out.update(ingest_adm_izh(db))
    except Exception:
        _log.exception("adm.izh.ru ingest failed")
        out["adm_izh_error"] = 1
    return out
