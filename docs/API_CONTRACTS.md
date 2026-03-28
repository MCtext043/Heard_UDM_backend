# API-контракты Technostrelka (мобильный клиент)

Документ описывает, что клиент **отправляет** и **получает** при работе с бэкендом FastAPI. Актуальная интерактивная схема также доступна в **Swagger UI**: `{BASE_URL}/docs` (если включён в развёртывании).

## Базовый URL и версия

| Компонент | Значение |
|-----------|----------|
| Префикс REST API | `/api/v1` |
| Пример полного пути | `https://api.example.com/api/v1/events` |
| Проверка живости (вне префикса) | `GET /health` |
| Статические файлы (аватары, фото отзывов) | `GET {PUBLIC_BASE_URL}/static/...` |

Все тела запросов и ответов — **JSON**, кодировка UTF-8, заголовок запроса: `Content-Type: application/json` (кроме `multipart/form-data`, см. ниже).

Даты/время в JSON — строки в формате **ISO 8601** с часовым поясом (например `2025-03-27T12:00:00+00:00`).

Идентификаторы сущностей — **UUID** в каноническом строковом виде.

---

## CORS

Сервер настраивается переменной `CORS_ORIGINS`: `*` или список origin через запятую. Для мобильного **нативного** приложения CORS обычно не применяется (он для браузера).

---

## Ошибки

В типичных случаях FastAPI возвращает:

- **401** — `{"detail": "..."}` — нет/невалидный токен, неверный логин.
- **403** — `{"detail": "..."}` — нет прав (например админ без ключа).
- **404** — `{"detail": "Event not found"}` и т.п.
- **409** — `{"detail": "Email already registered"}`.
- **422** — тело валидации Pydantic: `{"detail": [ ... ]}`.

Текст `detail` на английском, как в коде сервера.

---

## Аутентификация пользователя (JWT)

После `POST /api/v1/auth/register` или `POST /api/v1/auth/login` клиент получает `access_token`.

**Заголовок для защищённых методов:**

```http
Authorization: Bearer <access_token>
```

Токен — JWT (алгоритм из конфига сервера, по умолчанию **HS256**). В payload поле `sub` — строка с UUID пользователя. Срок жизни задаётся на сервере (по умолчанию **7 суток** в минутах: `access_token_expire_minutes`).

**Выход:** `POST /api/v1/auth/logout` — сервер отвечает **204** без тела; токен нужно **удалить на клиенте** (серверный blacklist не реализован).

---

## Админ-доступ (не для обычного приложения)

Эндпоинты с пометкой **Admin** требуют заголовок:

```http
X-Admin-Key: <ADMIN_API_KEY>
```

Если `ADMIN_API_KEY` на сервере пустой, такие методы вернут **403** с пояснением, что админ API отключён.

---

# Эндпоинты

Ниже пути указаны **относительно** `/api/v1`, если не сказано иное.

---

## 1. Здоровье сервиса

### `GET /health`

**Аутентификация:** не требуется.

**Ответ 200:**

```json
{ "status": "ok" }
```

---

## 2. Auth — `/auth`

### `POST /auth/register`

**Тело (JSON):**

| Поле | Тип | Ограничения |
|------|-----|-------------|
| `email` | string | валидный email |
| `password` | string | 6–128 символов |
| `username` | string | 1–120 символов |

**Ответ 200:**

| Поле | Тип | Описание |
|------|-----|----------|
| `access_token` | string | JWT |
| `token_type` | string | всегда `"bearer"` |

**409** — email уже занят.

---

### `POST /auth/login`

**Тело (JSON):**

| Поле | Тип | Ограничения |
|------|-----|-------------|
| `email` | string | email |
| `password` | string | 1–128 символов |

**Ответ 200:** как у `register` — `Token`.

**401** — неверная пара email/пароль.

---

### `POST /auth/logout`

**Аутентификация:** не обязательна (тело не используется).

**Ответ 204** — без тела.

---

## 3. Пользователь — `/users`

### `GET /users/me`

**Аутентификация:** Bearer.

**Ответ 200 — объект пользователя (`UserPublic`):**

