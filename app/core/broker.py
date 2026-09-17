from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterable

from dishka import Provider, Scope, from_context, provide
from faststream.rabbit import (
    Channel,
    ExchangeType,
    RabbitBroker,
    RabbitExchange,
    RabbitQueue,
)

from app.core.config import Settings

logger = logging.getLogger(__name__)

PAYMENTS_EXCHANGE_NAME = "payments"
PAYMENTS_DLX_NAME = "payments.dlx"
QUEUE_NEW_NAME = "payments.new"
QUEUE_RETRY_2S_NAME = "payments.retry.2s"
QUEUE_RETRY_4S_NAME = "payments.retry.4s"
QUEUE_DLQ_NAME = "payments.new.dlq"

PAYMENTS_EXCHANGE = RabbitExchange(
    PAYMENTS_EXCHANGE_NAME,
    type=ExchangeType.DIRECT,
    durable=True,
)
PAYMENTS_DLX = RabbitExchange(
    PAYMENTS_DLX_NAME,
    type=ExchangeType.DIRECT,
    durable=True,
)

QUEUE_NEW = RabbitQueue(
    QUEUE_NEW_NAME,
    durable=True,
    arguments={
        "x-dead-letter-exchange": PAYMENTS_DLX_NAME,
        "x-dead-letter-routing-key": QUEUE_DLQ_NAME,
    },
)
QUEUE_RETRY_2S = RabbitQueue(
    QUEUE_RETRY_2S_NAME,
    durable=True,
    arguments={
        "x-message-ttl": 2000,
        "x-dead-letter-exchange": PAYMENTS_EXCHANGE_NAME,
        "x-dead-letter-routing-key": QUEUE_NEW_NAME,
    },
)
QUEUE_RETRY_4S = RabbitQueue(
    QUEUE_RETRY_4S_NAME,
    durable=True,
    arguments={
        "x-message-ttl": 4000,
        "x-dead-letter-exchange": PAYMENTS_EXCHANGE_NAME,
        "x-dead-letter-routing-key": QUEUE_NEW_NAME,
    },
)
QUEUE_DLQ = RabbitQueue(QUEUE_DLQ_NAME, durable=True)

RETRY_ROUTING_BY_ATTEMPT = {
    0: QUEUE_RETRY_2S_NAME,
    1: QUEUE_RETRY_4S_NAME,
}


def build_broker(url: str, *, prefetch: int | None = None) -> RabbitBroker:
    channel = Channel(
        prefetch_count=prefetch,
        publisher_confirms=True,
        on_return_raises=True,
    )
    return RabbitBroker(url, default_channel=channel)


async def setup_topology(broker: RabbitBroker) -> None:
    payments = await broker.declare_exchange(PAYMENTS_EXCHANGE)
    dlx = await broker.declare_exchange(PAYMENTS_DLX)

    new_queue = await broker.declare_queue(QUEUE_NEW)
    await new_queue.bind(payments, routing_key=QUEUE_NEW_NAME)

    retry_2s = await broker.declare_queue(QUEUE_RETRY_2S)
    await retry_2s.bind(payments, routing_key=QUEUE_RETRY_2S_NAME)

    retry_4s = await broker.declare_queue(QUEUE_RETRY_4S)
    await retry_4s.bind(payments, routing_key=QUEUE_RETRY_4S_NAME)

    dlq = await broker.declare_queue(QUEUE_DLQ)
    await dlq.bind(dlx, routing_key=QUEUE_DLQ_NAME)


async def wait_for_rabbitmq(broker: RabbitBroker, attempts: int = 30) -> None:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            await broker.connect()
            logger.info("connected to rabbitmq")
            return
        except Exception as exc:
            last_error = exc
            logger.warning(
                "rabbitmq not ready attempt=%s/%s error=%s",
                attempt,
                attempts,
                exc,
            )
            await asyncio.sleep(1)
    raise RuntimeError("could not connect to rabbitmq") from last_error


class ApiBrokerProvider(Provider):
    """API process publishes only: it owns and connects its own broker."""

    scope = Scope.APP

    @provide
    async def get_broker(self, cfg: Settings) -> AsyncIterable[RabbitBroker]:
        broker = build_broker(cfg.rabbitmq_url)
        await wait_for_rabbitmq(broker)
        await setup_topology(broker)
        try:
            yield broker
        finally:
            await broker.stop()


class WorkerBrokerProvider(Provider):
    """Worker builds its broker at import time to attach subscribers to it;
    this exposes that already-running instance instead of building a new one."""

    broker = from_context(provides=RabbitBroker, scope=Scope.APP)
