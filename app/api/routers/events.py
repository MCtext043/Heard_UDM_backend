from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from app.api.admin_deps import require_admin_key
from app.api.deps import CurrentUser
from app.database import get_db
from app.models import Event, Review, ReviewPhoto
from app.schemas.event import EventCreate, EventOut, EventRatingSummary, pack_event_gallery_for_storage
from app.services.event_freshness import is_event_current
from app.utils.categories import review_bucket_for_type
from app.schemas.review import ReviewCreate, ReviewOut

router = APIRouter()


def _list_current_events(
    db: Session,
    *,
    type: str | None,
    limit: int,
    offset: int,
    extra_where=None,
) -> list[Event]:
    """Пагинация по актуальным событиям (без прошедших дат вроде 2017)."""
    stmt = select(Event).order_by(Event.created_at.desc())
    if type:
        stmt = stmt.where(Event.type == type)
    if extra_where is not None:
        stmt = stmt.where(extra_where)
    # Берём запас, чтобы после фильтра по дате хватило на offset+limit.
    pool_limit = min(2000, max(200, (offset + limit) * 8 + 50))
    pool = list(db.scalars(stmt.limit(pool_limit)).all())
    current = [ev for ev in pool if is_event_current(ev)]
    return current[offset : offset + limit]


@router.get("", response_model=list[EventOut])
def list_events(
    db: Annotated[Session, Depends(get_db)],
    type: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> list[Event]:
    return _list_current_events(db, type=type, limit=limit, offset=offset)


@router.post(
    "",
    response_model=EventOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin_key)],
)
def create_event(
    body: EventCreate,
    db: Annotated[Session, Depends(get_db)],
) -> Event:
    name_low = body.name.strip().lower()
    if "smoke" in name_low or "smokecat" in name_low:
        raise HTTPException(status_code=400, detail="Test/smoke events are not allowed")
    url_low = (body.url or "").lower()
    if "example.com" in url_low:
        raise HTTPException(status_code=400, detail="example.com URLs are not allowed")

    bucket = body.review_bucket or review_bucket_for_type(body.type)
    img_stored, gallery_json = pack_event_gallery_for_storage(
        body.img_url,
        body.image_urls,
    )
    if not img_stored:
        raise HTTPException(status_code=400, detail="Valid event image is required")
    slug = (body.slug or "").strip()
    ev = Event(
        name=body.name.strip(),
        slug=slug or None,
        img_url=img_stored,
        image_urls_json=gallery_json,
        description=body.description,
        age=body.age,
        date_caption=body.date_caption,
        place=body.place,
        url=body.url,
        rating=body.rating,
        schedule=body.schedule,
        status=body.status,
        type=body.type,
        review_bucket=bucket,
    )
    db.add(ev)
    db.commit()
    db.refresh(ev)
    return ev


@router.get("/search", response_model=list[EventOut])
def search_events(
    db: Annotated[Session, Depends(get_db)],
    q: Annotated[str, Query(min_length=1)],
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> list[Event]:
    term = f"%{q.strip()}%"
    extra = or_(
        Event.name.ilike(term),
        Event.description.ilike(term),
        Event.place.ilike(term),
    )
    return _list_current_events(db, type=None, limit=limit, offset=offset, extra_where=extra)


@router.get("/{event_id}/reviews", response_model=list[ReviewOut])
def list_reviews(
    event_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> list[Review]:
    event = db.get(Event, event_id)
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")
    stmt = (
        select(Review)
        .options(joinedload(Review.photos))
        .where(Review.event_id == event_id)
        .order_by(Review.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    return list(db.scalars(stmt).unique().all())


@router.get("/{event_id}/rating-summary", response_model=EventRatingSummary)
def rating_summary(event_id: UUID, db: Annotated[Session, Depends(get_db)]) -> EventRatingSummary:
    event = db.get(Event, event_id)
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")
    agg = db.execute(
        select(func.count(Review.id), func.avg(Review.rating)).where(Review.event_id == event_id)
    ).one()
    cnt, avg = agg[0], agg[1]
    return EventRatingSummary(average=float(avg or 0.0), count=int(cnt or 0))


@router.post(
    "/{event_id}/reviews",
    response_model=ReviewOut,
    status_code=status.HTTP_201_CREATED,
)
def create_or_update_review(
    event_id: UUID,
    body: ReviewCreate,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> Review:
    event = db.get(Event, event_id)
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")
    today = datetime.now(timezone.utc).strftime("%d.%m.%y")
    existing = db.query(Review).filter_by(event_id=event_id, user_id=user.id).first()
    if existing:
        existing.rating = body.rating
        existing.text = body.text
        existing.user_name = user.username
        existing.review_date = today
        existing.avatar_url = user.profile_image_url
        for p in list(existing.photos):
            db.delete(p)
        for i, url in enumerate(body.photo_urls):
            db.add(ReviewPhoto(review_id=existing.id, url=url, sort_order=i))
        db.add(existing)
        db.commit()
        stmt = (
            select(Review).options(joinedload(Review.photos)).where(Review.id == existing.id)
        )
        return db.scalars(stmt).unique().one()

    rev = Review(
        event_id=event_id,
        user_id=user.id,
        rating=body.rating,
        text=body.text,
        user_name=user.username,
        review_date=today,
        avatar_url=user.profile_image_url,
    )
    db.add(rev)
    db.flush()
    for i, url in enumerate(body.photo_urls):
        db.add(ReviewPhoto(review_id=rev.id, url=url, sort_order=i))
    db.commit()
    stmt = select(Review).options(joinedload(Review.photos)).where(Review.id == rev.id)
    out = db.scalars(stmt).unique().one()
    return out


@router.get("/{event_id}", response_model=EventOut)
def get_event(event_id: UUID, db: Annotated[Session, Depends(get_db)]) -> Event:
    event = db.get(Event, event_id)
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")
    return event
