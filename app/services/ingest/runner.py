"""Полный цикл импорта для Ижевска."""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.config import settings
from app.services.event_completeness import purge_incomplete_events
from app.services.ingest.adm_izh import ingest_adm_izh
from app.services.ingest.afisha_goroda import ingest_afisha_goroda
from app.services.ingest.rss import ingest_rss_izhevsk
from app.services.ingest.visit_udmurtia import ingest_visit_udmurtia
from app.services.ingest.yandex_afisha import ingest_yandex_afisha

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
        out.update(ingest_visit_udmurtia(db))
    except Exception:
        _log.exception("visitudmurtia ingest failed")
        out["visit_udm_error"] = 1
    try:
        out.update(ingest_afisha_goroda(db))
    except Exception:
        _log.exception("afisha goroda ingest failed")
        out["afisha_error"] = 1
    try:
        out.update(ingest_adm_izh(db))
    except Exception:
        _log.exception("adm.izh.ru ingest failed")
        out["adm_izh_error"] = 1
    try:
        out.update(ingest_yandex_afisha(db))
    except Exception:
        _log.exception("yandex afisha ingest failed")
        out["yandex_afisha_error"] = 1
    if settings.ingest_purge_incomplete_after_run:
        try:
            out["events_purged_incomplete"] = purge_incomplete_events(db)
        except Exception:
            _log.exception("purge incomplete events failed")
            out["purge_incomplete_error"] = 1
    return out
