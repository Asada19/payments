from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import UUID

from faststream.rabbit import RabbitBroker
from faststream.rabbit.message import RabbitMessage
from sqlalchemy import update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.broker import PAYMENTS_EXCHANGE
from app.core.config import Settings, get_settings
from app.domain.errors import PaymentNotFoundError
from app.domain.models import Payment, PaymentHistoryEventType, PaymentStatus
from app.domain.services.gateway import emulate_gateway
from app.domain.services.history import record_history_event
from app.domain.services.retry import Decision, NextAction, decide_next_action
from app.domain.services.webhook import (
    WebhookDeliveryError,
    WebhookPayload,
    send_webhook,
)
from app.events.v1.schemas.payments import PaymentNewEvent

logger = logging.getLogger(__name__)


async def claim_payment(
    session: AsyncSession,
    payment_id: UUID,
    new_status: PaymentStatus,
) -> bool:
    result = await session.execute(
        update(Payment)
        .where(Payment.id == payment_id, Payment.status == PaymentStatus.pending)
        .values(status=new_status, processed_at=datetime.now(UTC))
    )
    claimed = isinstance(result, CursorResult) and result.rowcount == 1
    if claimed:
        event_type = (
            PaymentHistoryEventType.gateway_succeeded
            if new_status == PaymentStatus.succeeded
            else PaymentHistoryEventType.gateway_failed
        )
        record_history_event(session, payment_id, event_type)
    await session.commit()
    return claimed


async def claim_webhook_delivery(session: AsyncSession, payment_id: UUID) -> bool:
    """Atomically reserve the right to send the webhook for this payment.

    Two concurrent handlers for the same payment_id (an outbox double-publish
    after a relay crash, or an overlapping redelivery) would otherwise both
    read webhook_delivered_at IS NULL and both POST -- this conditional UPDATE
    makes only one of them win, mirroring claim_payment's own pattern above.
    """
    result = await session.execute(
        update(Payment)
        .where(Payment.id == payment_id, Payment.webhook_delivered_at.is_(None))
        .values(webhook_delivered_at=datetime.now(UTC))
    )
    await session.commit()
    return isinstance(result, CursorResult) and result.rowcount == 1


async def release_webhook_claim(session: AsyncSession, payment_id: UUID) -> None:
    """Undo claim_webhook_delivery after a failed send, so the retry/DLQ path
    (which re-checks webhook_delivered_at IS NULL) can try again."""
    await session.execute(
        update(Payment)
        .where(Payment.id == payment_id)
        .values(webhook_delivered_at=None)
    )
    await session.commit()


async def apply_decision(
    decision: Decision,
    event: PaymentNewEvent,
    msg: RabbitMessage,
    broker: RabbitBroker,
    attempt: int,
    publish_timeout: float,
) -> None:
    if decision.action == NextAction.RETRY:
        assert decision.routing_key is not None
        await broker.publish(
            event.model_dump(mode="json"),
            exchange=PAYMENTS_EXCHANGE,
            routing_key=decision.routing_key,
            persist=True,
            message_id=msg.message_id,
            headers={"x-retry-count": attempt + 1},
            mandatory=True,
            timeout=publish_timeout,
        )
        await msg.ack()
        logger.info(
            "scheduled retry payment_id=%s message_id=%s attempt=%s routing_key=%s",
            event.payment_id,
            msg.message_id,
            attempt,
            decision.routing_key,
        )
        return

    await msg.reject()
    logger.warning(
        "rejected to dlq payment_id=%s message_id=%s attempt=%s",
        event.payment_id,
        msg.message_id,
        attempt,
    )


async def handle_payment_event(
    event: PaymentNewEvent,
    msg: RabbitMessage,
    session: AsyncSession,
    broker: RabbitBroker,
    app_settings: Settings | None = None,
) -> None:
    cfg = app_settings or get_settings()
    attempt = int(msg.headers.get("x-retry-count", 0) or 0)
    logger.info(
        "consume payment_id=%s message_id=%s attempt=%s",
        event.payment_id,
        msg.message_id,
        attempt,
    )

    try:
        payment = await session.get(Payment, event.payment_id)
        if payment is None:
            raise PaymentNotFoundError(event.payment_id)

        if payment.status == PaymentStatus.pending:
            outcome = await emulate_gateway()
            claimed = await claim_payment(session, payment.id, outcome)
            payment = await session.get(Payment, payment.id)
            if payment is None:
                raise PaymentNotFoundError(event.payment_id)
            logger.info(
                "gateway outcome payment_id=%s status=%s claimed=%s",
                payment.id,
                payment.status.value,
                claimed,
            )

        if payment.webhook_delivered_at is None:
            if payment.processed_at is None or payment.status == PaymentStatus.pending:
                raise RuntimeError("payment is not terminal before webhook")
            claimed_webhook = await claim_webhook_delivery(session, payment.id)
            if not claimed_webhook:
                logger.info(
                    "webhook delivery already claimed elsewhere payment_id=%s",
                    payment.id,
                )
            else:
                payload = WebhookPayload(
                    payment_id=payment.id,
                    status=payment.status,
                    amount=payment.amount,
                    currency=payment.currency,
                    processed_at=payment.processed_at,
                )
                try:
                    await send_webhook(
                        payment.webhook_url,
                        payload,
                        timeout=cfg.webhook_timeout_seconds,
                        signing_secret=cfg.webhook_signing_secret,
                        ssrf_allowed_hosts=cfg.webhook_ssrf_allowed_hosts_set,
                    )
                except Exception:
                    await release_webhook_claim(session, payment.id)
                    raise
                record_history_event(
                    session, payment.id, PaymentHistoryEventType.webhook_delivered
                )
                await session.commit()

        await msg.ack()
        logger.info(
            "acked payment_id=%s message_id=%s status=%s",
            payment.id,
            msg.message_id,
            payment.status.value,
        )
    except PaymentNotFoundError:
        logger.warning(
            "payment not found, reject to dlq payment_id=%s message_id=%s",
            event.payment_id,
            msg.message_id,
        )
        await msg.reject()
    except Exception as exc:
        if isinstance(exc, WebhookDeliveryError):
            logger.warning(
                "webhook delivery failed payment_id=%s message_id=%s attempt=%s error=%s",
                event.payment_id,
                msg.message_id,
                attempt,
                exc,
            )
        else:
            logger.exception(
                "processing failed payment_id=%s message_id=%s attempt=%s",
                event.payment_id,
                msg.message_id,
                attempt,
            )
        try:
            await session.rollback()
        except Exception:
            logger.exception("session rollback failed")
        decision = decide_next_action(attempt, ok=False)
        if decision.action == NextAction.DLQ:
            try:
                record_history_event(
                    session,
                    event.payment_id,
                    PaymentHistoryEventType.webhook_delivery_failed,
                    detail={"error": str(exc)},
                )
                await session.commit()
            except Exception:
                logger.exception(
                    "failed to record dlq history event payment_id=%s",
                    event.payment_id,
                )
        try:
            await apply_decision(
                decision,
                event,
                msg,
                broker,
                attempt,
                publish_timeout=cfg.publish_timeout_seconds,
            )
        except Exception:
            logger.exception(
                "failed to apply retry/dlq payment_id=%s message_id=%s",
                event.payment_id,
                msg.message_id,
            )
