"""Тесты импорта афиши: RSS и adm.izh с моком HTTP (без реальных запросов)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.models import Event
from app.services.ingest.adm_izh import ingest_adm_izh
from app.services.ingest.rss import ingest_rss_izhevsk
from app.services.ingest.runner import run_izhevsk_ingest


@pytest.fixture
def db_session(setup_database) -> Session:
    s = SessionLocal()
    s.query(Event).filter(Event.ingest_key.isnot(None)).delete()
    s.commit()
    try:
        yield s
    finally:
        s.query(Event).filter(Event.ingest_key.isnot(None)).delete()
        s.commit()
        s.close()


def test_rss_ingest_creates_event_with_region_keyword(db_session: Session, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.ingest.rss.settings",
        settings.model_copy(update={"izhevsk_rss_feed_urls": "http://test-feed.local/x.xml"}),
    )
    xml = """<?xml version="1.0" encoding="utf-8"?>
    <rss version="2.0"><channel>
      <item>
        <title>Спектакль в Ижевске</title>
        <link>https://theater.example/show/1</link>
        <description>Афиша Ижевска на выходные</description>
      </item>
    </channel></rss>"""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = xml.encode("utf-8")

    inner = MagicMock()
    inner.get.return_value = mock_resp
    cm = MagicMock()
    cm.__enter__.return_value = inner
    cm.__exit__.return_value = None

    with patch("app.services.ingest.rss.httpx.Client", MagicMock(return_value=cm)):
        stats = ingest_rss_izhevsk(db_session)

    assert stats["rss_upserted"] == 1
    assert stats["rss_skipped"] == 0
    ev = db_session.query(Event).filter(Event.ingest_key.like("rss:%")).one()
    assert "Ижевск" in ev.name or "Ижевск" in (ev.description or "")
    assert "Ижевск" in (ev.place or "")
    assert "theater.example" in (ev.place or "")


def test_rss_skips_without_region_when_required(db_session: Session, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.ingest.rss.settings",
        settings.model_copy(
            update={
                "izhevsk_rss_feed_urls": "http://test-feed.local/y.xml",
                "rss_require_region_keyword": True,
            }
        ),
    )
    xml = """<?xml version="1.0"?><rss version="2.0"><channel>
      <item><title>Москва событие</title><link>https://m.ru/e</link><description>Столица</description></item>
    </channel></rss>"""
    mock_resp = MagicMock(status_code=200, content=xml.encode())
    inner = MagicMock()
    inner.get.return_value = mock_resp
    cm = MagicMock()
    cm.__enter__.return_value = inner
    cm.__exit__.return_value = None

    with patch("app.services.ingest.rss.httpx.Client", MagicMock(return_value=cm)):
        stats = ingest_rss_izhevsk(db_session)

    assert stats["rss_skipped"] >= 1
    assert stats["rss_upserted"] == 0


def test_run_izhevsk_ingest_respects_disabled(db_session: Session, monkeypatch) -> None:
    monkeypatch.setattr(settings, "ingest_enabled", False)
    out = run_izhevsk_ingest(db_session, force=False)
    assert out.get("skipped") == 1


def _adm_calendar_html() -> str:
    return """<!DOCTYPE html><html><body>
<div class="hide" id="data">
<span id="e_999001">Концерт тест ADM</span><div id="i_999001"><img src="/res_ru/x.jpg" width="50"><img src="/res_ru/y.png" width="50"></div>
</div>
<script>
var evData = [
                    {
                        title: $('span#e_'+999001),
                        start: '15.06.2099 18:00',
                        end: '15.06.2099 21:00',
                        newid: '999001',
                        img: $('div#i_'+999001)
                    },
];
</script>
</body></html>"""


def _adm_detail_html() -> str:
    return """
    <div class="eventWrap">
    <div class="mb-3"><img src="/res_ru/detail1.jpg"><img src="/res_ru/detail2.jpg"></div>
    <div class="mb-3"><b>Адрес мероприятия</b>&nbsp;ул. Тестовая, 1 (ДК)<br>
    <b>Мероприятие будет проходить</b>&nbsp;<b>с</b>&nbsp;15.06.2099 18:00&nbsp;<b>до</b>&nbsp;15.06.2099 21:00
    </div>
    <div style="margin:10px -16px;background:#eef4fc;height:20px;"></div>
    <div class="mb-3"><p>Описание мероприятия из карточки.</p></div>
    <div style="margin:10px -16px;background:#eef4fc;height:20px;"></div>
    <div class="mb-3"><b>О событии</b>&nbsp;<a href="#">ссылка</a></div>
    </div>
    """


def test_adm_izh_ingest_without_details(db_session: Session, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.ingest.adm_izh.settings",
        settings.model_copy(
            update={
                "adm_izh_fetch_details": False,
                "adm_izh_max_events": 50,
            }
        ),
    )
    cal = _adm_calendar_html()
    mock_resp = MagicMock(status_code=200, text=cal)
    inner = MagicMock()
    inner.get.return_value = mock_resp
    cm = MagicMock()
    cm.__enter__.return_value = inner
    cm.__exit__.return_value = None

    with patch("app.services.ingest.adm_izh.httpx.Client", MagicMock(return_value=cm)):
        stats = ingest_adm_izh(db_session)

    assert stats["adm_izh_upserted"] == 1
    assert stats.get("adm_izh_detail_fetched", 0) == 0
    ev = db_session.query(Event).filter(Event.ingest_key == "adm_izh:999001").one()
    assert "Концерт тест ADM" in ev.name
    assert ev.slug == "adm-izh-999001"
    assert settings.default_event_place[:20] in (ev.place or "")
    assert ev.img_url and "res_ru/x.jpg" in ev.img_url
    urls = json.loads(ev.image_urls_json or "[]")
    assert len(urls) == 2
    assert any("x.jpg" in u for u in urls)
    assert any("y.png" in u for u in urls)


def test_adm_izh_ingest_with_details(db_session: Session, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.ingest.adm_izh.settings",
        settings.model_copy(
            update={
                "adm_izh_fetch_details": True,
                "adm_izh_max_detail_fetches": 5,
                "adm_izh_max_events": 50,
                "adm_izh_detail_delay_sec": 0.0,
            }
        ),
    )
    cal = _adm_calendar_html()
    detail = _adm_detail_html()

    def fake_get(url: str, **_kwargs):
        r = MagicMock()
        r.status_code = 200
        if "calendar-calendar" in url:
            r.text = cal
        else:
            r.text = detail
        return r

    inner = MagicMock()
    inner.get.side_effect = fake_get
    cm = MagicMock()
    cm.__enter__.return_value = inner
    cm.__exit__.return_value = None

    with patch("app.services.ingest.adm_izh.httpx.Client", MagicMock(return_value=cm)):
        stats = ingest_adm_izh(db_session)

    assert stats["adm_izh_detail_fetched"] == 1
    ev = db_session.query(Event).filter(Event.ingest_key == "adm_izh:999001").one()
    assert "Тестовая" in (ev.place or "")
    assert "Удмурт" in (ev.place or "")
    assert ev.description and "Описание мероприятия" in ev.description
    urls = json.loads(ev.image_urls_json or "[]")
    assert len(urls) >= 3
    assert any("detail1" in u for u in urls)
