"""Переменные окружения должны быть заданы до импорта приложения (см. app.config)."""

from __future__ import annotations

import os

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql://postgres:postgres@127.0.0.1:5432/technostrelka_test",
)
os.environ.setdefault("ADMIN_API_KEY", "pytest-admin-key")
os.environ.setdefault("SECRET_KEY", "pytest-secret-key-for-jwt")
os.environ.setdefault("PUBLIC_BASE_URL", "http://testserver")
os.environ.setdefault("INGEST_ENABLED", "false")

import pytest
from fastapi.testclient import TestClient

from app.database import Base, engine
from app.main import app


@pytest.fixture(scope="session")
def setup_database():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="session")
def client(setup_database):
    with TestClient(app) as c:
        yield c


@pytest.fixture
def mock_llm(monkeypatch):
    async def fake_gigachat(
        messages: list[dict],
        *,
        max_tokens: int | None = None,
    ) -> str:
        first = messages[0] if messages else {}
        content = (first.get("content") or "").lower()
        if first.get("role") == "system" and "классификатор" in content:
            return '{"category": "IT"}'
        return "Mock assistant reply."

    monkeypatch.setattr(
        "app.api.routers.assistant._call_gigachat_proxy",
        fake_gigachat,
    )
