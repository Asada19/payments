from __future__ import annotations

from uuid import UUID


class PaymentError(Exception):
    """Base for domain-level payment errors."""


class PaymentNotFoundError(PaymentError):
    def __init__(self, payment_id: UUID) -> None:
        self.payment_id = payment_id
        super().__init__(f"Payment {payment_id} not found")


class IdempotencyConflictError(PaymentError):
    def __init__(self, idempotency_key: str) -> None:
        self.idempotency_key = idempotency_key
        super().__init__(
            f"Idempotency-Key {idempotency_key!r} already used "
            "with a different request body"
        )