| Поле | Тип | Описание |
|------|-----|----------|
| `id` | UUID | |
| `email` | string | |
| `username` | string | |
| `profile_image_url` | string \| null | абсолютный URL (часто `{PUBLIC_BASE_URL}/static/...`) |
| `category_user` | string \| null | интересы/категория |
| `post_text` | string | произвольный текст профиля |
| `post_name_text` | string | |
| `post_images` | string | |
| `created_at` | datetime | |

---

### `PATCH /users/me`

**Аутентификация:** Bearer.

**Тело (JSON):** все поля опциональны (частичное обновление):

| Поле | Тип | Ограничения |
|------|-----|-------------|
| `username` | string | max 120 |
| `category_user` | string | max 64 |
| `post_text` | string | |
| `post_name_text` | string | |
| `post_images` | string | |

**Ответ 200:** обновлённый `UserPublic`.

---

### `POST /users/me/avatar`

**Аутентификация:** Bearer.

**Тело:** `multipart/form-data`, одно поле файла:

| Поле | Тип | Описание |
|------|-----|----------|
| `file` | file | изображение; допустимые расширения обрабатываются на сервере (jpg, png, webp, gif и т.д.) |

**Ответ 200:** `UserPublic` с обновлённым `profile_image_url`.

---

### `GET /users/me/progress`

**Аутентификация:** Bearer.

**Ответ 200:**

| Поле | Тип |
|------|-----|
| `progress` | int |
| `score` | int |
| `last_updated` | datetime \| null |

---

### `POST /users/me/progress/increment`

**Аутентификация:** Bearer.

**Тело (JSON):**

| Поле | Тип | По умолчанию | Ограничения |
|------|-----|--------------|-------------|
| `delta` | int | 1 | 1–50 |
| `cap_at` | int | 100 | 1–100 |

Сервер увеличивает `progress` на `delta`, но не выше `cap_at`, увеличивает `score` на `delta`, обновляет `progress_last_updated`.

**Ответ 200:** объект как у `GET .../progress`.

---

### `POST /users/me/viewed-content`

**Аутентификация:** Bearer.

**Тело (JSON):**

| Поле | Тип | Обязательно | Ограничения |
|------|-----|-------------|-------------|
| `content_id` | string | да | max 256 |
| `content_type` | string | нет | max 64 |
| `is_completed` | bool | нет, default false | |

**Ответ 204** — без тела. Повтор с тем же `content_id` обновляет запись.

---

### `POST /users/me/device-tokens`

**Аутентификация:** Bearer.

**Тело (JSON):**

| Поле | Тип | Ограничения |
|------|-----|-------------|
| `token` | string | max 512 (push-токен устройства) |

**Ответ 204** — без тела (дубликаты по паре пользователь+токен не создаются).

---

## 4. Избранное — `/users/me/favorites`

### `GET /users/me/favorites`

**Аутентификация:** Bearer.

**Ответ 200:** массив **`EventOut`** (полная структура события, см. раздел «События»).

---

### `PUT /users/me/favorites/{event_id}`

**Аутентификация:** Bearer.

**Параметр пути:** `event_id` — UUID события.

**Тело:** нет.

**Ответ 204** — добавлено в избранное. **404** — события нет.

---

### `DELETE /users/me/favorites/{event_id}`

**Аутентификация:** Bearer.

**Ответ 204** — удалено из избранного (если записи не было, тоже успех без ошибки после текущей логики).

---

### `GET /users/me/favorites/status`

**Аутентификация:** Bearer.

**Query-параметры:** один или несколько `event_id` (список UUID). В HTTP это повторяющиеся ключи:

```http
GET /api/v1/users/me/favorites/status?event_ids=<uuid1>&event_ids=<uuid2>
```

**Ответ 200:**

```json
{
  "favorites": {
    "<uuid1>": true,
    "<uuid2>": false
  }
}
```

Ключи — **строки** UUID в том же порядке/наборе, что запрошены. Пустой список `event_ids` → `{"favorites": {}}`.

---

## 5. Каталог главной — `/home-categories`

### `GET /home-categories`

**Аутентификация:** не требуется.

**Ответ 200:** массив объектов:

| Поле | Тип |
|------|-----|
| `id` | UUID |
| `name` | string |
| `type` | string |
| `sort_order` | int |

Сортировка: `sort_order`, затем `name`.

---

### `POST /home-categories` — **Admin**

**Заголовок:** `X-Admin-Key`.

