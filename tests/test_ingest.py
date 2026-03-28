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
from app.services.ingest.afisha_goroda import ingest_afisha_goroda
from app.services.ingest.dates_ru import parse_russian_date_span
from app.services.ingest.rss import ingest_rss_izhevsk
from app.services.ingest.runner import run_izhevsk_ingest
from app.services.ingest.visit_udmurtia import ingest_visit_udmurtia
from app.services.ingest.yandex_afisha import ingest_yandex_afisha
from app.services.event_completeness import is_event_complete, purge_incomplete_events


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


def test_parse_russian_date_span() -> None:
    s, e = parse_russian_date_span("15 июля 2030")
    assert s == e and s.month == 7 and s.day == 15
    s2, e2 = parse_russian_date_span("12 июня 2030 - 13 июня 2030")
    assert s2.day == 12 and e2.day == 13 and e2.month == 6


def test_visit_udm_ingest(db_session: Session, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.ingest.visit_udmurtia.settings",
        settings.model_copy(
            update={
                "visit_udm_enabled": True,
                "visit_udm_max_list_links": 10,
                "visit_udm_max_detail_fetches": 5,
                "visit_udm_detail_delay_sec": 0.0,
                "visit_udm_verify_ssl": True,
            }
        ),
    )
    cal = """<html><body>
    <a class="announcement" href="/kalendar-sobytij/test-future-fest/"></a>
    </body></html>"""
    det = """<html><body>
    <div class="cover__title">Фестиваль тест Visit</div>
    <div class="cover__date-label">15 августа 2030</div>
    <div class="section container"><div class="row justify-content-center"><div class="col-md-8">
    <p>Очень длинное осмысленное описание для фильтра минимальной длины сорок символов текста.</p>
    </div></div></div>
    <div class="contacts__row row"><div class="col-md-6">
    <div class="contacts__key">Место проведения</div>
    <div class="contacts__value"> г. Ижевск, ул. Пушкинская, 1</div>
    </div></div>
    <img class="cover__img lazy-load" data-src="/upload/iblock/z.jpg" alt="">
    </body></html>"""

    def fake_get(url: str, **_kwargs):
        r = MagicMock()
        r.status_code = 200
        r.text = det if "test-future-fest" in url else cal
        return r

    inner = MagicMock()
    inner.get.side_effect = fake_get
    cm = MagicMock()
    cm.__enter__.return_value = inner
    cm.__exit__.return_value = None

    with patch("app.services.ingest.visit_udmurtia.httpx.Client", MagicMock(return_value=cm)):
        stats = ingest_visit_udmurtia(db_session)

    assert stats["visit_udm_upserted"] == 1
    ev = db_session.query(Event).filter(Event.ingest_key == "visit_udm:test-future-fest").one()
    assert "Visit" in ev.name
    assert "Пушкинская" in (ev.place or "")
    assert ev.img_url


def test_afisha_goroda_ingest(db_session: Session, monkeypatch) -> None:
    next_list = {
        "props": {"pageProps": {"events": [{"slug": "test-show-2030", "title": "Тест шоу"}]}}
    }
    next_detail = {
        "props": {
            "pageProps": {
                "event": {
                    "title": "Тест шоу Афиша",
                    "slug": "test-show-2030",
                    "description": "Подробное описание концерта для фильтра сорок плюс символов текста.",
                    "image": {"url": "https://izh.afishagoroda.ru/media/x.jpg"},
                    "place": {"title": "ДК «Металлург»", "address": "г. Ижевск, ул. Карла Маркса, 246"},
                    "sessions": [{"startTime": "2030-08-20T19:00:00+04:00"}],
                }
            }
        }
    }
    list_html = (
        f'<html><script id="__NEXT_DATA__" type="application/json">{json.dumps(next_list)}</script></html>'
    )
    det_html = (
        f'<html><script id="__NEXT_DATA__" type="application/json">{json.dumps(next_detail)}</script></html>'
    )

    monkeypatch.setattr(
        "app.services.ingest.afisha_goroda.settings",
        settings.model_copy(
            update={
                "afisha_goroda_enabled": True,
                "afisha_goroda_max_slugs": 10,
                "afisha_goroda_max_detail_fetches": 5,
                "afisha_goroda_detail_delay_sec": 0.0,
                "afisha_goroda_verify_ssl": True,
            }
        ),
    )

    def fake_get(url: str, **_kwargs):
        r = MagicMock()
        r.status_code = 200
        r.text = det_html if "test-show-2030" in url else list_html
        return r

    inner = MagicMock()
    inner.get.side_effect = fake_get
    cm = MagicMock()
    cm.__enter__.return_value = inner
    cm.__exit__.return_value = None

    with patch("app.services.ingest.afisha_goroda.httpx.Client", MagicMock(return_value=cm)):
        stats = ingest_afisha_goroda(db_session)

    assert stats["afisha_upserted"] == 1
    ev = db_session.query(Event).filter(Event.ingest_key == "afisha_goroda:test-show-2030").one()
    assert "Афиша" in ev.name
    assert "Карла Маркса" in (ev.place or "")


