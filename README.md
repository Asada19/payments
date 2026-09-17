# Payment processing service

Асинхронный микросервис приёма платежей: FastAPI принимает запрос, через transactional outbox публикует событие в RabbitMQ, FastStream-consumer эмулирует платёжный шлюз, атомарно фиксирует статус и один раз за попытку отправляет webhook.

Стек: Python 3.13, FastAPI, Pydantic v2, SQLAlchemy 2.0 (async), Alembic, FastStream 0.7 / RabbitMQ, PostgreSQL, Dishka (DI). Зависимости через **uv**.

## Структура

Слоями, как в бэкенде на моей текущей работе — `api` не знает `domain`/`events` изнутри, `domain` не знает `api`:

```
app/
├── main.py, worker.py        # два процесса: uvicorn-приложение и FastStream-консьюмер
├── api/v1/
│   ├── endpoints/payments.py     # роутер: payments + payments/{id}/history
│   ├── schemas/payments.py       # входные/выходные DTO + canonical_request_hash
│   ├── dependencies/auth.py, rate_limit.py
│   └── error_handlers.py         # доменная ошибка -> HTTP-ответ
├── core/                     # сквозные вещи: конфиг, DI, брокер, БД, логирование, SSRF-guard
│   ├── config.py, db.py, broker.py, di.py, logging.py, ssrf_guard.py
├── domain/
│   ├── models.py, errors.py      # SQLAlchemy-модели (+ payment_history), доменные исключения
│   └── services/                 # payments, consumer, gateway, outbox, retry, webhook, history
└── events/v1/
    ├── handlers/payments_handler.py  # router-фабрика для FastStream
    └── schemas/payments.py           # схема события payments.new
```

`tests/unit/` зеркалит это деление (`api/`, `domain/`, `events/`), `tests/integration/` — отдельно.

Два места, где грань между слоями сознательно не строгая: `domain/services/payments.py` принимает `PaymentCreate` прямо из `api/v1/schemas`, а `domain/services/consumer.py` — `PaymentNewEvent` из `events/v1/schemas`. Оба — обычные Pydantic-модели без фреймворковой связности, а не HTTP/AMQP-объекты, так что для сервиса такого размера заводить отдельный слой доменных input-моделей ради формальной чистоты не показалось оправданным.

## DI-контейнер

