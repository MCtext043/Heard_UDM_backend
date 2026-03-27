from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser
from app.database import get_db
from app.models import Event, Favorite
from app.schemas.event import EventOut
from app.schemas.review import FavoriteStatusResponse

router = APIRouter(prefix="/me/favorites", tags=["favorites"])


@router.get("", response_model=list[EventOut])
def list_favorites(
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> list[Event]:
    rows = (
        db.query(Favorite)
        .filter(Favorite.user_id == user.id)
        .join(Event, Favorite.event_id == Event.id)
        .all()
    )
    return [f.event for f in rows if f.event is not None]


@router.put("/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
def add_favorite(
    event_id: UUID,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> None:
    event = db.get(Event, event_id)
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")
    exists = db.query(Favorite).filter_by(user_id=user.id, event_id=event_id).first()
    if exists is None:
        db.add(Favorite(user_id=user.id, event_id=event_id))
        db.commit()


@router.delete("/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_favorite(
    event_id: UUID,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> None:
    row = db.query(Favorite).filter_by(user_id=user.id, event_id=event_id).first()
    if row:
        db.delete(row)
        db.commit()


@router.get("/status", response_model=FavoriteStatusResponse)
def favorites_status(
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
    event_ids: Annotated[list[UUID], Query()],
) -> FavoriteStatusResponse:
    if not event_ids:
        return FavoriteStatusResponse(favorites={})
    ids_set = set(event_ids)
    favorited_ids = {
        row[0]
        for row in db.execute(
            select(Favorite.event_id).where(
                Favorite.user_id == user.id,
                Favorite.event_id.in_(ids_set),
            )
        ).all()
    }
    return FavoriteStatusResponse(
        favorites={str(eid): (eid in favorited_ids) for eid in event_ids}
    )
