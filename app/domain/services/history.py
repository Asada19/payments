from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import PaymentHistoryEvent, PaymentHistoryEventType


def record_history_event(
    session: AsyncSession,
    payment_id: UUID,
    event_type: PaymentHistoryEventType,
    detail: dict[str, Any] | None = None,
) -> None:
    """Stage an append-only history row. Caller commits as part of its own
    transaction, so the event lands atomically with the state change it
    describes."""
    session.add(
        PaymentHistoryEvent(payment_id=payment_id, event_type=event_type, detail=detail)
    )


async def list_history_events(
    session: AsyncSession, payment_id: UUID
) -> list[PaymentHistoryEvent]:
    result = await session.execute(
        select(PaymentHistoryEvent)
        .where(PaymentHistoryEvent.payment_id == payment_id)
        .order_by(PaymentHistoryEvent.created_at)
    )
    return list(result.scalars().all())
