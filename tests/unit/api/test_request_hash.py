from decimal import Decimal

from app.api.v1.schemas.payments import PaymentCreate, canonical_request_hash
from app.domain.models import Currency


def _payload(**overrides) -> PaymentCreate:
    data = {
        "amount": Decimal("10.50"),
        "currency": Currency.RUB,
        "description": "test",
        "metadata": {"order": "1"},
        "webhook_url": "http://api:8000/debug/sink",
    }
    data.update(overrides)
    return PaymentCreate.model_validate(data)


def test_same_body_same_hash() -> None:
    assert canonical_request_hash(_payload()) == canonical_request_hash(_payload())


def test_different_amount_changes_hash() -> None:
    left = canonical_request_hash(_payload())
    right = canonical_request_hash(_payload(amount=Decimal("10.51")))
    assert left != right


def test_metadata_order_does_not_change_hash() -> None:
    a = _payload(metadata={"a": 1, "b": 2})
    b = _payload(metadata={"b": 2, "a": 1})
    assert canonical_request_hash(a) == canonical_request_hash(b)
