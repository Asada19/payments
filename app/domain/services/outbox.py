from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from faststream.rabbit import RabbitBroker
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.broker import PAYMENTS_EXCHANGE, QUEUE_NEW_NAME
from app.core.config import Settings
from app.domain.models import OutboxEvent, OutboxStatus

logger = logging.getLogger(__name__)


async def publish_pending_batch(
    session: AsyncSession, broker: RabbitBroker, settings: Settings
) -> int:
    result = await session.execute(
        select(OutboxEvent)
        .where(OutboxEvent.status == OutboxStatus.pending)
        .order_by(OutboxEvent.created_at)
        .with_for_update(skip_locked=True)
        .limit(settings.outbox_batch_size)
    )
    events = list(result.scalars().all())
    if not events:
        return 0

    now = datetime.now(UTC)
    for event in events:
        await broker.publish(
            event.payload,
            exchange=PAYMENTS_EXCHANGE,
            routing_key=QUEUE_NEW_NAME,
            persist=True,
            message_id=str(event.id),
            mandatory=True,
            timeout=settings.publish_timeout_seconds,
        )
        event.status = OutboxStatus.published
        event.published_at = now
    return len(events)


async def run_relay_loop(
    broker: RabbitBroker,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    stop: asyncio.Event,
) -> None:
    while not stop.is_set():
        try:
            async with session_factory() as session, session.begin():
                published = await publish_pending_batch(session, broker, settings)
            if published:
                logger.info("outbox published=%s", published)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("outbox relay iteration failed")

        try:
            await asyncio.wait_for(
                stop.wait(), timeout=settings.outbox_poll_interval_seconds
            )
        except TimeoutError:
            continue
