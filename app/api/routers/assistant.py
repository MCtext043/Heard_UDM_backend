"""
Ассистент: тот же внешний эндпоинт, что и в SmartWallet
(https://github.com/MCtext043/SmartWallet — POST на derendyaev.ru/api/gigachat/message,
те же поля model/stream/messages/max_tokens и т.д.), но системные инструкции свои.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser
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


async def _call_gigachat_proxy(
    messages: list[dict[str, str]],
    *,
    max_tokens: int | None = None,
) -> str:
    """Тело запроса как в SmartWallet routers/assistant.py (requests.post на этот URL)."""
    max_tok = max_tokens if max_tokens is not None else settings.gigachat_max_tokens
    payload: dict[str, Any] = {
        "model": settings.gigachat_model,
        "stream": False,
        "update_interval": 0,
        "messages": messages,
        "n": 1,
        "max_tokens": max_tok,
        "repetition_penalty": 1.0,
    }
    timeout = httpx.Timeout(settings.gigachat_timeout)
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(
            settings.gigachat_proxy_url,
            json=payload,
            headers={"Content-Type": "application/json"},
        )
    if r.status_code != 200:
        return ""
    return r.text


@router.post("/route-quiz", response_model=RouteQuizResponse)
async def route_quiz(body: RouteQuizAnswers) -> RouteQuizResponse:
    system = (
        "Ты классификатор интересов к городским событиям. По ответам пользователя (JSON) "
        "выбери ровно одну метку из набора: IT, искусство, история.\n"
        "Ответь только JSON без пояснений: {\"category\":\"...\"}"
    )
    user_content = json.dumps(body.answers, ensure_ascii=False)
    raw = await _call_gigachat_proxy(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ],
    )
    if not raw.strip():
        return RouteQuizResponse(category="история", raw=None)
    cleaned = clean_giga_response(raw)
    cat = "история"
    for candidate in (cleaned, raw):
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                c = str(parsed.get("category", "")).strip()
                if c:
                    cat = c
                    break
        except json.JSONDecodeError:
            continue
    return RouteQuizResponse(category=cat, raw=cleaned or raw)


@router.post("/chat", response_model=ChatResponse)
async def chat(
    body: ChatRequest,
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> ChatResponse:
    """Чат с тем же бэкендом GigaChat, что SmartWallet; требуется Bearer (см. CHAT_API.md у них)."""
    user_context = get_user_context(user, db)
    system_message = _build_chat_system_message(user_context)
    messages = [
        {"role": "system", "content": system_message},
        {"role": "user", "content": body.message},
    ]
    try:
        raw = await _call_gigachat_proxy(messages)
        if not raw.strip():
            return ChatResponse(
                reply="Извините, произошла ошибка при обращении к ассистенту. Попробуйте позже.",
            )
        clean_reply = clean_giga_response(raw)
        return ChatResponse(reply=clean_reply)
    except httpx.TimeoutException:
        return ChatResponse(reply="Извините, ассистент не отвечает. Попробуйте позже.")
    except httpx.ConnectError:
        return ChatResponse(
            reply="Извините, не удается подключиться к ассистенту. Проверьте интернет-соединение.",
        )
    except Exception as e:  # noqa: BLE001 — как запасной путь в SmartWallet
        return ChatResponse(reply=f"Произошла ошибка: {e!s}")
