import os
import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.domain.models import (
    Base,
    Currency,
    Payment,
    PaymentHistoryEvent,
    PaymentHistoryEventType,
    PaymentStatus,
)
from app.domain.services.consumer import (
    claim_payment,
    claim_webhook_delivery,
    release_webhook_claim,
)

pytestmark = pytest.mark.integration


def _database_url() -> str:
    url = os.getenv("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL is not set")
    return url


@pytest.fixture
async def session() -> AsyncSession:
    engine = create_async_engine(_database_url(), pool_pre_ping=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        yield session
    await engine.dispose()


async def _make_payment(session: AsyncSession, **overrides) -> Payment:
    data = {
        "id": uuid.uuid4(),
        "amount": Decimal("10.00"),
        "currency": Currency.USD,
        "status": PaymentStatus.pending,
        "idempotency_key": f"key-{uuid.uuid4()}",
        "request_hash": "hash",
        "webhook_url": "http://api:8000/debug/sink",
    }
    data.update(overrides)
    payment = Payment(**data)
    session.add(payment)
    await session.commit()
    return payment


async def test_claim_payment_only_succeeds_once(session: AsyncSession) -> None:
    payment = await _make_payment(session)

    first = await claim_payment(session, payment.id, PaymentStatus.succeeded)
    second = await claim_payment(session, payment.id, PaymentStatus.failed)

    assert first is True
    assert second is False
    refreshed = await session.get(Payment, payment.id)
    assert refreshed is not None
    assert refreshed.status is PaymentStatus.succeeded  # the second claim never won


async def test_claim_payment_records_exactly_one_history_event(
    session: AsyncSession,
) -> None:
    payment = await _make_payment(session)

    await claim_payment(session, payment.id, PaymentStatus.succeeded)
    await claim_payment(session, payment.id, PaymentStatus.failed)  # loses the race

    events = (
        (
            await session.execute(
                select(PaymentHistoryEvent).where(
                    PaymentHistoryEvent.payment_id == payment.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(events) == 1
    assert events[0].event_type == PaymentHistoryEventType.gateway_succeeded


async def test_webhook_delivery_can_only_be_claimed_once(session: AsyncSession) -> None:
    payment = await _make_payment(
        session, status=PaymentStatus.succeeded, processed_at=datetime.now(UTC)
    )

    first = await claim_webhook_delivery(session, payment.id)
    second = await claim_webhook_delivery(session, payment.id)

    assert first is True
    assert (
        second is False
    )  # this is exactly the double-send race from the outbox report


async def test_releasing_a_claim_allows_reclaiming_for_retry(
    session: AsyncSession,
) -> None:
    payment = await _make_payment(
        session, status=PaymentStatus.succeeded, processed_at=datetime.now(UTC)
    )

    assert await claim_webhook_delivery(session, payment.id) is True
    await release_webhook_claim(session, payment.id)
    assert await claim_webhook_delivery(session, payment.id) is True
