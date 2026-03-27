import json
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.config import settings

router = APIRouter()


class RouteQuizAnswers(BaseModel):
    answers: dict[str, Any] = Field(default_factory=dict)
    update_profile_category: bool = True


class RouteQuizResponse(BaseModel):
    category: str
    raw: str | None = None


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    system: str | None = None


class ChatResponse(BaseModel):
    reply: str


async def _openai_chat(messages: list[dict[str, str]]) -> str:
    if not settings.openai_api_key:
        raise HTTPException(
            status_code=503,
            detail="LLM is not configured (set OPENAI_API_KEY)",
        )
    url = f"{settings.openai_base_url.rstrip('/')}/chat/completions"
    headers = {"Authorization": f"Bearer {settings.openai_api_key}"}
    payload = {
        "model": settings.openai_chat_model,
        "messages": messages,
        "temperature": 0.3,
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.post(url, json=payload, headers=headers)
        if r.status_code >= 400:
            raise HTTPException(
                status_code=502,
                detail=f"LLM error: {r.status_code} {r.text[:500]}",
            )
        data = r.json()
    try:
        return data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError):
        raise HTTPException(status_code=502, detail="Unexpected LLM response shape")


@router.post("/route-quiz", response_model=RouteQuizResponse)
async def route_quiz(body: RouteQuizAnswers) -> RouteQuizResponse:
    system = (
        "You are a classifier for city event interests. "
        "Given user quiz answers as JSON, respond with exactly one category label "
        "from this set: IT, искусство, история. "
        "Reply as JSON only: {\"category\":\"...\"}"
    )
    user_content = json.dumps(body.answers, ensure_ascii=False)
    raw = await _openai_chat(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ]
    )
    try:
        parsed = json.loads(raw)
        cat = str(parsed.get("category", "")).strip() or "история"
    except json.JSONDecodeError:
        cat = "история"
    return RouteQuizResponse(category=cat, raw=raw)


@router.post("/chat", response_model=ChatResponse)
async def chat(body: ChatRequest) -> ChatResponse:
    messages: list[dict[str, str]] = []
    if body.system:
        messages.append({"role": "system", "content": body.system})
    messages.append({"role": "user", "content": body.message})
    reply = await _openai_chat(messages)
    return ChatResponse(reply=reply)
