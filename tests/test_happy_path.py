"""Happy path: main API flows (LLM mocked)."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def unique_email() -> str:
    return f"user_{uuid.uuid4().hex[:12]}@example.com"


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_health(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_full_backend_happy_path(
    client: TestClient,
    mock_llm,
    unique_email: str,
) -> None:
    admin_key = "pytest-admin-key"
    password = "secretpass123"

    r = client.post(
        "/api/v1/auth/register",
        json={
            "email": unique_email,
            "password": password,
            "username": "Happy User",
        },
    )
    assert r.status_code == 200
    token = r.json()["access_token"]
    headers = auth_headers(token)

    r = client.get("/api/v1/users/me", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["email"] == unique_email
    assert body["username"] == "Happy User"
    user_id = body["id"]

    r = client.post(
        "/api/v1/events",
        headers={"X-Admin-Key": admin_key},
        json={
            "name": "HappyPath Test Event",
            "slug": "test_happy_event",
            "type": "IT",
            "description": "unique search phrase for tests",
            "place": "Test Street",
            "img_url": "https://example.com/poster.jpg",
        },
    )
    assert r.status_code == 201
    event = r.json()
    event_id = event["id"]
    assert event["name"] == "HappyPath Test Event"
    assert event["review_bucket"] is not None

    r = client.get("/api/v1/events", headers=headers)
    assert r.status_code == 200
    assert any(e["id"] == event_id for e in r.json())

    r = client.get(f"/api/v1/events/{event_id}", headers=headers)
    assert r.status_code == 200
    assert r.json()["id"] == event_id

    r = client.get(
        "/api/v1/events/search",
        params={"q": "unique search phrase"},
        headers=headers,
    )
    assert r.status_code == 200
    assert any(e["id"] == event_id for e in r.json())

    r = client.get("/api/v1/home-categories", headers=headers)
    assert r.status_code == 200
    categories = r.json()
    assert len(categories) >= 1
    types = {c["type"] for c in categories}
    assert "IT" in types

    r = client.put(f"/api/v1/users/me/favorites/{event_id}", headers=headers)
    assert r.status_code == 204

    r = client.get("/api/v1/users/me/favorites", headers=headers)
    assert r.status_code == 200
    favs = r.json()
    assert len(favs) == 1
    assert favs[0]["id"] == event_id

    fake_other = str(uuid.uuid4())
    r = client.get(
        "/api/v1/users/me/favorites/status",
        params=[("event_ids", event_id), ("event_ids", fake_other)],
        headers=headers,
    )
    assert r.status_code == 200
    st = r.json()["favorites"]
    assert st[str(event_id)] is True
    assert st[fake_other] is False

    tiny_jpeg = b"\xff\xd8\xff\xdb\x00C\x00\xff\xd9"

    r = client.post(
        "/api/v1/uploads/review-photos",
        headers=headers,
        data={"event_id": event_id},
        files=[("files", ("shot.jpg", tiny_jpeg, "image/jpeg"))],
    )
    assert r.status_code == 201
    photo_urls = r.json()["urls"]
    assert len(photo_urls) == 1
    assert photo_urls[0].startswith("http://testserver/static/")

    r = client.post(
        f"/api/v1/events/{event_id}/reviews",
        headers=headers,
        json={
            "rating": 5,
            "text": "Great event",
            "photo_urls": photo_urls,
        },
    )
    assert r.status_code == 201
    rev = r.json()
    assert rev["rating"] == 5
    assert len(rev["photos"]) == 1

    r = client.get(f"/api/v1/events/{event_id}/reviews", headers=headers)
    assert r.status_code == 200
    reviews = r.json()
    assert len(reviews) == 1
    assert reviews[0]["user_id"] == user_id

    r = client.get(f"/api/v1/events/{event_id}/rating-summary", headers=headers)
    assert r.status_code == 200
    summary = r.json()
    assert summary["count"] == 1
    assert summary["average"] == 5.0

    r = client.patch(
        "/api/v1/users/me",
        headers=headers,
        json={"category_user": "art"},
    )
    assert r.status_code == 200
    assert r.json()["category_user"] == "art"

    r = client.post(
        "/api/v1/users/me/progress/increment",
        headers=headers,
        json={"delta": 5, "cap_at": 100},
    )
    assert r.status_code == 200
    assert r.json()["progress"] == 5

    r = client.get("/api/v1/users/me/progress", headers=headers)
    assert r.status_code == 200
    assert r.json()["progress"] == 5
    assert r.json()["score"] >= 5

    r = client.post(
        "/api/v1/users/me/viewed-content",
        headers=headers,
        json={
            "content_id": "article-1",
            "content_type": "article",
            "is_completed": True,
        },
    )
    assert r.status_code == 204

    r = client.post(
        "/api/v1/users/me/device-tokens",
        headers=headers,
        json={"token": "fcm-token-demo"},
    )
    assert r.status_code == 204

    r = client.post(
        "/api/v1/assistant/route-quiz",
        json={"answers": {"q1": "code"}, "update_profile_category": False},
    )
    assert r.status_code == 200
    assert r.json()["category"] == "IT"

    r = client.post(
        "/api/v1/assistant/chat",
        headers=headers,
        json={"message": "What to see?"},
    )
    assert r.status_code == 200
    assert "Mock assistant" in r.json()["reply"]

    avatar_bytes = tiny_jpeg
    r = client.post(
        "/api/v1/users/me/avatar",
        headers=headers,
        files={"file": ("ava.jpg", avatar_bytes, "image/jpeg")},
    )
    assert r.status_code == 200
    assert r.json()["profile_image_url"] is not None

    r = client.post("/api/v1/auth/logout", headers=headers)
    assert r.status_code == 204

    r = client.post(
        "/api/v1/auth/login",
        json={"email": unique_email, "password": password},
    )
    assert r.status_code == 200
    new_token = r.json()["access_token"]
    new_headers = auth_headers(new_token)

    r = client.delete(f"/api/v1/users/me/favorites/{event_id}", headers=new_headers)
    assert r.status_code == 204

    r = client.get("/api/v1/users/me/favorites", headers=new_headers)
    assert r.status_code == 200
    assert r.json() == []

    r = client.post(
        "/api/v1/home-categories",
        headers={"X-Admin-Key": admin_key},
        json={"name": "Cinema", "type": "Cinema", "sort_order": 42},
    )
    assert r.status_code == 201
    assert r.json()["type"] == "Cinema"

    r = client.get("/api/v1/events", params={"type": "IT"}, headers=new_headers)
    assert r.status_code == 200
    assert any(e["id"] == event_id for e in r.json())
