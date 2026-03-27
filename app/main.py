from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.routers import api_router
from app.config import settings
from app.database import Base, engine
from app import models as _models  # noqa: F401 — register ORM metadata
from app.database import SessionLocal
from app.models import HomeCategory
from app.services import storage


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


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    storage.ensure_upload_root()
    _seed_home_categories_if_empty()
    yield


app = FastAPI(title="Technostrelka API", version="1.0.0", lifespan=lifespan)

app.include_router(api_router, prefix="/api/v1")

storage.ensure_upload_root()
static_dir = Path(settings.upload_dir)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
