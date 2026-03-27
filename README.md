# Technostrelka API (FastAPI + PostgreSQL)

Бэкенд REST API для приложения городских событий: аутентификация (JWT), события, избранное, отзывы, загрузка файлов, прогресс пользователя, заглушка для FCM и прокси к LLM (ключ только на сервере).

## Требования

- [Docker Engine](https://docs.docker.com/engine/install/) и [Docker Compose](https://docs.docker.com/compose/install/) v2 (в Windows обычно входит в **Docker Desktop**).

Проверка:

```bash
docker version
docker compose version
```

## Быстрый старт (только API и база)

Из корня репозитория (где лежат `Dockerfile` и `docker-compose.yml`):

```bash
docker compose up --build -d
```

Подождите, пока контейнер `db` станет healthy (Compose выставляет `depends_on: condition: service_healthy` для сервиса `api`).

- **HTTP API:** [http://localhost:8000](http://localhost:8000)
- **OpenAPI (Swagger):** [http://localhost:8000/docs](http://localhost:8000/docs)
- **Проверка живости:** [http://localhost:8000/health](http://localhost:8000/health)

Остановка и удаление контейнеров (том с данными Postgres сохраняется):

```bash
docker compose down
```

Полный сброс данных Postgres (удалит том с БД):

```bash
docker compose down -v
```

При следующем `up` скрипт `docker/init-db.sql` снова создаст базу **`technostrelka_test`** (нужна для pytest на хосте или отдельным сервисом).

## Что поднимает Compose

| Сервис | Назначение |
|--------|------------|
| `db` | PostgreSQL 16 (`technostrelka` + при первом старте тома — `technostrelka_test`) |
| `api` | Uvicorn, приложение `app.main:app`, порт **8000** |

Файлы загрузок (аватары, фото отзывов) хранятся в именованном томе **`uploads_data`**, внутри контейнера путь: `/app/uploads`. Статика отдаётся по префиксу **`/static/`** (см. `PUBLIC_BASE_URL`).

## Переменные окружения

Compose задаёт разумные значения по умолчанию. Переопределить можно через файл **`.env`** в корне (см. также `.env.example`).

| Переменная | Описание |
|------------|----------|
| `DATABASE_URL` | Строка подключения SQLAlchemy/psycopg2, например `postgresql://postgres:postgres@db:5432/technostrelka` внутри Compose |
| `SECRET_KEY` | Секрет подписи JWT (в продакшене — длинная случайная строка) |
| `ADMIN_API_KEY` | Ключ для `X-Admin-Key` при создании событий и категорий |
| `PUBLIC_BASE_URL` | Базовый URL для ссылок на загруженные файлы (с хоста: `http://localhost:8000`) |
| `UPLOAD_DIR` | Каталог загрузок (в образе по умолчанию `/app/uploads`) |
| `OPENAI_API_KEY` | Для живых ответов ассистента (`/api/v1/assistant/...`); без ключа — 503 |

Пример локального `.env` для разработки не в Docker (Postgres на `localhost`):

```env
DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:5432/technostrelka
SECRET_KEY=local-dev-secret
ADMIN_API_KEY=local-admin
PUBLIC_BASE_URL=http://localhost:8000
```

## Тесты (happy path)

Интеграционные тесты ходят в **PostgreSQL** и ожидают базу **`technostrelka_test`** (её создаёт `docker/init-db.sql` при **первом** создании тома БД).

### Вариант A: только Postgres в Docker, pytest на машине

1. Поднимите базу:

   ```bash
   docker compose up -d db
   ```

2. Убедитесь, что база `technostrelka_test` существует (после первого `up` с пустым томом — создаётся автоматически). Если том уже был без этого скрипта, создайте БД вручную один раз:

   ```bash
   docker compose exec db psql -U postgres -c "CREATE DATABASE technostrelka_test;"
   ```

3. Установите зависимости и запустите тесты из корня проекта:

   ```bash
   pip install -r requirements.txt -r requirements-dev.txt
   pytest tests -v
   ```

По умолчанию `tests/conftest.py` подключается к `postgresql://postgres:postgres@127.0.0.1:5432/technostrelka_test`. При необходимости задайте `DATABASE_URL` до запуска pytest.

### Вариант B: pytest внутри Docker (тот же репозиторий, общая сеть с `db`)

Compose поднимет сервис `db`, если он ещё не запущен (из-за `depends_on` у сервиса `pytest`):

```bash
docker compose --profile test run --rm pytest
```

Дождитесь готовности Postgres (первый старт может занять несколько секунд). При ошибке подключения выполните `docker compose up -d db`, подождите healthcheck и повторите команду.

Сервис **`pytest`** в `docker-compose.yml` использует `DATABASE_URL=...@db:5432/technostrelka_test`, монтирует `./tests` в контейнер и выполняет `pytest tests/ -v`. После изменений в `app/` пересоберите образ: `docker compose build pytest` или `docker compose build`.

## Сборка образа без Compose

```bash
docker build -t technostrelka-api .
docker run --rm -p 8000:8000 \
  -e DATABASE_URL=postgresql://user:pass@host:5432/dbname \
  technostrelka-api
```

## Полезные команды

Логи API:

```bash
docker compose logs -f api
```

Вход в shell контейнера API:

```bash
docker compose exec api sh
```

Пересборка после изменений кода:

```bash
docker compose up --build -d api
```
