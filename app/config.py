from zoneinfo import ZoneInfo

from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql://postgres:postgres@localhost:5432/technostrelka"
    secret_key: str = "dev-secret-change-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24 * 7

    upload_dir: str = "uploads"
    public_base_url: str = "http://localhost:8000"
    # Для мобильного клиента / отладки в браузере: "*" или список origin через запятую.
    cors_origins: str = "*"

    # --- Assistant / LLM (no external AI services required) ---
    # Provider:
    # - "llamacpp_http": call a local OpenAI-compatible server (e.g. llama.cpp server) via HTTP
    # - "rules": deterministic fallback without any LLM
    assistant_provider: str = "rules"
    assistant_base_url: str = "http://localhost:8080/v1"
    assistant_model: str = "Qwen2.5-0.5B-Instruct"
    assistant_max_tokens: int = 256
    assistant_temperature: float = 0.6
    assistant_timeout: float = 45.0

    # Legacy (was used for external proxy). Kept for backward compatibility but no longer required.
    gigachat_proxy_url: str = ""
    gigachat_model: str = ""
    gigachat_max_tokens: int = 256
    gigachat_timeout: float = 30.0

    admin_api_key: str = ""

    # Периодический импорт (RSS + внешние афиши + adm.izh.ru).
    ingest_enabled: bool = False  # в продакшене задайте INGEST_ENABLED=true
    ingest_interval_minutes: int = 360
    ingest_http_timeout: float = 45.0
    # Часовой пояс для «актуальности» дат при отборе событий (Удмуртия / Самара).
    ingest_timezone: str = "Europe/Samara"
    # Строгий отбор: описание, адрес, даты — при false больше событий с фото попадает в БД.
    ingest_strict_event_quality: bool = False
    ingest_min_description_len: int = 20
    ingest_min_images_per_event: int = 1
    ingest_event_days_past_grace: int = 0
    default_event_place: str = "г. Ижевск, Удмуртская Респ., Россия"
    # Через запятую URL RSS (афиши учреждений Ижевска и т.п.).
    izhevsk_rss_feed_urls: str = ""
    rss_require_region_keyword: bool = True

    # Календарь событий администрации Ижевска (adm.izh.ru).
    adm_izh_base_url: str = "https://adm.izh.ru"
    adm_izh_calendar_path: str = "/i/calendar-calendar"
    adm_izh_timeout: float = 60.0
    adm_izh_fetch_details: bool = True
    adm_izh_max_detail_fetches: int = 200
    adm_izh_max_events: int = 2500
    adm_izh_detail_delay_sec: float = 0.1
    adm_izh_max_images_per_event: int = 30
    # Если в Docker/корпоративной сети падает TLS к adm.izh.ru — временно false (нежелательно в проде).
    adm_izh_verify_ssl: bool = True

    # Visit Udmurtia — календарь событий (HTML + карточки).
    visit_udm_enabled: bool = True
    visit_udm_base_url: str = "https://visitudmurtia.org"
    visit_udm_calendar_path: str = "/kalendar-sobytij/"
    visit_udm_max_list_links: int = 120
    visit_udm_max_detail_fetches: int = 80
    visit_udm_detail_delay_sec: float = 0.12
    visit_udm_verify_ssl: bool = True
    visit_udm_max_images_per_event: int = 20

    # Афиша Города Ижевск (Next.js).
    afisha_goroda_enabled: bool = True
    afisha_goroda_base_url: str = "https://izh.afishagoroda.ru"
    afisha_goroda_events_path: str = "/events"
    afisha_goroda_max_slugs: int = 150
    afisha_goroda_max_detail_fetches: int = 90
    afisha_goroda_detail_delay_sec: float = 0.12
    # У части окружений TLS к izh.afishagoroda.ru падает (как у adm.izh) — при необходимости false.
    afisha_goroda_verify_ssl: bool = False
    afisha_goroda_max_images_per_event: int = 24

    # Яндекс.Афиша (OG-теги на карточках; ссылки собираются с хабов города).
    yandex_afisha_enabled: bool = True
    yandex_afisha_base_url: str = "https://afisha.yandex.ru"
    yandex_afisha_city_slug: str = "izhevsk"
    # Пути хабов через запятую (относительно базы или полные URL).
    yandex_afisha_hub_paths: str = (
        "/izhevsk/main,/izhevsk/theatre,/izhevsk/events,/izhevsk/selections,"
        "/izhevsk/cinema,/izhevsk/sport,/izhevsk"
    )
    yandex_afisha_max_events: int = 200
    yandex_afisha_max_detail_fetches: int = 120
    yandex_afisha_detail_delay_sec: float = 0.12
    yandex_afisha_hub_delay_sec: float = 0.05
    yandex_afisha_verify_ssl: bool = False
    yandex_afisha_max_images_per_event: int = 8

    # После импорта удалять события без полного набора полей (см. event_completeness).
    ingest_purge_incomplete_after_run: bool = True
    event_completeness_enabled: bool = True
    # Если true — требуются также age, rating, schedule, status (часто пусты у импорта).
    event_completeness_require_extras: bool = False
    event_completeness_min_gallery_urls: int = 1
    event_completeness_min_description_len: int = 0
    # Требовать минимальную длину описания при сохранении (админка / валидация).
    event_completeness_require_description: bool = False
    # Отклонять названия в стиле «купить билеты», «билеты на …».
    event_completeness_reject_ticket_marketing: bool = False

    @computed_field  # type: ignore[prop-decorator]
    @property
    def ingest_tz(self) -> ZoneInfo:
        try:
            return ZoneInfo(self.ingest_timezone)
        except Exception:
            return ZoneInfo("UTC")


settings = Settings()
