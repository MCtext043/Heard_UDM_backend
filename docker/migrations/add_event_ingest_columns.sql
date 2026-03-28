-- Добавление колонок для импорта афиши (если таблица events уже существовала без них).
ALTER TABLE events ADD COLUMN IF NOT EXISTS ingest_key VARCHAR(160);
ALTER TABLE events ADD COLUMN IF NOT EXISTS last_ingested_at TIMESTAMP WITH TIME ZONE;

CREATE UNIQUE INDEX IF NOT EXISTS uq_events_ingest_key ON events (ingest_key)
    WHERE ingest_key IS NOT NULL;
