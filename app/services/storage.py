import uuid
from pathlib import Path

from fastapi import UploadFile

from app.config import settings


def ensure_upload_root() -> Path:
    root = Path(settings.upload_dir)
    root.mkdir(parents=True, exist_ok=True)
    return root


def public_url(*path_parts: str) -> str:
    base = settings.public_base_url.rstrip("/")
    rel = "/".join(path_parts)
    return f"{base}/static/{rel}"


async def save_avatar(user_id: uuid.UUID, file: UploadFile) -> str:
    ext = Path(file.filename or "avatar").suffix.lower()
    if ext not in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
        ext = ".jpg"
    root = ensure_upload_root()
    sub = root / "images"
    sub.mkdir(parents=True, exist_ok=True)
    dest = sub / f"{user_id}{ext}"
    dest.write_bytes(await file.read())
    return public_url("images", dest.name)


async def save_review_photo(
    category: str,
    event_slug: str,
    user_id: uuid.UUID,
    index: int,
    file: UploadFile,
) -> str:
    ext = Path(file.filename or "photo").suffix.lower()
    if ext not in (".jpg", ".jpeg", ".png", ".webp"):
        ext = ".jpg"
    safe_cat = "".join(c if c.isalnum() or c in "-_" else "_" for c in category)[:64]
    safe_event = "".join(c if c.isalnum() or c in "-_" else "_" for c in event_slug)[:128]
    root = ensure_upload_root()
    sub = root / "review_photos" / safe_cat / safe_event / str(user_id)
    sub.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4().hex}_{index}{ext}"
    dest = sub / name
    dest.write_bytes(await file.read())
    rel_from_static = Path("review_photos") / safe_cat / safe_event / str(user_id) / name
    return public_url(*[str(p) for p in rel_from_static.parts])
