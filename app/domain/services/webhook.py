from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

import httpx
from pydantic import BaseModel

from app.domain.models import Currency, PaymentStatus


class WebhookPayload(BaseModel):
    payment_id: UUID
    status: PaymentStatus
    amount: Decimal
    currency: Currency
    processed_at: datetime


class WebhookDeliveryError(Exception):
    pass


async def send_webhook(
    url: str,
    payload: WebhookPayload,
    timeout: float,
    client: httpx.AsyncClient | None = None,
) -> None:
    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout, connect=min(5.0, timeout))
        )
    try:
        try:
            response = await client.post(url, json=payload.model_dump(mode="json"))
        except httpx.HTTPError as exc:
            raise WebhookDeliveryError(str(exc)) from exc
        if response.status_code >= 300:
            raise WebhookDeliveryError(f"webhook status {response.status_code}")
    finally:
        if owns_client:
            await client.aclose()
