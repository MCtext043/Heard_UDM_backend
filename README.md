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

## Доступ с телефона (та же Wi‑Fi сеть)

По умолчанию API на порту **8000** и `PUBLIC_BASE_URL=http://localhost:8000` — с физического телефона `localhost` указывает на сам телефон, а абсолютные ссылки на картинки будут неверными.

Файл **`docker-compose.mobile.yml`** подключает отдельную Docker-сеть **`technostrelka_lan`** и публикует API на хосте как **`http://<IP_вашего_ПК>:8888`** (внутри контейнера по-прежнему порт 8000).

1. Узнайте IPv4 компьютера в **той же сети, что и телефон** (Windows: `ipconfig`). Берите адрес у **«Беспроводная сеть»** или Ethernet к роутеру (часто `192.168.x.x`, шлюз — ваш роутер). **Не используйте** адреса виртуальных адаптеров (VMware `192.168.75.x` / `192.168.66.x`, WSL/Hyper-V `192.168.16.x`, NAT `172.16.x.x`) и **не** адрес VPN вроде Radmin (`26.x.x.x`), если телефон подключён к домашнему Wi‑Fi, а не к той же VPN.
2. В **`.env`** в корне проекта задайте тот же хост и порт **8888**:

   ```env
   MOBILE_PUBLIC_BASE_URL=http://192.168.x.x:8888
   ```

3. Поднимите стек:

   ```bash
   docker compose -f docker-compose.yml -f docker-compose.mobile.yml up --build -d
   ```

4. В мобильном приложении укажите базовый URL API: **`http://192.168.x.x:8888`** (те же хост и порт, что в `MOBILE_PUBLIC_BASE_URL`). Проверка: в браузере телефона откройте `http://192.168.x.x:8888/health` — должен вернуться JSON `{"status":"ok"}`.

Если запросы не доходят, разрешите входящие подключения на порт **8888** в брандмауэре Windows.

Подсказки по эмуляторам: **Android Emulator** — `http://10.0.2.2:8888` (и такой же `MOBILE_PUBLIC_BASE_URL`, если ответы с картинками должны открываться с эмулятора). **iOS Simulator** на Mac часто достаточно `http://127.0.0.1:8888`.

Опционально **`CORS_ORIGINS`** в `.env`: через запятую список origin для веб-отладки; по умолчанию в mobile-файле задано `*` (см. `app/main.py`).

Живые pytest с хоста при таком подъёме: `LIVE_BACKEND_URL=http://127.0.0.1:8888 pytest tests/integration -v -m live`.

## Что поднимает Compose

| Сервис | Назначение |
|--------|------------|
| `db` | PostgreSQL 16 (`technostrelka` + при первом старте тома — `technostrelka_test`) |
| `api` | Uvicorn, приложение `app.main:app`, порт **8000** |

Файлы загрузок (аватары, фото отзывов) хранятся в именованном томе **`uploads_data`**, внутри контейнера путь: `/app/uploads`. Статика отдаётся по префиксу **`/static/`** (см. `PUBLIC_BASE_URL`).

## Импорт афиши (Ижевск и Удмуртия)

Фоновый планировщик (**APScheduler**) периодически подтягивает события (порядок прогона):

