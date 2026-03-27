from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser
from app.database import get_db
from app.models import Event
from app.services import storage

router = APIRouter(prefix="/uploads", tags=["uploads"])


@router.post("/review-photos", status_code=status.HTTP_201_CREATED)
async def upload_review_photos(
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
    event_id: UUID = Form(...),
    files: list[UploadFile] = File(...),
) -> dict:
    if not files:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No files")
    event = db.get(Event, event_id)
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")
    bucket = event.review_bucket or "Other"
    slug = event.slug or event.name.replace(" ", "_")[:128]
    urls: list[str] = []
    for i, f in enumerate(files):
        urls.append(await storage.save_review_photo(bucket, slug, user.id, i, f))
    return {"urls": urls}
