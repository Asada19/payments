from __future__ import annotations

from typing import Annotated
from uuid import UUID

from dishka import FromDishka
from dishka.integrations.fastapi import DishkaRoute
from fastapi import APIRouter, Depends, Header, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies.auth import require_api_key
from app.api.v1.schemas.payments import PaymentAccepted, PaymentCreate, PaymentOut
from app.domain.services.payments import create_payment, get_payment

router = APIRouter(
    prefix="/api/v1/payments", tags=["payments"], route_class=DishkaRoute
)
IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=1)]


@router.post(
    "",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=PaymentAccepted,
    dependencies=[Depends(require_api_key)],
)
async def create_payment_endpoint(
    payload: PaymentCreate,
    session: FromDishka[AsyncSession],
    idempotency_key: IdempotencyKey,
) -> PaymentAccepted:
    payment = await create_payment(session, payload, idempotency_key)
    return PaymentAccepted(
        payment_id=payment.id,
        status=payment.status,
        created_at=payment.created_at,
    )


@router.get(
    "/{payment_id}",
    response_model=PaymentOut,
    dependencies=[Depends(require_api_key)],
)
async def get_payment_endpoint(
    payment_id: UUID,
    session: FromDishka[AsyncSession],
) -> PaymentOut:
    payment = await get_payment(session, payment_id)
    return PaymentOut(
        payment_id=payment.id,
        amount=payment.amount,
        currency=payment.currency,
        description=payment.description,
        metadata=payment.metadata_,
        status=payment.status,
        webhook_url=payment.webhook_url,
        created_at=payment.created_at,
        processed_at=payment.processed_at,
        webhook_delivered_at=payment.webhook_delivered_at,
    )
