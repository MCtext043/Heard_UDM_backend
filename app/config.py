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

    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_chat_model: str = "gpt-4o-mini"

    # Тот же прокси, что в SmartWallet (POST JSON как у themc в routers/assistant.py).
    gigachat_proxy_url: str = "https://derendyaev.ru/api/gigachat/message"
    gigachat_model: str = "GigaChat:latest"
    gigachat_max_tokens: int = 256
    gigachat_timeout: float = 30.0

    admin_api_key: str = ""

    # Периодический импорт (adm.izh.ru + опционально RSS).
    ingest_enabled: bool = False  # в продакшене задайте INGEST_ENABLED=true
    ingest_interval_minutes: int = 360
    ingest_http_timeout: float = 45.0
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


settings = Settings()
