"""Тесты ИИ: разбор ответа GigaChat, route-quiz, чат с моком прокси (без сети)."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api.routers import assistant as assistant_mod


def test_clean_giga_response_plain_text() -> None:
    assert assistant_mod.clean_giga_response("  Привет \\n мир  ") == "Привет \n мир"


def test_clean_giga_response_json_with_content() -> None:
    raw = '{"content": "{\\"category\\": \\"искусство\\"}"}'
    out = assistant_mod.clean_giga_response(raw)
    assert "category" in out or "искусство" in out


def test_route_quiz_default_category_when_proxy_empty(client: TestClient, monkeypatch) -> None:
    async def empty_proxy(*args, **kwargs):
        return ""

    monkeypatch.setattr(assistant_mod, "_call_gigachat_proxy", empty_proxy)
    r = client.post("/api/v1/assistant/route-quiz", json={"answers": {"a": 1}})
    assert r.status_code == 200
    assert r.json()["category"] == "история"
    assert r.json()["raw"] is None


def test_route_quiz_parses_json_category(client: TestClient, monkeypatch) -> None:
    async def fake_proxy(messages, **kwargs):
        return '{"category": "искусство"}'

    monkeypatch.setattr(assistant_mod, "_call_gigachat_proxy", fake_proxy)
    r = client.post("/api/v1/assistant/route-quiz", json={"answers": {"q": "x"}})
    assert r.status_code == 200
    body = r.json()
    assert body["category"] == "искусство"


def test_chat_requires_authentication(client: TestClient) -> None:
    r = client.post("/api/v1/assistant/chat", json={"message": "Привет"})
    assert r.status_code == 401


def test_chat_success_with_mocked_proxy(client: TestClient, monkeypatch) -> None:
    async def fake_proxy(messages, **kwargs):
        assert any(m.get("role") == "system" for m in messages)
        assert messages[-1]["role"] == "user"
        return "Visit a theater in Izhevsk."

    monkeypatch.setattr(assistant_mod, "_call_gigachat_proxy", fake_proxy)

    email = f"ai_{uuid.uuid4().hex[:10]}@example.com"
    reg = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password123", "username": "AITester"},
    )
    assert reg.status_code == 200
    token = reg.json()["access_token"]

    r = client.post(
        "/api/v1/assistant/chat",
        headers={"Authorization": f"Bearer {token}"},
        json={"message": "Что посмотреть?"},
    )
    assert r.status_code == 200
    assert "Izhevsk" in r.json()["reply"]


def test_chat_empty_proxy_returns_friendly_message(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(
        assistant_mod,
        "_call_gigachat_proxy",
        AsyncMock(return_value="   "),
    )
    email = f"ai2_{uuid.uuid4().hex[:10]}@example.com"
    client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password123", "username": "u2"},
    )
    login = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "password123"},
    )
    token = login.json()["access_token"]
    r = client.post(
        "/api/v1/assistant/chat",
        headers={"Authorization": f"Bearer {token}"},
        json={"message": "?" },
    )
    assert r.status_code == 200
    assert "ошибк" in r.json()["reply"].lower()


def test_chat_timeout_returns_friendly_message(client: TestClient, monkeypatch) -> None:
    async def timeout_proxy(*a, **k):
        raise httpx.TimeoutException("timeout")

    monkeypatch.setattr(assistant_mod, "_call_gigachat_proxy", timeout_proxy)
    email = f"ai3_{uuid.uuid4().hex[:10]}@example.com"
    client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password123", "username": "u3"},
    )
    token = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "password123"},
    ).json()["access_token"]
    r = client.post(
        "/api/v1/assistant/chat",
        headers={"Authorization": f"Bearer {token}"},
        json={"message": "hi"},
    )
    assert r.status_code == 200
    assert "не отвечает" in r.json()["reply"].lower()
