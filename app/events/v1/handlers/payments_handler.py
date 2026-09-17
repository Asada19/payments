from __future__ import annotations

import logging

from dishka import FromDishka
from faststream import AckPolicy
from faststream.rabbit import Channel, RabbitBroker, RabbitRouter
from faststream.rabbit.annotations import RabbitMessage
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.broker import PAYMENTS_EXCHANGE, QUEUE_NEW
from app.core.config import Settings
from app.domain.services.consumer import handle_payment_event
from app.events.v1.schemas.payments import PaymentNewEvent

logger = logging.getLogger(__name__)


async def payments_new_handler(
    msg: RabbitMessage,
    session: FromDishka[AsyncSession],
    broker: FromDishka[RabbitBroker],
) -> None:
    try:
        event = PaymentNewEvent.model_validate(await msg.decode())
    except Exception as exc:
        # A payload that doesn't even parse as PaymentNewEvent can only come
        # from a bug or a foreign producer. With ack_policy=MANUAL it would
        # otherwise stay unacked and get redelivered forever, so it goes
        # straight to the DLQ instead.
        logger.warning(
            "malformed payments.new message, rejecting to dlq message_id=%s error=%s",
            msg.message_id,
            exc,
        )
        await msg.reject()
        return

    await handle_payment_event(event, msg, session, broker)


def initialize_payments_router(settings: Settings) -> RabbitRouter:
    router = RabbitRouter()
    router.subscriber(
        QUEUE_NEW,
        PAYMENTS_EXCHANGE,
        channel=Channel(
            prefetch_count=settings.consumer_prefetch_count,
            publisher_confirms=True,
            on_return_raises=True,
        ),
        ack_policy=AckPolicy.MANUAL,
    )(payments_new_handler)
    return router
