from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas.payments import PaymentCreate, canonical_request_hash
from app.domain.errors import IdempotencyConflictError, PaymentNotFoundError
from app.domain.models import (
    PAYMENTS_NEW_EVENT,
    OutboxEvent,
    OutboxStatus,
    Payment,
    PaymentHistoryEvent,
    PaymentHistoryEventType,
    PaymentStatus,
)
from app.domain.services.history import list_history_events, record_history_event


async def create_payment(
    session: AsyncSession,
    payload: PaymentCreate,
    idempotency_key: str,
) -> Payment:
    request_hash = canonical_request_hash(payload)
    payment_id = uuid.uuid4()
    payment = Payment(
        id=payment_id,
        amount=payload.amount,
        currency=payload.currency,
        description=payload.description,
        metadata_=payload.metadata,
        status=PaymentStatus.pending,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        webhook_url=str(payload.webhook_url),
    )
    event = OutboxEvent(
        payment_id=payment_id,
        event_type=PAYMENTS_NEW_EVENT,
        payload={"payment_id": str(payment_id)},
        status=OutboxStatus.pending,
    )

    session.add(payment)
    session.add(event)
    record_history_event(session, payment_id, PaymentHistoryEventType.created)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        existing = await session.scalar(
            select(Payment).where(Payment.idempotency_key == idempotency_key)
        )
        if existing is None:
            raise
        if existing.request_hash != request_hash:
            raise IdempotencyConflictError(idempotency_key) from None
        return existing

    await session.refresh(payment)
    return payment


async def get_payment(session: AsyncSession, payment_id: uuid.UUID) -> Payment:
    payment = await session.get(Payment, payment_id)
    if payment is None:
        raise PaymentNotFoundError(payment_id)
    return payment


async def get_payment_history(
    session: AsyncSession, payment_id: uuid.UUID
) -> list[PaymentHistoryEvent]:
    await get_payment(session, payment_id)  # 404 if the payment itself doesn't exist
    return await list_history_events(session, payment_id)
