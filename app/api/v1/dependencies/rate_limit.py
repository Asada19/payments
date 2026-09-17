from __future__ import annotations

import time
from collections import defaultdict, deque

from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import Depends, HTTPException, status

from app.api.v1.dependencies.auth import require_api_key
from app.core.config import Settings

_hits: dict[str, deque[float]] = defaultdict(deque)
"""Per-API-key sliding window of request timestamps.

In-memory and per-process: the api service already runs as a single uvicorn
worker (see README), so this doesn't need Redis or any shared store to be
correct. Keyed by API key rather than IP, since that's the identity that's
actually authenticated and the one an idempotency-key exhaustion attack would
need to hold.
"""


def check_rate_limit(cfg: Settings, api_key: str) -> None:
    now = time.monotonic()
    window = _hits[api_key]
    cutoff = now - cfg.rate_limit_window_seconds
    while window and window[0] < cutoff:
        window.popleft()
    if len(window) >= cfg.rate_limit_max_requests:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded",
        )
    window.append(now)


@inject
async def rate_limit(
    cfg: FromDishka[Settings],
    api_key: str = Depends(require_api_key),
) -> None:
    check_rate_limit(cfg, api_key)
