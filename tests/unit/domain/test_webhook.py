import hashlib
import hmac
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
    sign_webhook_body,
)

SECRET = "test-secret"
NO_HOSTS: frozenset[str] = frozenset()
# example.test never resolves in DNS (RFC 2606) -- allowlist it explicitly so
# these tests exercise send_webhook's HTTP/signing behavior via the mock
# transport, not the SSRF guard's "could not resolve host" path.
MOCK_HOST: frozenset[str] = frozenset({"example.test"})


def _payload() -> WebhookPayload:
    return WebhookPayload(
        payment_id=uuid4(),
        status=PaymentStatus.succeeded,
        amount=Decimal("10.00"),
        currency=Currency.USD,
        processed_at=datetime.now(UTC),
    )


def test_sign_webhook_body_is_deterministic_hmac_sha256() -> None:
    body = b'{"a":1}'
    expected = hmac.new(SECRET.encode(), b"1000." + body, hashlib.sha256).hexdigest()
    assert sign_webhook_body(SECRET, 1000, body) == expected


def test_sign_webhook_body_changes_with_timestamp() -> None:
    body = b'{"a":1}'
    assert sign_webhook_body(SECRET, 1, body) != sign_webhook_body(SECRET, 2, body)


async def test_webhook_success_single_signed_post() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"ok": True})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    await send_webhook(
        "http://example.test/hook",
        _payload(),
        timeout=2,
        signing_secret=SECRET,
        ssrf_allowed_hosts=MOCK_HOST,
        client=client,
    )
    await client.aclose()
    assert len(calls) == 1
    request = calls[0]
    assert request.method == "POST"
    timestamp = int(request.headers["X-Webhook-Timestamp"])
    expected_sig = sign_webhook_body(SECRET, timestamp, request.content)
    assert request.headers["X-Webhook-Signature"] == expected_sig


async def test_webhook_http_error_is_delivery_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"ok": False})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with pytest.raises(WebhookDeliveryError):
        await send_webhook(
            "http://example.test/fail",
            _payload(),
            timeout=2,
            signing_secret=SECRET,
            ssrf_allowed_hosts=MOCK_HOST,
            client=client,
        )
    await client.aclose()


async def test_webhook_timeout_is_delivery_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("slow")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with pytest.raises(WebhookDeliveryError):
        await send_webhook(
            "http://example.test/timeout",
            _payload(),
            timeout=1,
            signing_secret=SECRET,
            ssrf_allowed_hosts=MOCK_HOST,
            client=client,
        )
    await client.aclose()


async def test_webhook_to_private_address_is_blocked_before_any_request() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with pytest.raises(WebhookDeliveryError):
        await send_webhook(
            "http://127.0.0.1:9/hook",
            _payload(),
            timeout=2,
            signing_secret=SECRET,
            ssrf_allowed_hosts=NO_HOSTS,
            client=client,
        )
    await client.aclose()
    assert calls == []


async def test_webhook_to_allowlisted_host_is_not_blocked() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    await send_webhook(
        "http://localhost:9/hook",
        _payload(),
        timeout=2,
        signing_secret=SECRET,
        ssrf_allowed_hosts=frozenset({"localhost"}),
        client=client,
    )
    await client.aclose()
    assert len(calls) == 1
