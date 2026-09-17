from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from typing import Any

from dishka.integrations.fastapi import setup_dishka
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from faststream.rabbit import RabbitBroker
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.v1.endpoints.payments import router as payments_router
from app.api.v1.error_handlers import register_error_handlers
from app.core.config import Settings, get_settings
from app.core.di import build_api_container
from app.core.logging import setup_logging
from app.domain.services.outbox import run_relay_loop

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    setup_logging()
    container = app.state.dishka_container
    broker = await container.get(RabbitBroker)
    session_factory = await container.get(async_sessionmaker[AsyncSession])
    settings = await container.get(Settings)

    stop = asyncio.Event()
    relay_task = asyncio.create_task(
        run_relay_loop(broker, session_factory, settings, stop), name="outbox-relay"
    )
    try:
        yield
    finally:
        stop.set()
        relay_task.cancel()
        with suppress(asyncio.CancelledError):
            await relay_task
        await container.close()


def create_app() -> FastAPI:
    app = FastAPI(title="Payment processing service", lifespan=lifespan)
    setup_dishka(build_api_container(get_settings()), app)
    register_error_handlers(app)
    app.include_router(payments_router)

    @app.get("/healthz", tags=["ops"])
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/debug/sink", tags=["debug"])
    async def debug_sink(request: Request) -> dict[str, str]:
        body: Any
        try:
            body = await request.json()
        except Exception:
            body = (await request.body()).decode("utf-8", errors="replace")
        logger.info("debug sink received body=%s", body)
        return {"status": "ok"}

    @app.post("/debug/fail", tags=["debug"])
    async def debug_fail() -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"status": "error"},
        )

    return app


app = create_app()
