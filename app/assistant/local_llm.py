from __future__ import annotations

from typing import Any

import httpx

from app.config import settings


class LocalLlmError(RuntimeError):
    pass


async def chat_completion(
    messages: list[dict[str, str]],
    *,
    max_tokens: int | None = None,
    temperature: float | None = None,
) -> str:
    """
    Calls a local OpenAI-compatible chat endpoint, e.g. llama.cpp server:
      POST {assistant_base_url}/chat/completions
    """
    base = (settings.assistant_base_url or "").rstrip("/")
    if not base:
        raise LocalLlmError("assistant_base_url is not configured")

    url = f"{base}/chat/completions"
    payload: dict[str, Any] = {
        "model": settings.assistant_model or "local-model",
        "messages": messages,
        "temperature": settings.assistant_temperature if temperature is None else float(temperature),
        "top_p": 0.9,
        "max_tokens": settings.assistant_max_tokens if max_tokens is None else int(max_tokens),
        "stream": False,
    }
    timeout = httpx.Timeout(settings.assistant_timeout)
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(url, json=payload, headers={"Content-Type": "application/json"})
    if r.status_code != 200:
        raise LocalLlmError(f"LLM HTTP {r.status_code}: {r.text[:300]}")
    data = r.json()
    try:
        return str(data["choices"][0]["message"]["content"]).strip()
    except Exception as e:  # noqa: BLE001
        raise LocalLlmError(f"Unexpected LLM response shape: {data!r}") from e

