from __future__ import annotations

import hashlib
import json
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

from app.domain.models import (
    CURRENCY_DECIMAL_PLACES,
    Currency,
    PaymentHistoryEventType,
    PaymentStatus,
)


class PaymentCreate(BaseModel):
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=3)
    currency: Currency
    description: str | None = None
    metadata: dict[str, Any] | None = None
    webhook_url: HttpUrl

    @model_validator(mode="after")
    def _validate_amount_precision(self) -> PaymentCreate:
        allowed = CURRENCY_DECIMAL_PLACES[self.currency]
        raw_exponent = self.amount.as_tuple().exponent
        if not isinstance(raw_exponent, int):
            raise ValueError("amount must be a finite number")
        if -raw_exponent > allowed:
            raise ValueError(
                f"{self.currency.value} supports at most {allowed} decimal place(s)"
            )
        return self


class PaymentAccepted(BaseModel):
    payment_id: UUID
    status: PaymentStatus
    created_at: datetime


class PaymentOut(BaseModel):
    payment_id: UUID
    amount: Decimal
    currency: Currency
    description: str | None
    metadata: dict[str, Any] | None = None
    status: PaymentStatus
    webhook_url: str
    created_at: datetime
    processed_at: datetime | None
    webhook_delivered_at: datetime | None


class PaymentHistoryEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    event_type: PaymentHistoryEventType
    detail: dict[str, Any] | None
    created_at: datetime


def canonical_request_hash(payload: PaymentCreate) -> str:
    body = {
        "amount": str(payload.amount),
        "currency": payload.currency.value,
        "description": payload.description,
        "metadata": payload.metadata,
        "webhook_url": str(payload.webhook_url),
    }
    encoded = json.dumps(
        body,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
