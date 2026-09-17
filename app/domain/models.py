from __future__ import annotations

import enum
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Currency(enum.StrEnum):
    RUB = "RUB"
    USD = "USD"
    EUR = "EUR"


CURRENCY_DECIMAL_PLACES: dict[Currency, int] = {
    Currency.RUB: 2,
    Currency.USD: 2,
    Currency.EUR: 2,
}
"""Minor-unit precision per currency (ISO 4217 exponent).

Kept explicit and per-currency rather than a single global constant: RUB/USD/EUR
are all 2 today, but currencies like JPY (0) or KWD (3) would silently corrupt
amounts under a single hardcoded ``decimal_places``.
"""


class PaymentStatus(enum.StrEnum):
    pending = "pending"
    succeeded = "succeeded"
    failed = "failed"


class OutboxStatus(enum.StrEnum):
    pending = "pending"
    published = "published"


class PaymentHistoryEventType(enum.StrEnum):
    created = "created"
    gateway_succeeded = "gateway_succeeded"
    gateway_failed = "gateway_failed"
    webhook_delivered = "webhook_delivered"
    webhook_delivery_failed = "webhook_delivery_failed"


def _enum_values(enum_cls: type[enum.Enum]) -> list[str]:
    return [item.value for item in enum_cls]


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_payments_amount_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[Currency] = mapped_column(
        Enum(
            Currency,
            native_enum=False,
            length=3,
            values_callable=_enum_values,
        ),
        nullable=False,
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata", JSONB, nullable=True
    )
    status: Mapped[PaymentStatus] = mapped_column(
        Enum(
            PaymentStatus,
            native_enum=False,
            length=16,
            values_callable=_enum_values,
        ),
        nullable=False,
        default=PaymentStatus.pending,
    )
    idempotency_key: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False
    )
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    webhook_url: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    webhook_delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    outbox_events: Mapped[list[OutboxEvent]] = relationship(back_populates="payment")


class OutboxEvent(Base):
    __tablename__ = "outbox"
    __table_args__ = (Index("ix_outbox_status_created_at", "status", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    payment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("payments.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[OutboxStatus] = mapped_column(
        Enum(
            OutboxStatus,
            native_enum=False,
            length=16,
            values_callable=_enum_values,
        ),
        nullable=False,
        default=OutboxStatus.pending,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    payment: Mapped[Payment] = relationship(back_populates="outbox_events")


class PaymentHistoryEvent(Base):
    """Append-only audit trail of everything that happened to a payment.

    Rows are never updated or deleted -- ``payments`` holds current state,
    this table holds the history of how it got there (regulators expect a
    write-once record of state transitions, not just the final status).
    """

    __tablename__ = "payment_history"
    __table_args__ = (
        Index("ix_payment_history_payment_id_created_at", "payment_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    payment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("payments.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_type: Mapped[PaymentHistoryEventType] = mapped_column(
        Enum(
            PaymentHistoryEventType,
            native_enum=False,
            length=32,
            values_callable=_enum_values,
        ),
        nullable=False,
    )
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


PAYMENTS_NEW_EVENT = "payments.new"
