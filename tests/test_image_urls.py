"""Проверка фильтрации URL картинок (adm.izh.ru плейсхолдеры и т.п.)."""

from __future__ import annotations

from app.schemas.event import merge_event_image_urls, pack_event_gallery_for_storage
from app.utils.image_urls import filter_valid_event_image_urls, is_valid_event_image_url


def test_rejects_adm_izh_void_placeholder() -> None:
    bad = "https://adm.izh.ru/res_ru/0_event_1537_1"
    assert is_valid_event_image_url(bad) is False


def test_accepts_adm_izh_real_file() -> None:
    ok = "https://adm.izh.ru/res_ru/some_1537_poster.jpg"
    assert is_valid_event_image_url(ok) is True


def test_adm_izh_res_ru_requires_extension() -> None:
    assert is_valid_event_image_url("https://adm.izh.ru/res_ru/foo") is False
    assert is_valid_event_image_url("https://adm.izh.ru/res_ru/foo.webp") is True


def test_non_adm_may_have_no_extension() -> None:
    assert is_valid_event_image_url("https://avatars.mds.yandex.net/get-afishanew/123/abc") is True
    assert is_valid_event_image_url("https://cdn.somecdn.net/img/abc123.jpg") is True


def test_rejects_example_com_placeholder() -> None:
    assert is_valid_event_image_url("https://example.com/poster.jpg") is False
    assert is_valid_event_image_url("https://cdn.example.com/img/abc123") is False


def test_merge_drops_invalid_keeps_valid() -> None:
    raw = '["https://adm.izh.ru/res_ru/0_event_1_1", "https://adm.izh.ru/res_ru/a.png"]'
    merged = merge_event_image_urls(raw, "https://adm.izh.ru/res_ru/0_event_2_2")
    assert merged == ["https://adm.izh.ru/res_ru/a.png"]


def test_pack_event_gallery_for_storage() -> None:
    img, js = pack_event_gallery_for_storage(
        "https://adm.izh.ru/res_ru/0_event_1_1",
        [
            "https://adm.izh.ru/res_ru/0_event_1_1",
            "https://adm.izh.ru/res_ru/poster.jpeg",
        ],
    )
    assert img == "https://adm.izh.ru/res_ru/poster.jpeg"
    assert js is not None
    assert "poster.jpeg" in js
    assert "0_event_" not in js


def test_filter_valid_preserves_order() -> None:
    u = filter_valid_event_image_urls(
        [
            "https://a.com/x.jpg",
            "https://adm.izh.ru/res_ru/0_event_9_1",
            "https://b.com/y.png",
        ]
    )
    assert u == ["https://a.com/x.jpg", "https://b.com/y.png"]