**Тело (JSON):**

| Поле | Тип | Ограничения |
|------|-----|-------------|
| `name` | string | max 120 |
| `type` | string | max 64 |
| `sort_order` | int | default 0 |

**Ответ 201:** объект категории как в GET.

---

## 6. События (афиша) — `/events`

### Объект ответа `EventOut`

Используется в списках, карточке события и в избранном.

| Поле | Тип | Описание |
|------|-----|----------|
| `id` | UUID | |
| `name` | string | |
| `slug` | string \| null | уникальный slug, может быть null |
| `img_url` | string \| null | основное изображение (обложка) |
| `image_urls` | string[] | галерея: **объединение** `img_url` (если есть) и URL из `image_urls_json` на сервере, без дубликатов; порядок — сначала обложка |
| `description` | string \| null | |
| `age` | string \| null | возрастное ограничение и т.п. |
| `date_caption` | string \| null | текст про дату/время для UI |
| `place` | string \| null | адрес/место |
| `url` | string \| null | внешняя ссылка на источник |
| `rating` | string \| null | |
| `schedule` | string \| null | |
| `status` | string \| null | |
| `type` | string \| null | категория события (например IT / Искусство / История) |
| `review_bucket` | string \| null | папка/тип для загрузки фото отзывов на сервере |
| `created_at` | datetime | |
| `ingest_key` | string \| null | ключ внешнего импорта, если событие с афиши |
| `last_ingested_at` | datetime \| null | время последнего обновления импортом |

Внешние URL картинок могут быть абсолютными ссылки на сторонние сайты; локальные загрузки — через `{PUBLIC_BASE_URL}/static/...`. Для корректной загрузки медиа с телефона **`PUBLIC_BASE_URL` на сервере должен совпадать с тем хостом, по которому клиент ходит в API**.

---

### `GET /events`

**Query:**

| Параметр | Тип | По умолчанию | Описание |
|----------|-----|--------------|----------|
| `type` | string | нет | фильтр по полю `type` события |
| `limit` | int | 50 | 1–200 |
| `offset` | int | 0 | ≥ 0 |

**Ответ 200:** `EventOut[]`. Порядок: `created_at` по убыванию.

---

### `GET /events/search`

**Query:**

| Параметр | Тип | Описание |
|----------|-----|----------|
| `q` | string | минимум 1 символ; поиск по подстроке в `name`, `description`, `place` (без учёта регистра) |
| `limit` | int | 1–200, default 50 |
| `offset` | int | default 0 |

**Ответ 200:** `EventOut[]`.

---

### `GET /events/{event_id}`

**Ответ 200:** один `EventOut`. **404** — нет события.

---

### `POST /events` — **Admin**

Создание события вручную.

**Заголовок:** `X-Admin-Key`.

**Тело (JSON) — `EventCreate`:**

| Поле | Тип | Описание |
|------|-----|----------|
| `name` | string | обязательно, max 512 |
| `slug` | string \| null | max 512, опционально |
| `img_url` | string \| null | |
| `image_urls` | string[] \| null | список URL галереи; на БД кладётся JSON в `image_urls_json` |
| `description` | string \| null | |
| `age` | string \| null | |
| `date_caption` | string \| null | max 512 |
| `place` | string \| null | |
| `url` | string \| null | |
| `rating` | string \| null | |
| `schedule` | string \| null | |
| `status` | string \| null | |
| `type` | string \| null | |
| `review_bucket` | string \| null | если не передан — вычисляется от `type` на сервере |

**Ответ 201:** `EventOut`.

---

## 7. Отзывы — `/events/{event_id}/...`

### Объект `ReviewOut`

| Поле | Тип |
|------|-----|
| `id` | UUID |
| `event_id` | UUID |
| `user_id` | UUID |
| `rating` | int (1–5) |
| `text` | string |
| `user_name` | string |
| `review_date` | string \| null | строка вица даты, сервер выставляет при сохранении |
| `avatar_url` | string \| null |
| `created_at` | datetime |
| `photos` | `ReviewPhotoOut[]` |

**`ReviewPhotoOut`:** `id` (UUID), `url` (string), `sort_order` (int).

---

### `GET /events/{event_id}/reviews`

**Query:** `limit` (1–200, default 50), `offset` (default 0).

