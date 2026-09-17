from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import httpx
import pytest

from app.domain.models import Currency, PaymentStatus
from app.domain.services.webhook import (
    WebhookDeliveryError,
    WebhookPayload,
    send_webhook,
)


def _payload() -> WebhookPayload:
    return WebhookPayload(
        payment_id=uuid4(),
        status=PaymentStatus.succeeded,
        amount=Decimal("10.00"),
        currency=Currency.USD,
        processed_at=datetime.now(UTC),
    )


async def test_webhook_success_single_post() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"ok": True})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    await send_webhook("http://example.test/hook", _payload(), timeout=2, client=client)
    await client.aclose()
    assert len(calls) == 1
    assert calls[0].method == "POST"


async def test_webhook_http_error_is_delivery_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"ok": False})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with pytest.raises(WebhookDeliveryError):
        await send_webhook(
            "http://example.test/fail", _payload(), timeout=2, client=client
        )
    await client.aclose()


async def test_webhook_timeout_is_delivery_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("slow")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with pytest.raises(WebhookDeliveryError):
        await send_webhook(
            "http://example.test/timeout", _payload(), timeout=1, client=client
        )
    await client.aclose()
