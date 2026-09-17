from __future__ import annotations

import asyncio
import random

from app.core.config import get_settings
from app.domain.models import PaymentStatus


async def emulate_gateway(
    *,
    min_delay: float | None = None,
    max_delay: float | None = None,
    success_rate: float | None = None,
) -> PaymentStatus:
    cfg = get_settings()
    await asyncio.sleep(
        random.uniform(
            min_delay if min_delay is not None else cfg.gateway_min_delay_seconds,
            max_delay if max_delay is not None else cfg.gateway_max_delay_seconds,
        )
    )
    rate = success_rate if success_rate is not None else cfg.gateway_success_rate
    if random.random() < rate:
        return PaymentStatus.succeeded
    return PaymentStatus.failed
