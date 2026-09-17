from __future__ import annotations

from dishka_faststream import setup_dishka
from faststream import FastStream

from app.core.broker import build_broker, setup_topology
from app.core.config import get_settings
from app.core.di import build_worker_container
from app.core.logging import setup_logging
from app.events.v1.handlers.payments_handler import initialize_payments_router

setup_logging()
settings = get_settings()

broker = build_broker(settings.rabbitmq_url, prefetch=settings.consumer_prefetch_count)
broker.include_router(initialize_payments_router(settings))

app = FastStream(broker)

setup_dishka(
    build_worker_container(settings, broker),
    app=app,
    auto_inject=True,
    finalize_container=True,
)


@app.after_startup
async def declare_topology() -> None:
    await setup_topology(broker)


if __name__ == "__main__":
    import asyncio

    asyncio.run(app.run())