def test_is_event_complete_and_purge(db_session: Session, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.event_completeness.settings",
        settings.model_copy(
            update={
                "event_completeness_enabled": True,
                "event_completeness_require_extras": False,
                "event_completeness_min_gallery_urls": 1,
                "event_completeness_min_description_len": 30,
                "event_completeness_reject_ticket_marketing": True,
            }
        ),
    )
    complete = Event(
        ingest_key="test:complete-one",
        name="Полное событие",
        slug="complete-one",
        img_url="https://ex/img.jpg",
        image_urls_json='["https://ex/img.jpg"]',
        description="Достаточно подробное описание мероприятия для отображения в ленте.",
        date_caption="01.06.2030",
        place="ДК «Тест», ул. Ленина, 10, Ижевск",
        url="https://example.com/event/1",
        type="Искусство",
        review_bucket="Other",
    )
    incomplete = Event(
        ingest_key="test:bad-one",
        name="Пустое",
        slug="bad-one",
        img_url=None,
        description=None,
        date_caption=None,
        place=None,
        url=None,
        type="Искусство",
        review_bucket="Other",
    )
    db_session.add_all([complete, incomplete])
    db_session.commit()
    assert is_event_complete(complete) is True
    assert is_event_complete(incomplete) is False
    deleted = purge_incomplete_events(db_session)
    assert deleted >= 1
    assert db_session.query(Event).filter(Event.slug == "complete-one").count() == 1
    assert db_session.query(Event).filter(Event.slug == "bad-one").count() == 0


def test_yandex_afisha_ingest(db_session: Session, monkeypatch) -> None:
    hub = '<html><body><a href="/izhevsk/concert/ya-test-one">x</a></body></html>'
    detail = """<html><head>
<meta property="og:title" content="Bilet Test 05.05.2030 DK - Yandex Afisha" />
<meta property="og:description" content="Тест Яндекс, ДК «Проверка», купить билеты на концерт в Ижевске, 05.05.2030." />
<meta property="og:image" content="https://avatars.mds.yandex.net/get-afishanew/1/abcd0123ef/1200x628_wmark.jpg" />
</head></html>"""

    monkeypatch.setattr(
        "app.services.ingest.yandex_afisha.settings",
        settings.model_copy(
            update={
                "yandex_afisha_enabled": True,
                "yandex_afisha_city_slug": "izhevsk",
                "yandex_afisha_hub_paths": "/izhevsk/main",
                "yandex_afisha_max_events": 10,
                "yandex_afisha_max_detail_fetches": 5,
                "yandex_afisha_detail_delay_sec": 0.0,
                "yandex_afisha_hub_delay_sec": 0.0,
                "yandex_afisha_verify_ssl": True,
            }
        ),
    )

    def fake_get(url: str, **_kwargs):
        r = MagicMock()
        r.status_code = 200
        r.text = detail if "ya-test-one" in url else hub
        return r

    inner = MagicMock()
    inner.get.side_effect = fake_get
    cm = MagicMock()
    cm.__enter__.return_value = inner
    cm.__exit__.return_value = None

    with patch("app.services.ingest.yandex_afisha.httpx.Client", MagicMock(return_value=cm)):
        stats = ingest_yandex_afisha(db_session)

    assert stats["yandex_afisha_upserted"] == 1
    ev = db_session.query(Event).filter(Event.ingest_key == "yandex_afisha:izhevsk:concert:ya-test-one").one()
    assert "Концерт" in ev.name and "Тест Яндекс" in ev.name
    assert ev.img_url
    assert ev.place and "Проверка" in ev.place
