from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.admin_deps import require_admin_key
from app.database import get_db
from app.services.ingest.runner import run_izhevsk_ingest

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/ingest/run")
def trigger_ingest(
    _: Annotated[None, Depends(require_admin_key)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """Ручной запуск импорта (RSS + календарь adm.izh.ru)."""
    return run_izhevsk_ingest(db, force=True)
