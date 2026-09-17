import os
import uuid
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.v1.schemas.payments import PaymentCreate
from app.domain.errors import IdempotencyConflictError
from app.domain.models import Base, Currency
from app.domain.services.payments import create_payment

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


def _payload(**overrides) -> PaymentCreate:
    data = {
        "amount": Decimal("15.00"),
        "currency": Currency.EUR,
        "description": "integration",
        "metadata": {"k": "v"},
        "webhook_url": "http://api:8000/debug/sink",
    }
    data.update(overrides)
    return PaymentCreate.model_validate(data)


async def test_create_is_idempotent(session: AsyncSession) -> None:
    key = f"key-same-{uuid.uuid4()}"
    first = await create_payment(session, _payload(), key)
    second = await create_payment(session, _payload(), key)
    assert first.id == second.id


async def test_same_key_different_body_conflicts(session: AsyncSession) -> None:
    key = f"key-conflict-{uuid.uuid4()}"
    await create_payment(session, _payload(), key)
    with pytest.raises(IdempotencyConflictError):
        await create_payment(
            session,
            _payload(amount=Decimal("16.00")),
            key,
        )
