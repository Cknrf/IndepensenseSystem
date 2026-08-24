"""Connectivity probe, shared by everything that needs to know if we're online.

This started as a private method on `PeriodicHeartbeatSender`. The cloud
LLM fallback needs the same answer, and two implementations of "are we
online" would eventually disagree — the heartbeat reporting connected
while the voice pipeline says otherwise would be a confusing thing to
debug from a spoken response.
"""
import sys


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
