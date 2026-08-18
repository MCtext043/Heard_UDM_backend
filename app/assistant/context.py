from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.assistant.rules import extract_keywords
from app.models import Event


def find_relevant_events(db: Session, user_message: str, *, limit: int = 6) -> list[Event]:
    kws = extract_keywords(user_message, limit=6)
    stmt = select(Event)
    if kws:
        ors = []
        for kw in kws:
            term = f"%{kw}%"
            ors.extend([Event.name.ilike(term), Event.description.ilike(term), Event.place.ilike(term)])
        stmt = stmt.where(or_(*ors))
    stmt = stmt.order_by(Event.created_at.desc()).limit(limit)
    return list(db.scalars(stmt).all())


def build_events_context(db: Session, user_message: str, *, limit: int = 6) -> str:
    """
    Pulls a small set of relevant events from DB to ground assistant answers.
    """
    events = find_relevant_events(db, user_message, limit=limit)
    if not events:
        return "События из базы: (ничего не найдено по запросу)"

    lines = ["События из базы (для ответа, не выдумывай вне списка):"]
    for ev in events:
        bits: list[str] = []
        if ev.date_caption:
            bits.append(ev.date_caption.strip())
        if ev.place:
            bits.append(ev.place.strip())
        meta = " — ".join([b for b in bits if b])
        meta_s = f" ({meta})" if meta else ""

        # Keep context short to avoid slow inference on small CPU boxes.
        name = (ev.name or "").strip()
        if len(name) > 120:
            name = name[:117].rstrip() + "..."
        url_s = f" URL: {ev.url}" if ev.url and len(ev.url) <= 140 else ""
        lines.append(f"- {name}{meta_s}{url_s}")
    return "\n".join(lines)

