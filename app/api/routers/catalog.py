from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.admin_deps import require_admin_key
from app.database import get_db
from app.models import HomeCategory
from app.schemas.event import HomeCategoryCreate, HomeCategoryOut

router = APIRouter()


@router.get("/home-categories", response_model=list[HomeCategoryOut])
def list_home_categories(db: Annotated[Session, Depends(get_db)]) -> list[HomeCategory]:
    stmt = select(HomeCategory).order_by(HomeCategory.sort_order, HomeCategory.name)
    return list(db.scalars(stmt).all())


@router.post(
    "/home-categories",
    response_model=HomeCategoryOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin_key)],
)
def create_home_category(
    body: HomeCategoryCreate,
    db: Annotated[Session, Depends(get_db)],
) -> HomeCategory:
    row = HomeCategory(name=body.name, type=body.type, sort_order=body.sort_order)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row
