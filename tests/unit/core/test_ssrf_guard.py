import pytest

from app.core.ssrf_guard import SsrfBlockedError, assert_public_host


async def test_loopback_address_is_blocked() -> None:
    with pytest.raises(SsrfBlockedError):
        await assert_public_host("http://127.0.0.1:9/", frozenset())


async def test_loopback_hostname_is_blocked() -> None:
    with pytest.raises(SsrfBlockedError):
        await assert_public_host("http://localhost:9/", frozenset())


async def test_link_local_metadata_address_is_blocked() -> None:
    with pytest.raises(SsrfBlockedError):
        await assert_public_host(
            "http://169.254.169.254/latest/meta-data/", frozenset()
        )


async def test_private_rfc1918_address_is_blocked() -> None:
    with pytest.raises(SsrfBlockedError):
        await assert_public_host("http://10.0.0.5:8000/hook", frozenset())


async def test_url_without_hostname_is_blocked() -> None:
    with pytest.raises(SsrfBlockedError):
        await assert_public_host("not-a-url", frozenset())


async def test_allowlisted_host_skips_resolution_entirely() -> None:
    # "api" doesn't resolve on the test host at all -- if the allowlist check
    # didn't short-circuit before DNS resolution, this would raise.
    await assert_public_host("http://api:8000/debug/sink", frozenset({"api"}))


async def test_unresolvable_host_is_blocked() -> None:
    with pytest.raises(SsrfBlockedError):
        await assert_public_host(
            "http://this-host-does-not-exist.invalid/hook", frozenset()
        )
