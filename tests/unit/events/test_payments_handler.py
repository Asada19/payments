from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.events.v1.handlers import payments_handler as handler_module
from app.events.v1.handlers.payments_handler import payments_new_handler


class FakeMessage:
    def __init__(self, body: dict) -> None:
        self._body = body
        self.message_id = "msg-1"
        self.ack = AsyncMock()
        self.reject = AsyncMock()

    async def decode(self) -> dict:
        return self._body


async def test_malformed_message_is_rejected_without_touching_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handle = AsyncMock()
    monkeypatch.setattr(handler_module, "handle_payment_event", handle)

    msg = FakeMessage({"garbage": True})
    await payments_new_handler(msg, session=AsyncMock(), broker=AsyncMock())

    msg.reject.assert_awaited_once()
    msg.ack.assert_not_called()
    handle.assert_not_called()


async def test_valid_message_is_delegated_to_handle_payment_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handle = AsyncMock()
    monkeypatch.setattr(handler_module, "handle_payment_event", handle)

    payment_id = uuid4()
    msg = FakeMessage({"payment_id": str(payment_id)})
    session = AsyncMock()
    broker = AsyncMock()
    await payments_new_handler(msg, session=session, broker=broker)

    handle.assert_awaited_once_with(handle.await_args.args[0], msg, session, broker)
    assert handle.await_args.args[0].payment_id == payment_id
    msg.reject.assert_not_called()
