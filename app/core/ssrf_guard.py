from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit


class SsrfBlockedError(Exception):
    pass


def _is_unsafe_address(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


async def assert_public_host(url: str, allowed_hosts: frozenset[str]) -> None:
    """Reject a URL whose host resolves to a private/loopback/link-local/reserved
    address, so a user-supplied webhook_url can't be used to probe internal
    services or cloud metadata endpoints (169.254.169.254 and friends).

    Resolves and checks on every call, not just at registration time, since a
    hostname's DNS record can change after the payment is created (DNS rebinding).
    ``allowed_hosts`` is an explicit exception list for known-safe internal
    hostnames (e.g. this project's own docker-compose demo receiver).
    """
    hostname = urlsplit(url).hostname
    if not hostname:
        raise SsrfBlockedError(f"webhook url has no hostname: {url}")
    if hostname in allowed_hosts:
        return

    loop = asyncio.get_running_loop()
    try:
        resolved = await loop.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise SsrfBlockedError(
            f"could not resolve webhook host {hostname!r}: {exc}"
        ) from exc

    for *_rest, sockaddr in resolved:
        ip = ipaddress.ip_address(sockaddr[0])
        if _is_unsafe_address(ip):
            raise SsrfBlockedError(
                f"webhook host {hostname!r} resolves to non-public address {ip}"
            )
