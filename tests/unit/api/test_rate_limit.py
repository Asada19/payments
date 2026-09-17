import pytest
from fastapi import HTTPException

from app.api.v1.dependencies import rate_limit as rate_limit_module
from app.api.v1.dependencies.rate_limit import check_rate_limit
from app.core.config import Settings


@pytest.fixture(autouse=True)
def _clear_hits() -> None:
    rate_limit_module._hits.clear()


def test_allows_requests_within_the_limit() -> None:
    cfg = Settings(rate_limit_window_seconds=60, rate_limit_max_requests=3)
    for _ in range(3):
        check_rate_limit(cfg, api_key="key-a")


def test_blocks_once_limit_is_exceeded() -> None:
    cfg = Settings(rate_limit_window_seconds=60, rate_limit_max_requests=2)
    check_rate_limit(cfg, api_key="key-b")
    check_rate_limit(cfg, api_key="key-b")
    with pytest.raises(HTTPException) as exc_info:
        check_rate_limit(cfg, api_key="key-b")
    assert exc_info.value.status_code == 429


def test_limits_are_tracked_independently_per_api_key() -> None:
    cfg = Settings(rate_limit_window_seconds=60, rate_limit_max_requests=1)
    check_rate_limit(cfg, api_key="key-c")
    check_rate_limit(cfg, api_key="key-d")  # different key, own budget


def test_old_hits_outside_the_window_are_forgotten() -> None:
    cfg = Settings(rate_limit_window_seconds=60, rate_limit_max_requests=1)
    check_rate_limit(cfg, api_key="key-e")
    # simulate the window having fully elapsed
    rate_limit_module._hits["key-e"][0] -= 3600
    check_rate_limit(cfg, api_key="key-e")