**Ответ 200:** `ReviewOut[]`, новые сверху. **404** — событие не найдено.

---

### `GET /events/{event_id}/rating-summary`

**Ответ 200:**

| Поле | Тип |
|------|-----|
| `average` | float | среднее по отзывам, 0.0 если отзывов нет |
| `count` | int | количество отзывов |

**404** — событие не найдено.

---

### `POST /events/{event_id}/reviews`

**Аутентификация:** Bearer.

**Тело (JSON) — `ReviewCreate`:**

| Поле | Тип | Описание |
|------|-----|----------|
| `rating` | int | 1–5 |
| `text` | string | допускается пустая строка |
| `photo_urls` | string[] | URL уже загруженных фото (см. `POST /uploads/review-photos`) |

**Поведение:** у пользователя **один отзыв на событие**. Повторный POST **обновляет** тот же отзыв (текст, рейтинг, фото заменяются). Имя и аватар подставляются из профиля.

**Ответ 201:** `ReviewOut` с загруженными `photos`.

---

## 8. Загрузка фото для отзыва — `/uploads`

### `POST /uploads/review-photos`

**Аутентификация:** Bearer.

**Тело:** `multipart/form-data`:

| Поле | Тип | Описание |
|------|-----|----------|
| `event_id` | string (UUID) | обязательно |
| `files` | file[] | одно или несколько изображений |

**Ответ 201:**

```json
{
  "urls": ["https://...", "https://..."]
}
```

Абсолютные URL для передачи в `photo_urls` при создании отзыва.

**Ошибки:** **400** — нет файлов; **404** — событие не найдено.

---

## 9. Ассистент — `/assistant`

### `POST /assistant/route-quiz`

**Аутентификация:** не требуется (квиз до логина).

**Тело (JSON):**

| Поле | Тип | По умолчанию |
|------|-----|--------------|
| `answers` | object (произвольный JSON) | `{}` |
| `update_profile_category` | bool | `true` |

Сервер отправляет `answers` во внешнюю LLM и ожидает JSON с полем `category`.

**Ответ 200:**

| Поле | Тип |
|------|-----|
| `category` | string | нормализованная метка (на практике может быть `IT`, `искусство`, `история` и т.д. — зависит от ответа модели) |
| `raw` | string \| null | сырой/очищенный ответ модели для отладки |

При ошибке прокси ответ может быть запасным (`category` по умолчанию `история`, `raw` null).

---

### `POST /assistant/chat`

**Аутентификация:** Bearer.

**Тело (JSON):**

| Поле | Тип | Ограничения |
|------|-----|-------------|
| `message` | string | 1–8000 символов |

**Ответ 200:**

```json
{ "reply": "текст ответа ассистента" }
```

При сбоях сети/таймаута сервер всё равно отвечает **200** с человекочитаемым сообщением об ошибке в `reply`.

---

## 10. Админ: импорт афиши — `/admin`

### `POST /admin/ingest/run` — **Admin**

**Заголовок:** `X-Admin-Key`.

**Тело:** нет.

**Ответ 200:** JSON-объект со счётчиками импорта (ключи зависят от реализации `run_izhevsk_ingest`, например числа upsert для RSS и adm.izh).

---

## Рекомендуемый порядок для мобильного клиента

1. **Регистрация/вход** → сохранить `access_token`.
2. **Главная:** `GET /home-categories`, `GET /events?type=...` или общий список.
3. **Карточка:** `GET /events/{id}`, `GET .../rating-summary`, `GET .../reviews`, при необходимости `GET /users/me/favorites/status?event_ids=...`.
4. **Избранное:** `PUT` / `DELETE` на `/users/me/favorites/{event_id}`, список `GET /users/me/favorites`.
5. **Отзыв с фото:** `POST /uploads/review-photos` (multipart) → `POST /events/{id}/reviews` с `photo_urls`.
6. **Профиль:** `GET/PATCH /users/me`, аватар `POST /users/me/avatar`.
7. **Пуш:** `POST /users/me/device-tokens` при получении FCM/APNs токена.

---

## Версия документа

Согласовано с кодовой базой проекта **Technostrelka API** (`app/main.py`: title/version 1.0.0). При изменении схем Pydantic в `app/schemas/` этот файл следует обновлять.
