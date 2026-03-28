import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import OperationalError

from app.config import settings
from app.database import Base, SessionLocal, engine
from app import models as _models  # noqa: F401 — зарегистрировать таблицы в metadata
from app.api.routers import api_router
from app.models import HomeCategory
from app.services import storage
from app.services.ingest.scheduler import shutdown_ingest_scheduler, start_ingest_scheduler

_log = logging.getLogger(__name__)


def _seed_home_categories_if_empty() -> None:
    db = SessionLocal()
    try:
        if db.query(HomeCategory).first() is not None:
            return
        seed = [
            HomeCategory(name="IT", type="IT", sort_order=0),
            HomeCategory(name="Искусство", type="Искусство", sort_order=1),
            HomeCategory(name="История", type="История", sort_order=2),
        ]
        db.add_all(seed)
        db.commit()
    finally:
        db.close()


def _ensure_db_schema() -> None:
    """
    Создаёт таблицы при старте. Повторяет попытки при кратковременной недоступности Postgres
    (иначе ingest и /events падают с «relation does not exist»).
    """
    import app.models  # noqa: F401 — на случай ленивых цепочек импортов

    last: OperationalError | None = None
    for attempt in range(1, 6):
        try:
            Base.metadata.create_all(bind=engine)
            return
        except OperationalError as e:
            last = e
            _log.warning(
                "DB schema create_all attempt %s/5 failed (%s), retrying…",
                attempt,
                e,
            )
            time.sleep(min(2 * attempt, 10))
    assert last is not None
    raise last


@asynccontextmanager
async def lifespan(_: FastAPI):
    _ensure_db_schema()
    storage.ensure_upload_root()
    _seed_home_categories_if_empty()
    start_ingest_scheduler()
    yield
    shutdown_ingest_scheduler()


app = FastAPI(title="Technostrelka API", version="1.0.0", lifespan=lifespan)

_cors_raw = settings.cors_origins.strip()
_cors_list = ["*"] if _cors_raw == "*" else [o.strip() for o in _cors_raw.split(",") if o.strip()]
if not _cors_list:
    _cors_list = ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_list,
    allow_credentials=_cors_list != ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api/v1")

storage.ensure_upload_root()
static_dir = Path(settings.upload_dir)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
