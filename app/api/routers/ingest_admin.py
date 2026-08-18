from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.admin_deps import require_admin_key
from app.database import get_db
from app.services.event_cleanup import purge_past_events, purge_test_data, repair_event_images
from app.services.event_completeness import purge_incomplete_events
from app.services.ingest.runner import run_izhevsk_ingest

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/ingest/run")
def trigger_ingest(
    _: Annotated[None, Depends(require_admin_key)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """Ручной запуск импорта + очистка неполных событий (если включено в настройках)."""
    return run_izhevsk_ingest(db, force=True)


@router.post("/events/purge-incomplete")
def purge_incomplete_events_endpoint(
    _: Annotated[None, Depends(require_admin_key)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """Удалить из БД события без полного набора полей."""
    return {"deleted": purge_incomplete_events(db)}


@router.post("/events/purge-past")
def purge_past_events_endpoint(
    _: Annotated[None, Depends(require_admin_key)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """Удалить события с распознанной датой в прошлом (например 2017)."""
    return {"deleted": purge_past_events(db)}


@router.post("/purge-test-data")
def purge_test_data_endpoint(
    _: Annotated[None, Depends(require_admin_key)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """Удалить smoke/test категории и события (SmokeCat, example.com и т.п.)."""
    return purge_test_data(db)


@router.post("/events/repair-images")
def repair_event_images_endpoint(
    _: Annotated[None, Depends(require_admin_key)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """Выровнять img_url по валидной галерее; удалить карточки без картинок."""
    return repair_event_images(db)
