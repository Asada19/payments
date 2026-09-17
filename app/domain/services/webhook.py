from __future__ import annotations

import hashlib
import hmac
import time
from datetime import datetime
from decimal import Decimal
from uuid import UUID

import httpx
from pydantic import BaseModel

from app.core.ssrf_guard import SsrfBlockedError, assert_public_host
from app.domain.models import Currency, PaymentStatus


class WebhookPayload(BaseModel):
    payment_id: UUID
    status: PaymentStatus
    amount: Decimal
    currency: Currency
    processed_at: datetime


class WebhookDeliveryError(Exception):
    pass


def sign_webhook_body(secret: str, timestamp: int, body: bytes) -> str:
    """HMAC-SHA256 over "{timestamp}." + body, hex-encoded.

    Timestamp is part of the signed message (not just a sibling header) so a
    captured signature can't be replayed with a different timestamp. The
    receiver is expected to recompute this with the shared secret and reject
    both a mismatched signature and a stale timestamp (a 5-minute window is a
    common choice) to guard against replay.
    """
    message = f"{timestamp}.".encode() + body
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


async def send_webhook(
    url: str,
    payload: WebhookPayload,
    timeout: float,
    signing_secret: str,
    ssrf_allowed_hosts: frozenset[str],
    client: httpx.AsyncClient | None = None,
) -> None:
    try:
        await assert_public_host(url, ssrf_allowed_hosts)
    except SsrfBlockedError as exc:
        raise WebhookDeliveryError(str(exc)) from exc

    body = payload.model_dump_json().encode("utf-8")
    timestamp = int(time.time())
    signature = sign_webhook_body(signing_secret, timestamp, body)

    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout, connect=min(5.0, timeout))
        )
    try:
        try:
            response = await client.post(
                url,
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Webhook-Timestamp": str(timestamp),
                    "X-Webhook-Signature": signature,
                },
            )
        except httpx.HTTPError as exc:
            raise WebhookDeliveryError(str(exc)) from exc
        if response.status_code >= 300:
            raise WebhookDeliveryError(f"webhook status {response.status_code}")
    finally:
        if owns_client:
            await client.aclose()