1. **RSS** (опционально) — `IZHEVSK_RSS_FEED_URLS`; фильтр по региону (`RSS_REQUIRE_REGION_KEYWORD`). **`ingest_key`**: `rss:<hash>`.
2. **[Visit Udmurtia](https://visitudmurtia.org/kalendar-sobytij/)** — со страницы календаря собираются ссылки на карточки; для каждой карточки читаются **заголовок**, **дата** (русский текст), **описание**, блок **«Место проведения»**, **обложка и картинки** с `/upload/`. **`ingest_key`**: `visit_udm:<slug>`.
3. **[Афиша Города (Ижевск)](https://izh.afishagoroda.ru/events)** — разбор **Next.js `__NEXT_DATA__`**: список slug’ов и детальная карточка (описание, площадка, сеансы с датами, изображения). **`ingest_key`**: `afisha_goroda:<slug>`. На части серверов TLS к этому хосту падает — в Docker по умолчанию `AFISHA_GORODA_VERIFY_SSL=false`.
4. **[Календарь adm.izh.ru](https://adm.izh.ru/i/calendar-calendar)** — как раньше: календарь + карточки `calendar-viewevent`. **`ingest_key`**: `adm_izh:<id>`.
5. **[Яндекс.Афиша](https://afisha.yandex.ru/izhevsk/main)** — ссылки на карточки собираются с хабов города (`YANDEX_AFISHA_HUB_PATHS`), на каждой карточке читаются **Open Graph** (`og:title`, `og:description`, `og:image`). **`ingest_key`**: `yandex_afisha:<город>:<рубрика>:<slug>`.

**Очистка БД:** после каждого прогона импорта (если `INGEST_PURGE_INCOMPLETE_AFTER_RUN=true`) удаляются события без полного набора полей: имя, slug, обложка, описание, дата (подпись), место, внешняя ссылка, тип, `review_bucket`, минимум одна картинка в галерее. Опционально `EVENT_COMPLETENESS_REQUIRE_EXTRAS=true` — дополнительно age, rating, schedule, status. Ручной вызов: `POST /api/v1/admin/events/purge-incomplete`.

**Отбор «сходить сейчас» и качество контента** (включается `INGEST_STRICT_EVENT_QUALITY=true` по умолчанию):

- дата окончания (или однодневная дата) **не раньше «сегодня»** в зоне `INGEST_TIMEZONE` (по умолчанию `Europe/Samara`);
- **описание** не короче `INGEST_MIN_DESCRIPTION_LEN` символов;
- минимум **`INGEST_MIN_IMAGES_PER_EVENT`** картинок (URL);
- **адрес / площадка** не «голый» город: нужны улица, ДК/ТРЦ/venue в «ёлочках», населённый пункт с подробностью и т.п. (эвристика в `app/services/ingest/quality.py`).

Исключение из автоматического парсинга: **Министерство по туризму УР** ([mintur.udmurt.ru](https://mintur.udmurt.ru)) публикует [событийный календарь](https://mintur.udmurt.ru/informatsiya-dlya-turistov/sobytiynyy-kalendar-turisticheskikh-meropriyatiy/) в основном **как PDF**, без стабильной HTML-афиши по отдельным мероприятиям. Пересечение по содержанию закрывается **Visit Udmurtia** и другими источниками. При появлении открытого API или RSS у Минтур — можно добавить отдельный модуль.

У импортированных строк заполняется **`ingest_key`** и галерея в **`image_urls_json`** (в API — `image_urls`).

| Переменная | Описание |
|------------|----------|
| `INGEST_ENABLED` | `true` / `false` — включить планировщик (в `docker-compose` для `api` уже `true`) |
| `INGEST_INTERVAL_MINUTES` | Интервал, не меньше 15 минут |
| `INGEST_HTTP_TIMEOUT` | Таймаут HTTP для импорта |
| `INGEST_TIMEZONE` | Зона для проверки «событие ещё не прошло» (например `Europe/Samara`) |
| `INGEST_STRICT_EVENT_QUALITY` | Строгий фильтр: описание, фото, адрес, дата |
| `INGEST_MIN_DESCRIPTION_LEN` | Мин. длина описания (символы) |
| `INGEST_MIN_IMAGES_PER_EVENT` | Мин. число URL изображений |
| `VISIT_UDM_*` | Лимиты и `VISIT_UDM_VERIFY_SSL` для visitudmurtia.org |
| `AFISHA_GORODA_*` | Лимиты и `AFISHA_GORODA_VERIFY_SSL` для izh.afishagoroda.ru |
| `YANDEX_AFISHA_*` | Город (`YANDEX_AFISHA_CITY_SLUG`), хабы, лимиты, `YANDEX_AFISHA_VERIFY_SSL` |
| `INGEST_PURGE_INCOMPLETE_AFTER_RUN` | После импорта удалять неполные события |
| `EVENT_COMPLETENESS_*` | Включение очистки и опционально age/rating/schedule/status |
| `DEFAULT_EVENT_PLACE` | Адрес по умолчанию, если с сайта адрес не извлечён |
| `IZHEVSK_RSS_FEED_URLS` | Через запятую URL RSS |
| `RSS_REQUIRE_REGION_KEYWORD` | Фильтр по региону в тексте RSS |
| `ADM_IZH_FETCH_DETAILS` | Ходить на карточку события за адресом, текстом и фото |
| `ADM_IZH_MAX_DETAIL_FETCHES` | Лимит карточек за прогон |
| `ADM_IZH_MAX_EVENTS` | Лимит событий из календаря за прогон |
| `ADM_IZH_MAX_IMAGES_PER_EVENT` | Максимум URL в галерее на одно событие |
| `ADM_IZH_DETAIL_DELAY_SEC` | Пауза между запросами карточек |

Ручной запуск импорта (нужен **`X-Admin-Key`**): `POST /api/v1/admin/ingest/run`.

Миграции для **уже существующего** тома Postgres (после обновления кода SQLAlchemy не добавляет колонки сама). Если Swagger/`GET /api/v1/events` даёт **500** и в логах `api` видно `column events.image_urls_json does not exist`, выполните из корня репозитория:

```bash
docker compose exec -T db psql -U postgres -d technostrelka -f - < docker/migrations/add_event_ingest_columns.sql
docker compose exec -T db psql -U postgres -d technostrelka -f - < docker/migrations/add_event_image_urls_json.sql
```

На Windows PowerShell, если перенаправление не сработало:

```powershell
Get-Content docker/migrations/add_event_image_urls_json.sql | docker compose exec -T db psql -U postgres -d technostrelka
```

Файлы: `docker/migrations/add_event_ingest_columns.sql`, `docker/migrations/add_event_image_urls_json.sql`.

## Переменные окружения

Compose задаёт разумные значения по умолчанию. Переопределить можно через файл **`.env`** в корне (см. также `.env.example`).

| Переменная | Описание |
|------------|----------|
| `DATABASE_URL` | Строка подключения SQLAlchemy/psycopg2, например `postgresql://postgres:postgres@db:5432/technostrelka` внутри Compose |
| `SECRET_KEY` | Секрет подписи JWT (в продакшене — длинная случайная строка) |
| `ADMIN_API_KEY` | Ключ для `X-Admin-Key` при создании событий и категорий |
| `PUBLIC_BASE_URL` | Базовый URL для ссылок на загруженные файлы (с хоста: `http://localhost:8000`) |
| `MOBILE_PUBLIC_BASE_URL` | Только с `docker-compose.mobile.yml`: тот же URL, что вводите в приложении (`http://<LAN>:8888`), чтобы ссылки `/static/...` были с телефона открываемы |
| `CORS_ORIGINS` | `*` или список origin через запятую (см. `CORSMiddleware` в `app/main.py`) |
| `UPLOAD_DIR` | Каталог загрузок (в образе по умолчанию `/app/uploads`) |
| `ASSISTANT_PROVIDER` | Провайдер ассистента: `rules` (без LLM) или `llamacpp_http` (локальная модель через llama.cpp server) |
| `ASSISTANT_BASE_URL` | Базовый URL OpenAI-compatible сервера (например `http://llm:8080/v1` в Compose) |
| `ASSISTANT_MODEL` | Имя модели (для логов/совместимости, llama.cpp может игнорировать) |

Пример локального `.env` для разработки не в Docker (Postgres на `localhost`):

```env
DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:5432/technostrelka
SECRET_KEY=local-dev-secret
ADMIN_API_KEY=local-admin
PUBLIC_BASE_URL=http://localhost:8000
```

## Ассистент без внешних AI сервисов (бесплатная модель)

Мы не меняем эндпоинты мобильного приложения:
- `POST /api/v1/assistant/chat`
- `POST /api/v1/assistant/route-quiz`

Варианты:
- **`ASSISTANT_PROVIDER=rules`**: всегда работает, не требует модели (ответы детерминированные, с контекстом из БД).
- **`ASSISTANT_PROVIDER=llamacpp_http`**: бесплатная локальная модель через **llama.cpp server** (OpenAI-compatible).

### Быстрый запуск локальной модели через Docker Compose

1. Скачайте GGUF модель (бесплатно). Рекомендация: **Qwen2.5-0.5B-Instruct (Q4_K_M)**:
   - файл: `qwen2.5-0.5b-instruct-q4_k_m.gguf`
   - положите в `./models/`
2. Запустите LLM сервис:

```bash
docker compose --profile llm up -d llm
```

3. В `.env` включите:

```env
ASSISTANT_PROVIDER=llamacpp_http
ASSISTANT_BASE_URL=http://llm:8080/v1
```

## Тесты (happy path)

Интеграционные тесты ходят в **PostgreSQL** и ожидают базу **`technostrelka_test`** (её создаёт `docker/init-db.sql` при **первом** создании тома БД).

Отдельные модули: `tests/test_assistant.py` (ИИ с моком GigaChat-прокси), `tests/test_ingest.py` (RSS/adm.izh с моком HTTP), `tests/test_happy_path.py` (сквозной сценарий).

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

Обычный прогон `pytest tests` **не заходит** в каталог `tests/integration` (см. `norecursedirs` в `pytest.ini`), чтобы не дергать живой API и внешние сервисы при каждом запуске.

### Проверка реально запущенного API (без моков)

Нужен отвечающий бэкенд (локально или Docker). По умолчанию тесты бьют в `http://127.0.0.1:8000`.

```bash
pytest tests/integration -v -m live
```

Переменные окружения:

- `LIVE_BACKEND_URL` — базовый URL API.
- `LIVE_ADMIN_API_KEY` — то же значение, что `X-Admin-Key` / `ADMIN_API_KEY` на сервере (в `docker-compose.yml` для `api` задано `docker-admin-key`), иначе тесты с админскими эндпоинтами пропускаются.
- `LIVE_ASSISTANT_STRICT=1` — строже проверять ответы чата (см. `tests/integration/test_live_backend.py`).

Из корня репозитория, когда подняты `db` и `api`:

```bash
docker compose --profile live run --rm live-pytest
```

Контейнер `live-pytest` ходит на `http://api:8000` и ждёт `service_healthy` у `api`.

### Вариант B: pytest внутри Docker (тот же репозиторий, общая сеть с `db`)

Compose поднимет сервис `db`, если он ещё не запущен (из-за `depends_on` у сервиса `pytest`):

```bash
docker compose --profile test run --rm pytest
```

Дождитесь готовности Postgres (первый старт может занять несколько секунд). При ошибке подключения выполните `docker compose up -d db`, подождите healthcheck и повторите команду.

Сервис **`pytest`** в `docker-compose.yml` использует `DATABASE_URL=...@db:5432/technostrelka_test`, монтирует `./tests` в контейнер и выполняет `pytest tests/ -v` (без `tests/integration`). Живую проверку API см. профиль **`live`** и сервис **`live-pytest`** выше. После изменений в `app/` пересоберите образ: `docker compose build pytest` или `docker compose build`.

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
