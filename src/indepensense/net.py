"""Connectivity probe, shared by everything that needs to know if we're online.

This started as a private method on `PeriodicHeartbeatSender`. The cloud
LLM fallback needs the same answer, and two implementations of "are we
online" would eventually disagree — the heartbeat reporting connected
while the voice pipeline says otherwise would be a confusing thing to
debug from a spoken response.
"""
import sys
from urllib.parse import urlparse

# Hosts where plaintext HTTP never leaves the machine, so there is no hop
# that could read the bearer token. Same carve-out browsers make when they
# treat localhost as a secure context.
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "[::1]"})


def require_https(url: str, what: str) -> None:
    """Raise unless `url` is safe to send a bearer token over.

    The device credential goes in an `Authorization` header on every
    request. Over plaintext HTTP that header is readable by every hop
    between the wearable and the backend, and it is the device's password
    — so this refuses at startup rather than leaking quietly for weeks.

    Loopback is exempt because the traffic never reaches a network.
    Nothing else is: a private or VPN address still traverses hops this
    code cannot verify, and "it's on our network" is how plaintext
    credentials usually get justified.
    """
    parsed = urlparse(url)
    if parsed.scheme == "https":
        return
    if parsed.scheme == "http" and parsed.hostname in _LOOPBACK_HOSTS:
        return
    raise ValueError(
        f"{what} must use https:// — got {url!r}. The device credential is "
        f"sent as a bearer token on every request and would be readable in "
        f"transit. Only http://localhost is exempt."
    )


def probe_internet(url: str, timeout_s: float = 2.0) -> bool:
    """True if an HTTP HEAD to `url` gets any response within the timeout.

    Any response counts as online, including error statuses — a 5xx from
    Cloudflare still means we reached Cloudflare, which means we have
    internet. Only a network-level failure means offline.

    Only `RequestException` is treated as offline. A broader catch would
    also swallow an ImportError from the lazy import below, so a missing
    `requests` install would report the device as permanently offline
    instead of surfacing the real cause.
    """
    import requests  # lazy: keeps the module importable off-device

    try:
        requests.head(url, timeout=timeout_s)
        return True
    except requests.RequestException as exc:
        print(f"[net] probe to {url} failed: {exc}", file=sys.stderr)
        return False
