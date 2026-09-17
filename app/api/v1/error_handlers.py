from __future__ import annotations

import logging

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.domain.errors import IdempotencyConflictError, PaymentNotFoundError

logger = logging.getLogger(__name__)


async def payment_not_found_handler(
    _request: Request, exc: PaymentNotFoundError
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content={"detail": str(exc)},
    )


async def idempotency_conflict_handler(
    _request: Request, exc: IdempotencyConflictError
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={"detail": str(exc)},
    )


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(
        PaymentNotFoundError,
        payment_not_found_handler,  # type: ignore[arg-type]
    )
    app.add_exception_handler(
        IdempotencyConflictError,
        idempotency_conflict_handler,  # type: ignore[arg-type]
    )
