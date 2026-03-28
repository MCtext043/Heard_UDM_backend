-- Галерея URL изображений (JSON-массив строк).
ALTER TABLE events ADD COLUMN IF NOT EXISTS image_urls_json TEXT;