Через [Dishka](https://github.com/reagento/dishka) вместо глобальных синглтонов. Каждый `Provider` лежит **в том же файле, что и то, что он предоставляет**, а [app/core/di.py](app/core/di.py) — это только тонкий composition root, который собирает списки провайдеров для api/consumer:

- `ConfigProvider` в [app/core/config.py](app/core/config.py) — отдаёт `Settings`, переданный в конструктор явно (не читает глобал). Вне DI-контекста (миграции, module-level код) конфиг берётся через `get_settings()` — `functools.cache`-обёртку над `Settings()`, а не через синглтон, созданный при импорте.
- `DbProvider` в [app/core/db.py](app/core/db.py) — `AsyncEngine` (APP scope, `dispose()` при закрытии контейнера), `async_sessionmaker`, и `AsyncSession` per-request/per-message (REQUEST scope).
- `ApiBrokerProvider` / `WorkerBrokerProvider` в [app/core/broker.py](app/core/broker.py) — api сам строит и коннектит свой `RabbitBroker` (только на publish); consumer уже создал `RabbitBroker` на уровне модуля (чтобы навесить подписчик), поэтому контейнер получает этот же инстанс через `from_context`, а не создаёт новый.

В FastAPI это `dishka.integrations.fastapi` (`DishkaRoute` + `FromDishka[...]` в сигнатуре эндпоинта, `@inject` на `require_api_key`), в consumer — `dishka-faststream` (`setup_dishka(..., auto_inject=True)`, `FromDishka[AsyncSession]` / `FromDishka[RabbitBroker]` прямо в сигнатуре подписчика).

## Consumer и события

FastStream-подписчик зарегистрирован через router-фабрику [app/events/v1/handlers/payments_handler.py](app/events/v1/handlers/payments_handler.py) (`initialize_payments_router(settings) -> RabbitRouter`, `worker.py` — только `broker.include_router(...)` + `app.run()`). Сам `payments_new_handler` — обычная модульная функция, а не замыкание внутри фабрики, поэтому тестируется напрямую (`tests/unit/events/test_payments_handler.py`) без контейнера и брокера, точно как `handle_payment_event` в [app/domain/services/consumer.py](app/domain/services/consumer.py), в который он делегирует бизнес-логику.

Перед парсингом в `PaymentNewEvent` тело сообщения декодируется и валидируется вручную (`msg.decode()` + `model_validate`, не через автокастинг параметра хендлера) — сообщение, которое не парсится в `PaymentNewEvent`, отправляется в DLQ логированным `reject()`, а не остаётся `unacked`: при `AckPolicy.MANUAL` автоматическая pydantic-валидация типизированного параметра подписчика падает *до* тела хендлера, и без ручного перехвата сообщение виснет в `messages_unacknowledged` и передоставляется бесконечно при любом переподключении консьюмера.

## Ошибки

Доменные ошибки — обычные исключения ([app/domain/errors.py](app/domain/errors.py): `PaymentNotFoundError`, `IdempotencyConflictError`), не `HTTPException`. Сервисный слой ([app/domain/services/payments.py](app/domain/services/payments.py)) их поднимает, а маппинг в HTTP-ответ живёт в одном месте — [app/api/v1/error_handlers.py](app/api/v1/error_handlers.py) (`register_error_handlers(app)`, вызывается из `create_app()`). Эндпоинты не содержат `try/except`/`if payment is None` — только бизнес-вызов.

## Локальная разработка

Нужны [uv](https://docs.astral.sh/uv/) и Python 3.13.

```bash
uv sync --group dev
uv run pre-commit install
```

Команды:

```bash
uv run ruff check app tests migrations
uv run ruff format app tests migrations
uv run mypy app
uv run pytest -m "not integration"
uv run pre-commit run --all-files
```

## Запуск

```bash
COMPOSE_BAKE=false docker compose up --build
```

Если Docker ругается на имя проекта из-за кириллицы в пути, задайте `COMPOSE_PROJECT_NAME=payments` (в `docker-compose.yml` уже стоит `name: payments`). На некоторых версиях Docker Desktop для пути с не-ASCII нужен `COMPOSE_BAKE=false`.

Сервисы:

- API: http://localhost:8000
- OpenAPI: http://localhost:8000/docs
- RabbitMQ UI: http://localhost:15672 (guest/guest)
- Postgres: localhost:5432, user/password/db `payments`

API поднимается одним процессом uvicorn (`--workers 1`): outbox-relay живёт в lifespan. Consumer стартует только после `GET /healthz` — к этому моменту миграции применены, топология очередей объявлена.

Локальный API-ключ по умолчанию: `local-development-key`.

## Создание платежа

Happy path (webhook всегда 200):

```bash
curl -sS -X POST http://localhost:8000/api/v1/payments \
  -H 'Content-Type: application/json' \
  -H 'X-API-Key: local-development-key' \
  -H 'Idempotency-Key: demo-1' \
  -d '{
    "amount": "100.00",
    "currency": "RUB",
    "description": "demo",
    "metadata": {"order_id": "A-1"},
    "webhook_url": "http://api:8000/debug/sink"
  }'
```

Ответ `202 Accepted`: `payment_id`, `status=pending`, `created_at`.

Получение платежа (тот же `X-API-Key`):

```bash
curl -sS http://localhost:8000/api/v1/payments/<payment_id> \
  -H 'X-API-Key: local-development-key'
```

Повтор POST с тем же `Idempotency-Key` и тем же телом вернёт существующий платёж. То же ключ, другое тело — `409`. Ключ ограничен 255 символами на уровне заголовка (совпадает с колонкой в БД, чтобы слишком длинный ключ падал чистым `422`, а не сырой ошибкой БД).

Ключ живёт **вечно** — он не отдельная запись с TTL, а колонка на самой записи `payments` (`uq_payments_idempotency_key`), поэтому его retention совпадает с retention самого платежа. Это осознанный выбор в пользу аудита (Stripe, для сравнения, по умолчанию хранит ключ 24 часа), а не забытый TTL: отдельная таблица-кэш с собственным жизненным циклом добавила бы сложности ради возможности нарочно забыть, что было оплачено.

`amount` валидируется по точности **валюты**, не глобально: `CURRENCY_DECIMAL_PLACES` в [app/domain/models.py](app/domain/models.py) — 2 знака для RUB/USD/EUR сегодня, но если добавится JPY (0 знаков) или KWD (3 знака), их придётся явно завести в этом словаре, а не тихо сломать округление.

Демо-приёмники вебхуков (без API-ключа, их вызывает consumer):

- `POST /debug/sink` — 200, тело пишется в лог api
- `POST /debug/fail` — всегда 500

Для DLQ отправьте платёж с `"webhook_url": "http://api:8000/debug/fail"`.

`webhook_url` должен быть достижим **из контейнера consumer**. Именно поэтому в примерах хост `api`, а не `localhost`.

## Retry и DLQ

Три попытки обработки сообщения. Попытки и DLQ расходуются только на ошибках доставки webhook и инфраструктурных сбоях.

Ошибка эмулятора шлюза (10%) — это бизнес-исход `failed`: статус пишется в БД, webhook уходит, сообщение `ack`. Такой платёж в DLQ не попадает.

Между неудачными доставками webhook задержки 2s и 4s (очереди `payments.retry.2s` / `payments.retry.4s`). После третьей неудачи сообщение уходит в `payments.new.dlq`.

**Семантика DLQ:** там лежат недоставленные уведомления. Сам платёж к этому моменту уже `succeeded` или `failed`. Это не откат платежа.

Тело вебхука:

```json
{
  "payment_id": "...",
  "status": "succeeded",
  "amount": "100.00",
  "currency": "RUB",
  "processed_at": "2026-09-17T00:00:00+00:00"
}
```

`payment_id` обязателен: доставка at-least-once, клиент строит на нём свою идемпотентность.

Prefetch consumer равен 10: пачка платежей обрабатывается параллельно, гонку за статус закрывает условный `UPDATE ... WHERE status='pending'`. На демо очередь не будет «стоять» по 3.5 секунды на каждое сообщение.

Очереди в management UI (`:15672`, вкладка Queues): `payments.new`, `payments.retry.2s`, `payments.retry.4s`, `payments.new.dlq`.

## Безопасность вебхука

**Подпись.** Каждый webhook подписан: `X-Webhook-Signature` — hex HMAC-SHA256 от `"{timestamp}." + raw_body`, `X-Webhook-Timestamp` — unix-время в секундах (`WEBHOOK_SIGNING_SECRET`, тот же секрет на api и consumer, публикующем платёж не нужен). Таймстемп — часть подписываемого сообщения, а не соседний заголовок, поэтому перехваченную подпись нельзя переиграть с другим временем. Получатель должен пересчитать HMAC с общим секретом через `hmac.compare_digest` и отклонять запросы старше нескольких минут (реализация подписи — [app/domain/services/webhook.py](app/domain/services/webhook.py):`sign_webhook_body`).

**SSRF-защита.** `webhook_url` резолвится и проверяется **на каждую отправку**, не только при создании платежа (DNS может измениться между попытками) — приватные/loopback/link-local/reserved-адреса (включая `169.254.169.254`) отклоняются до похода в сеть ([app/core/ssrf_guard.py](app/core/ssrf_guard.py)). `WEBHOOK_SSRF_ALLOWED_HOSTS` — явный allowlist имён хостов, минующих резолвинг; по умолчанию туда входит только `api` — свой же демо-приёмник в docker-сети.

**Гонка на отправке.** Два одновременных обработчика одного и того же `payment_id` (дубль из outbox после падения relay, или overlap ретрая) раньше могли оба увидеть `webhook_delivered_at IS NULL` и оба отправить webhook. `claim_webhook_delivery` в [app/domain/services/consumer.py](app/domain/services/consumer.py) резервирует отправку условным `UPDATE ... WHERE webhook_delivered_at IS NULL` **до** похода в сеть — тем же паттерном, что `claim_payment` уже использовал для исхода шлюза; при неудачной отправке `release_webhook_claim` откатывает флаг, чтобы retry/DLQ сработали как обычно. Проверено на реальном Postgres в [tests/integration/test_consumer.py](tests/integration/test_consumer.py).

## Rate limiting

`POST /api/v1/payments` и `GET /api/v1/payments/{id}` лимитируются по `X-API-Key` (не по IP — это авторизованная сущность), скользящее окно в памяти процесса ([app/api/v1/dependencies/rate_limit.py](app/api/v1/dependencies/rate_limit.py)). In-memory осознанно: api и так работает одним uvicorn-воркером (см. выше), общий стор типа Redis не нужен для корректности. `RATE_LIMIT_WINDOW_SECONDS` / `RATE_LIMIT_MAX_REQUESTS`, превышение — `429`.

## История платежа (аудит)

`payments` хранит только текущее состояние. Каждый переход состояния пишется дополнительно в append-only `payment_history` (никаких `UPDATE`/`DELETE` — только `INSERT`): `created`, `gateway_succeeded`/`gateway_failed`, `webhook_delivered`, `webhook_delivery_failed`. Регуляторы (SEC/FCA/MAS и аналоги) в реальном финтехе требуют именно такой неизменяемый журнал, а не только финальный статус — здесь это минимальная версия того же принципа.

```bash
curl -sS http://localhost:8000/api/v1/payments/<payment_id>/history \
  -H 'X-API-Key: local-development-key'
```

## Тесты

`tests/unit/` (без Postgres и брокера) и `tests/integration/` (нужен `DATABASE_URL`) — 1:1 с делением на быстрые и требующие инфраструктуры, `pytest.mark.integration` расставлен по файлам, а не по каждому тесту.

Юниты:

```bash
uv run pytest -m "not integration"
```

Интеграция (уникальный индекс, 409) — внутри compose, где есть `DATABASE_URL`:

```bash
docker compose exec api pytest -m integration
```

Вне контейнера те же тесты сработают, если задан `DATABASE_URL`:

```bash
DATABASE_URL=postgresql+asyncpg://payments:payments@localhost:5432/payments \
  uv run pytest -m integration
```

## Переменные окружения

| Имя | Назначение |
|---|---|
| `API_KEY` | Статический ключ для `X-API-Key` на POST/GET платежей |
| `DATABASE_URL` | SQLAlchemy async URL (`postgresql+asyncpg://...`) |
| `RABBITMQ_URL` | AMQP URL |
| `OUTBOX_POLL_INTERVAL_SECONDS` | Интервал опроса outbox |
| `PUBLISH_TIMEOUT_SECONDS` | Таймаут publish (relay и retry) |
| `WEBHOOK_TIMEOUT_SECONDS` | Таймаут одного HTTP POST |
| `CONSUMER_PREFETCH_COUNT` | QoS prefetch, по умолчанию 10 |
| `WEBHOOK_SIGNING_SECRET` | Секрет HMAC-подписи вебхука (`X-Webhook-Signature`) |
| `WEBHOOK_SSRF_ALLOWED_HOSTS` | Хосты через запятую, минующие SSRF-резолвинг (по умолчанию `api`) |
| `RATE_LIMIT_WINDOW_SECONDS` | Окно rate limit на API-ключ, по умолчанию 60 |
| `RATE_LIMIT_MAX_REQUESTS` | Лимит запросов за окно на API-ключ, по умолчанию 30 |
