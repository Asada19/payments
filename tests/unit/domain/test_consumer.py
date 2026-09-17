from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from app.domain.models import Currency, PaymentStatus
from app.domain.services import consumer as consumer_service
from app.domain.services.retry import NextAction
from app.events.v1.schemas.payments import PaymentNewEvent


class FakeMessage:
    def __init__(self, headers: dict | None = None) -> None:
        self.headers = headers or {}
        self.message_id = "msg-1"
        self.ack = AsyncMock()
        self.reject = AsyncMock()


class FakeSession:
    def __init__(self, payment) -> None:
        self.payment = payment
        self.rollback = AsyncMock()
        self.commit = AsyncMock()
        self.add = Mock()

    async def get(self, model, pk):
        if self.payment is not None and self.payment.id == pk:
            return self.payment
        return None


def _payment(**overrides):
    data = {
        "id": uuid4(),
        "amount": Decimal("12.00"),
        "currency": Currency.RUB,
        "status": PaymentStatus.pending,
        "webhook_url": "http://api:8000/debug/sink",
        "processed_at": None,
        "webhook_delivered_at": None,
    }
    data.update(overrides)
    return SimpleNamespace(**data)


async def test_missing_payment_rejected_without_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    apply = AsyncMock()
    monkeypatch.setattr(consumer_service, "apply_decision", apply)
    msg = FakeMessage()
    event = PaymentNewEvent(payment_id=uuid4())
    await consumer_service.handle_payment_event(
        event, msg, FakeSession(None), broker=AsyncMock()
    )
    msg.reject.assert_awaited_once()
    msg.ack.assert_not_called()
    apply.assert_not_called()


async def test_gateway_failure_is_final_and_acks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payment = _payment(status=PaymentStatus.pending)
    session = FakeSession(payment)

    async def fake_gateway() -> PaymentStatus:
        return PaymentStatus.failed

    async def fake_claim(session, payment_id, new_status):
        payment.status = new_status
        payment.processed_at = datetime.now(UTC)
        return True

    async def fake_webhook(*args, **kwargs) -> None:
        return None

    async def fake_claim_webhook(session, payment_id) -> bool:
        payment.webhook_delivered_at = datetime.now(UTC)
        return True

    monkeypatch.setattr(consumer_service, "emulate_gateway", fake_gateway)
    monkeypatch.setattr(consumer_service, "claim_payment", fake_claim)
    monkeypatch.setattr(consumer_service, "send_webhook", fake_webhook)
    monkeypatch.setattr(consumer_service, "claim_webhook_delivery", fake_claim_webhook)

    msg = FakeMessage()
    event = PaymentNewEvent(payment_id=payment.id)
    await consumer_service.handle_payment_event(event, msg, session, broker=AsyncMock())
    msg.ack.assert_awaited_once()
    msg.reject.assert_not_called()
    assert payment.status is PaymentStatus.failed


async def test_webhook_failure_schedules_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    payment = _payment(
        status=PaymentStatus.succeeded,
        processed_at=datetime.now(UTC),
    )
    session = FakeSession(payment)
    apply = AsyncMock()
    release = AsyncMock()

    from app.domain.services.webhook import WebhookDeliveryError

    async def failing_webhook(*args, **kwargs) -> None:
        raise WebhookDeliveryError("500")

    async def fake_claim_webhook(session, payment_id) -> bool:
        return True

    monkeypatch.setattr(consumer_service, "send_webhook", failing_webhook)
    monkeypatch.setattr(consumer_service, "apply_decision", apply)
    monkeypatch.setattr(consumer_service, "claim_webhook_delivery", fake_claim_webhook)
    monkeypatch.setattr(consumer_service, "release_webhook_claim", release)

    msg = FakeMessage({"x-retry-count": 0})
    event = PaymentNewEvent(payment_id=payment.id)
    await consumer_service.handle_payment_event(event, msg, session, broker=AsyncMock())
    release.assert_awaited_once_with(session, payment.id)
    apply.assert_awaited_once()
    decision = apply.await_args.args[0]
    assert decision.action is NextAction.RETRY
    assert decision.routing_key == "payments.retry.2s"
    msg.ack.assert_not_called()


async def test_lost_webhook_claim_race_skips_send_and_still_acks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payment = _payment(
        status=PaymentStatus.succeeded,
        processed_at=datetime.now(UTC),
    )
    session = FakeSession(payment)
    webhook = AsyncMock()

    async def fake_claim_webhook(session, payment_id) -> bool:
        # another concurrent handler already claimed (or delivered) it
        return False

    monkeypatch.setattr(consumer_service, "claim_webhook_delivery", fake_claim_webhook)
    monkeypatch.setattr(consumer_service, "send_webhook", webhook)

    msg = FakeMessage()
    event = PaymentNewEvent(payment_id=payment.id)
    await consumer_service.handle_payment_event(event, msg, session, broker=AsyncMock())
    webhook.assert_not_called()
    msg.ack.assert_awaited_once()
    msg.reject.assert_not_called()


async def test_already_delivered_skips_webhook(monkeypatch: pytest.MonkeyPatch) -> None:
    payment = _payment(
        status=PaymentStatus.succeeded,
        processed_at=datetime.now(UTC),
        webhook_delivered_at=datetime.now(UTC),
    )
    webhook = AsyncMock()
    gateway = AsyncMock()
    monkeypatch.setattr(consumer_service, "send_webhook", webhook)
    monkeypatch.setattr(consumer_service, "emulate_gateway", gateway)

    msg = FakeMessage()
    event = PaymentNewEvent(payment_id=payment.id)
    await consumer_service.handle_payment_event(
        event, msg, FakeSession(payment), broker=AsyncMock()
    )
    webhook.assert_not_called()
    gateway.assert_not_called()
    msg.ack.assert_awaited_once()
