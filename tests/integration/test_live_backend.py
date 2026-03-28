"""
Проверка реально запущенного бекенда (Docker / uvicorn), без моков HTTP и LLM.

Запуск (API должен отвечать, по умолчанию http://127.0.0.1:8000):

  pytest tests/integration -v -m live

Переменные окружения:
  LIVE_BACKEND_URL   — базовый URL API (по умолчанию http://127.0.0.1:8000)
  LIVE_ADMIN_API_KEY — X-Admin-Key для POST /events и POST /admin/ingest/run (как в docker-compose)
  LIVE_ASSISTANT_STRICT — если "1"/"true", чат считается успешным только если ответ не похож на ошибку прокси
"""

from __future__ import annotations

import os
import uuid

import httpx
import pytest

pytestmark = pytest.mark.live

LIVE_URL = os.environ.get("LIVE_BACKEND_URL", "http://127.0.0.1:8000").rstrip("/")
ADMIN_KEY = os.environ.get("LIVE_ADMIN_API_KEY", "").strip()
ASSISTANT_STRICT = os.environ.get("LIVE_ASSISTANT_STRICT", "").lower() in ("1", "true", "yes")


@pytest.fixture(scope="module")
def live_client() -> httpx.Client:
    try:
        r = httpx.get(f"{LIVE_URL}/health", timeout=5.0)
    except httpx.RequestError as e:
        pytest.skip(f"Бекенд недоступен по {LIVE_URL}: {e}")
    if r.status_code != 200:
        pytest.skip(f"/health вернул {r.status_code}, ожидался 200")
    with httpx.Client(base_url=LIVE_URL, timeout=120.0, follow_redirects=True) as c:
        yield c


def test_live_health(live_client: httpx.Client) -> None:
    r = live_client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_live_openapi_available(live_client: httpx.Client) -> None:
    r = live_client.get("/docs")
    assert r.status_code == 200


def test_live_register_login_profile(live_client: httpx.Client) -> None:
    email = f"live_{uuid.uuid4().hex[:16]}@example.com"
    password = "livepass123456"
    reg = live_client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "username": "LiveUser"},
    )
    assert reg.status_code == 200, reg.text
    token = reg.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    me = live_client.get("/api/v1/users/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["email"] == email

    login = live_client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert login.status_code == 200
    assert login.json()["access_token"]


def test_live_events_and_categories(live_client: httpx.Client) -> None:
    r = live_client.get("/api/v1/events")
    assert r.status_code == 200
    assert isinstance(r.json(), list)

    c = live_client.get("/api/v1/home-categories")
    assert c.status_code == 200
    cats = c.json()
    assert isinstance(cats, list)
    assert len(cats) >= 1


def test_live_assistant_route_quiz_real_upstream(live_client: httpx.Client) -> None:
    """Реальный вызов прокси GigaChat (как в проде), без monkeypatch."""
    r = live_client.post(
        "/api/v1/assistant/route-quiz",
        json={"answers": {"interest": "музеи и выставки"}, "update_profile_category": False},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "category" in body
    assert body["category"].strip()


def test_live_assistant_chat_real_upstream(live_client: httpx.Client) -> None:
    email = f"live_ai_{uuid.uuid4().hex[:12]}@example.com"
    reg = live_client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "livepass123456", "username": "LiveAI"},
    )
    assert reg.status_code == 200, reg.text
    token = reg.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    r = live_client.post(
        "/api/v1/assistant/chat",
        headers=headers,
        json={"message": "Кратко: что можно посмотреть в Ижевске в выходные?"},
    )
    assert r.status_code == 200, r.text
    reply = r.json().get("reply", "")
    assert isinstance(reply, str)
    assert len(reply) > 0

    if ASSISTANT_STRICT:
        low = reply.lower()
        assert not low.startswith("извините, произошла ошибка")
        assert "не удается подключиться" not in low
        assert "не отвечает" not in low


@pytest.mark.skipif(not ADMIN_KEY, reason="Задайте LIVE_ADMIN_API_KEY (тот же, что X-Admin-Key на сервере)")
def test_live_admin_ingest(live_client: httpx.Client) -> None:
    """Реальный прогон импорта (RSS + adm.izh.ru) с сервера приложения."""
    r = live_client.post(
        "/api/v1/admin/ingest/run",
        headers={"X-Admin-Key": ADMIN_KEY},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert isinstance(data, dict)


@pytest.mark.skipif(not ADMIN_KEY, reason="Задайте LIVE_ADMIN_API_KEY")
def test_live_admin_create_event(live_client: httpx.Client) -> None:
    r = live_client.post(
        "/api/v1/events",
        headers={"X-Admin-Key": ADMIN_KEY},
        json={
            "name": f"Live smoke {uuid.uuid4().hex[:8]}",
            "type": "IT",
            "description": "Создано live-тестом",
            "place": "Ижевск",
        },
    )
    assert r.status_code == 201, r.text
    ev = r.json()
    assert ev.get("name")
    assert ev.get("id")
