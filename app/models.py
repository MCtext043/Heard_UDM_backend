import uuid
from datetime import datetime
from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    username: Mapped[str] = mapped_column(String(120), nullable=False)
    profile_image_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    category_user: Mapped[str | None] = mapped_column(String(64), nullable=True)
    post_text: Mapped[str] = mapped_column(Text, default="", server_default="")
    post_name_text: Mapped[str] = mapped_column(Text, default="", server_default="")
    post_images: Mapped[str] = mapped_column(Text, default="", server_default="")
    progress: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    score: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    progress_last_updated: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    favorites: Mapped[list["Favorite"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    reviews: Mapped[list["Review"]] = relationship(back_populates="user")
    viewed_items: Mapped[list["ViewedContent"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    device_tokens: Mapped[list["DeviceToken"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class HomeCategory(Base):
    __tablename__ = "home_categories"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class Event(Base):
    __tablename__ = "events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    slug: Mapped[str | None] = mapped_column(String(512), unique=True, nullable=True)
    img_url: Mapped[str | None] = mapped_column(String(2048))
    description: Mapped[str | None] = mapped_column(Text)
    age: Mapped[str | None] = mapped_column(String(32))
    date_caption: Mapped[str | None] = mapped_column(String(512))
    place: Mapped[str | None] = mapped_column(String(512))
    url: Mapped[str | None] = mapped_column(String(2048))
    rating: Mapped[str | None] = mapped_column(String(32))
    schedule: Mapped[str | None] = mapped_column(String(512))
    status: Mapped[str | None] = mapped_column(String(64))
    type: Mapped[str | None] = mapped_column(String(64), index=True)
    review_bucket: Mapped[str | None] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    favorites: Mapped[list["Favorite"]] = relationship(back_populates="event")
    reviews: Mapped[list["Review"]] = relationship(back_populates="event", cascade="all, delete-orphan")


class Favorite(Base):
    __tablename__ = "favorites"
    __table_args__ = (UniqueConstraint("user_id", "event_id", name="uq_favorites_user_event"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    event_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("events.id", ondelete="CASCADE"))

    user: Mapped["User"] = relationship(back_populates="favorites")
    event: Mapped["Event"] = relationship(back_populates="favorites")


class Review(Base):
    __tablename__ = "reviews"
    __table_args__ = (UniqueConstraint("event_id", "user_id", name="uq_reviews_event_user"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("events.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, default="", server_default="")
    user_name: Mapped[str] = mapped_column(String(120), nullable=False)
    review_date: Mapped[str | None] = mapped_column(String(32))
    avatar_url: Mapped[str | None] = mapped_column(String(2048))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    event: Mapped["Event"] = relationship(back_populates="reviews")
    user: Mapped["User"] = relationship(back_populates="reviews")
    photos: Mapped[list["ReviewPhoto"]] = relationship(
        back_populates="review", cascade="all, delete-orphan", order_by="ReviewPhoto.sort_order"
    )


class ReviewPhoto(Base):
    __tablename__ = "review_photos"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    review_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("reviews.id", ondelete="CASCADE"))
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    review: Mapped["Review"] = relationship(back_populates="photos")


class ViewedContent(Base):
    __tablename__ = "viewed_content"
    __table_args__ = (UniqueConstraint("user_id", "content_id", name="uq_viewed_user_content"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    content_id: Mapped[str] = mapped_column(String(256), nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(64))
    viewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    is_completed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    user: Mapped["User"] = relationship(back_populates="viewed_items")


class DeviceToken(Base):
    __tablename__ = "device_tokens"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    token: Mapped[str] = mapped_column(String(512), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="device_tokens")
