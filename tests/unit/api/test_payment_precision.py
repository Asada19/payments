from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.api.v1.schemas.payments import PaymentCreate
from app.domain.models import Currency


def _payload(**overrides) -> dict:
    data = {
        "amount": Decimal("10.50"),
        "currency": Currency.RUB,
        "webhook_url": "http://api:8000/debug/sink",
    }
    data.update(overrides)
    return data


def test_two_decimal_places_accepted_for_rub() -> None:
    payment = PaymentCreate.model_validate(_payload(amount=Decimal("10.50")))
    assert payment.amount == Decimal("10.50")


def test_whole_amount_accepted() -> None:
    payment = PaymentCreate.model_validate(_payload(amount=Decimal("10")))
    assert payment.amount == Decimal("10")


def test_three_decimal_places_rejected_for_currency_with_two() -> None:
    with pytest.raises(ValidationError):
        PaymentCreate.model_validate(_payload(amount=Decimal("10.501")))


@pytest.mark.parametrize("currency", [Currency.RUB, Currency.USD, Currency.EUR])
def test_three_decimal_places_rejected_for_every_supported_currency(currency) -> None:
    with pytest.raises(ValidationError):
        PaymentCreate.model_validate(
            _payload(amount=Decimal("1.234"), currency=currency)
        )
