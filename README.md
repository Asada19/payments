# Payment processing service

Асинхронный приём платежей: FastAPI принимает запрос, transactional outbox публикует событие в RabbitMQ, FastStream-consumer эмулирует шлюз и один раз отправляет webhook.

Стек: Python 3.13, FastAPI, SQLAlchemy 2.0, Alembic, FastStream / RabbitMQ, PostgreSQL, Dishka. Зависимости через [uv](https://docs.astral.sh/uv/).

## Запуск

```bash
cp .env.example .env
docker compose up --build
```

- API: http://localhost:8000/docs
- RabbitMQ UI: http://localhost:15672 (`guest` / `guest`)
- API-ключ: `local-development-key`

```bash
curl -sS -X POST http://localhost:8000/api/v1/payments \
  -H 'Content-Type: application/json' \
  -H 'X-API-Key: local-development-key' \
  -H 'Idempotency-Key: demo-1' \
  -d '{
    "amount": "100.00",
    "currency": "RUB",
    "description": "demo",
    "webhook_url": "http://api:8000/debug/sink"
  }'
```

Ответ `202`: `payment_id`, `status=pending`. Дальше: `GET /api/v1/payments/{id}` и `GET /api/v1/payments/{id}/history`.

Повтор с тем же ключом и телом вернёт существующий платёж, другое тело — `409`. `webhook_url` должен быть доступен из контейнера consumer (`api`, не `localhost`). Демо-приёмники: `/debug/sink` (200), `/debug/fail` (500 → DLQ).

Webhook подписан HMAC-SHA256 (`X-Webhook-Signature` / `X-Webhook-Timestamp`). Недоставленные уведомления уходят в `payments.new.dlq` после трёх попыток; сам платёж к этому моменту уже `succeeded` или `failed`.

## Разработка

```bash
uv sync --group dev
uv run ruff check app tests migrations
uv run mypy app
uv run pytest -m "not integration"
docker compose exec api pytest -m integration
```
