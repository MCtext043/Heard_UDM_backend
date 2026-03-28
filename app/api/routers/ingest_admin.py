from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.admin_deps import require_admin_key
from app.database import get_db
from app.services.event_completeness import purge_incomplete_events
from app.services.ingest.runner import run_izhevsk_ingest

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/ingest/run")
def trigger_ingest(
    _: Annotated[None, Depends(require_admin_key)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """Ручной запуск импорта: RSS, Visit Udmurtia, Афиша Города, adm.izh.ru, Яндекс.Афиша; затем очистка неполных событий (если включено в настройках)."""
    return run_izhevsk_ingest(db, force=True)


@router.post("/events/purge-incomplete")
def purge_incomplete_events_endpoint(
    _: Annotated[None, Depends(require_admin_key)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """Удалить из БД события без полного набора полей (см. event_completeness, EVENT_COMPLETENESS_ENABLED)."""
    return {"deleted": purge_incomplete_events(db)}
