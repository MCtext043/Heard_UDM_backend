"""
Ассистент для мобильного приложения.

Эндпоинты и контракт не меняем, но реализация работает локально:
- либо через локальный OpenAI-compatible сервер (например, llama.cpp server),
- либо через безопасный deterministic fallback без внешних AI сервисов.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser
from app.assistant.context import find_relevant_events
from app.assistant.local_llm import LocalLlmError, chat_completion
from app.assistant.rules import route_quiz_category
from app.config import settings
from app.database import get_db
from app.models import Event, Favorite, User

router = APIRouter()

# Промпт для афиши / городских событий (не финансы, как в SmartWallet).
TECHNOSTRELKA_ASSISTANT_SYSTEM = (
    "Ты дружелюбный гид по городским и культурным событиям: афиша, кино, театр, "
    "выставки, концерты, лекции, прогулки и другие активности.\n"
    "Помогаешь пользователю выбрать, чем заняться в свободное время, как спланировать вечер или выходные.\n"
    "Отвечай по-русски, кратко и по делу, без лишней воды.\n"
    "Если в контексте пользователя нет конкретных названий или дат событий, не выдумывай их — "
    "давай общие советы, направления или попроси уточнить город, дату и тип отдыха.\n"
    "Не обещай скидки и не подделывай ссылки; если нужна официальная афиша, порекомендуй проверить "
    "проверенные площадки и приложение, из которого пользователь пишет."
)


class RouteQuizAnswers(BaseModel):
    answers: dict[str, Any] = Field(default_factory=dict)
    update_profile_category: bool = True


class RouteQuizResponse(BaseModel):
    category: str
    raw: str | None = None


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)


class ChatResponse(BaseModel):
    reply: str


def clean_giga_response(response_text: str) -> str:
    """Как в SmartWallet: разбор JSON-обёртки GigaChat и нормализация escape-последовательностей."""
    text = response_text
    try:
        giga_data = json.loads(response_text)
        if isinstance(giga_data, dict):
            if "content" in giga_data:
                text = giga_data["content"]
            else:
                text = response_text
        else:
            text = response_text
    except (ValueError, TypeError):
        text = response_text

    text = text.strip()
    text = text.replace("\\n", "\n")
    text = text.replace('\\"', '"')
    text = text.replace("\\/", "/")
    text = text.replace("\\\\", "\\")
    text = text.replace("\\t", "\t")
    return text


def get_user_context(user: User, db: Session) -> str:
    """Контекст для чата (аналог карт/транзакций в SmartWallet — профиль и избранное)."""
    lines = [f"Имя: {user.username}", f"Email: {user.email}"]
    if user.category_user:
        lines.append(f"Выбранные интересы (категория): {user.category_user}")
    rows = (
        db.query(Event.name)
        .join(Favorite, Favorite.event_id == Event.id)
        .filter(Favorite.user_id == user.id)
        .limit(8)
        .all()
    )
    if rows:
        lines.append("Избранные события в приложении: " + ", ".join(r[0] for r in rows))
    return "\n".join(lines)


def _build_chat_system_message(user_context: str) -> str:
    return (
        f"{TECHNOSTRELKA_ASSISTANT_SYSTEM}\n\n"
        f"Контекст пользователя из приложения:\n{user_context}"
    )


async def _assistant_llm(messages: list[dict[str, str]], *, max_tokens: int | None = None) -> str:
    provider = (settings.assistant_provider or "").strip().lower()
    if provider != "llamacpp_http":
        return ""
    return await chat_completion(messages, max_tokens=max_tokens)


def _build_rules_reply(user_message: str, user_context: str, events_context: str) -> str:
    # Minimal non-LLM fallback that still uses DB context.
    base = (
        "Я могу подсказать идеи по афише и активности в городе.\n\n"
        f"{events_context}\n\n"
        "Скажи, пожалуйста: город/район, даты (сегодня/выходные/конкретная дата) и что именно хочется "
        "(театр, выставка, кино, прогулка, концерт, лекция, семейное и т.п.)."
    )
    if user_message.strip():
        return base
    return base


def _looks_like_bad_llm_reply(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return True
    # CJK characters usually indicate the model drifted out of Russian context.
    if any("\u4e00" <= ch <= "\u9fff" for ch in t):
        return True
    letters = [ch for ch in t if ch.isalpha()]
    if not letters:
        return True
    cyr = [ch for ch in letters if ("а" <= ch.lower() <= "я") or (ch.lower() in ("ё",))]
    # If too few Cyrillic letters, prefer DB-grounded fallback.
    return (len(cyr) / max(1, len(letters))) < 0.25


def _events_context_from_list(events: list[Event]) -> str:
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
        name = (ev.name or "").strip()
        if len(name) > 120:
            name = name[:117].rstrip() + "..."
        url_s = f" URL: {ev.url}" if ev.url and len(ev.url) <= 140 else ""
        lines.append(f"- {name}{meta_s}{url_s}")
    return "\n".join(lines)


def _candidate_list_for_llm(events: list[Event]) -> str:
    lines: list[str] = []
    for i, ev in enumerate(events, start=1):
        name = (ev.name or "").strip()
        if len(name) > 120:
            name = name[:117].rstrip() + "..."
        meta = " | ".join([x.strip() for x in [ev.date_caption or "", ev.place or ""] if x and x.strip()])
        meta_s = f" | {meta}" if meta else ""
        lines.append(f"{i}. {name}{meta_s}")
    return "\n".join(lines)


@router.post("/route-quiz", response_model=RouteQuizResponse)
async def route_quiz(body: RouteQuizAnswers) -> RouteQuizResponse:
    # Always return 200 (mobile app depends on endpoint stability).
    # Prefer local LLM if configured; otherwise use deterministic rules.
    fallback = route_quiz_category(body.answers)
    system = (
        "Ты классификатор интересов к городским событиям. По ответам пользователя (JSON) "
        "выбери ровно одну метку из набора: IT, искусство, история.\n"
        "Ответь только JSON без пояснений: {\"category\":\"...\"}"
    )
    user_content = json.dumps(body.answers, ensure_ascii=False)
    try:
        raw = await _assistant_llm(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user_content},
            ],
            max_tokens=64,
        )
        if not raw.strip():
            return RouteQuizResponse(category=fallback, raw=None)
        cleaned = clean_giga_response(raw)
        cat = fallback
        for candidate in (cleaned, raw):
            try:
                parsed = json.loads(candidate)
                if isinstance(parsed, dict):
                    c = str(parsed.get("category", "")).strip()
                    if c:
                        # Only allow expected labels; otherwise keep deterministic fallback.
                        low = c.lower()
                        if low == "it":
                            cat = "IT"
                        elif low in ("искусство", "история"):
                            cat = low
                        break
            except json.JSONDecodeError:
                continue
        return RouteQuizResponse(category=cat, raw=cleaned or raw)
    except Exception:
        return RouteQuizResponse(category=fallback, raw=None)


@router.post("/chat", response_model=ChatResponse)
async def chat(
    body: ChatRequest,
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> ChatResponse:
    """Чат ассистента; требуется Bearer."""
    user_context = get_user_context(user, db)
    events = find_relevant_events(db, body.message, limit=7)
    events_context = _events_context_from_list(events[:5])
    candidates = _candidate_list_for_llm(events[:7])
    try:
        if not candidates.strip():
            return ChatResponse(reply=_build_rules_reply(body.message, user_context, events_context))

        system = (
            f"{TECHNOSTRELKA_ASSISTANT_SYSTEM}\n\n"
            "Твоя задача: выбрать подходящие события ТОЛЬКО из списка кандидатов.\n"
            "Запрещено придумывать новые события, даты или места.\n"
            "Ответь только JSON без пояснений:\n"
            "{\"pick\":[1,2,3],\"followup\":\"...\"}\n"
            "- pick: 3..7 номеров из списка\n"
            "- followup: один короткий уточняющий вопрос по городу/датам/типу отдыха\n"
        )
        raw = await _assistant_llm(
            [
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": f"Контекст пользователя:\n{user_context}\n\nЗапрос:\n{body.message}\n\nКандидаты:\n{candidates}",
                },
            ],
            max_tokens=160,
        )
        if not raw.strip():
            return ChatResponse(reply=_build_rules_reply(body.message, user_context, events_context))
        cleaned = clean_giga_response(raw)
        data = None
        for cand in (cleaned, raw):
            try:
                data = json.loads(cand)
                if isinstance(data, dict):
                    break
            except Exception:
                data = None
        if not isinstance(data, dict):
            return ChatResponse(reply=_build_rules_reply(body.message, user_context, events_context))

        picks = data.get("pick", [])
        if not isinstance(picks, list):
            picks = []
        idxs: list[int] = []
        for x in picks:
            try:
                i = int(x)
            except Exception:
                continue
            if 1 <= i <= len(events):
                if i not in idxs:
                    idxs.append(i)
        if len(idxs) < 3:
            return ChatResponse(reply=_build_rules_reply(body.message, user_context, events_context))

        followup = str(data.get("followup", "") or "").strip()

        # Build final reply from DB (no hallucinations).
        out_lines = ["Вот что можно выбрать из афиши:"]
        for i in idxs[:7]:
            ev = events[i - 1]
            bits: list[str] = []
            if ev.date_caption:
                bits.append(ev.date_caption.strip())
            if ev.place:
                bits.append(ev.place.strip())
            meta = " — ".join([b for b in bits if b])
            meta_s = f" ({meta})" if meta else ""
            url_s = f" — {ev.url}" if ev.url else ""
            out_lines.append(f"- {ev.name}{meta_s}{url_s}")
        if followup:
            out_lines.append("")
            out_lines.append(followup)
        return ChatResponse(reply="\n".join(out_lines))
    except LocalLlmError:
        return ChatResponse(reply=_build_rules_reply(body.message, user_context, events_context))
    except Exception:
        return ChatResponse(reply=_build_rules_reply(body.message, user_context, events_context))
