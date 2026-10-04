"""Reachability probe, shared by everything that needs to know if a host
it depends on is currently answering.

This started as a private method on `PeriodicHeartbeatSender`. The cloud
LLM fallback needs the same mechanism, and two implementations would
eventually disagree — the heartbeat reporting connected while the voice
pipeline says otherwise would be a confusing thing to debug from a
spoken response. One function, parameterised by target, keeps that from
happening while letting each caller name the host it actually needs.

Each caller probes its own dependency rather than a neutral reference
point, and that is a correction, not the original design. This used to
HEAD `http://1.1.1.1` on the theory that a well-known third party is a
more honest signal than any one endpoint. On the SIM7600 carrier the
device actually deploys on, `1.1.1.1` is null-routed on every port —
as is `8.8.8.8`, while Cloudflare's own `1.0.0.1` answers fine. Carriers
filter well-known public resolvers to keep subscribers on their DNS, and
`1.1.1.1` was squatted as an internal address for years before Cloudflare
ran it. The result was a wearable with working HTTPS to two hosts telling
its user "I need an internet connection", and a guardian dashboard
recording `internet_status: false` for a device that was never offline.

The lesson is narrow: the best predictor of "can I reach X" is X. A
third-party target adds a dependency that can fail on its own, and when
it does the error is silent in one caller and a spoken refusal in the
other.
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


def probe_reachable(url: str, timeout_s: float = 2.0) -> bool:
    """True if an HTTP HEAD to `url` gets any response within the timeout.

    Any response counts as reachable, including error statuses — a 401
    from Mistral or a 404 from the backend still means the request
    arrived and was answered, which is the whole question. Only a
    network-level failure counts as unreachable. Callers therefore do
    not need an endpoint that returns 200 to an unauthenticated HEAD,
    which is just as well: neither of ours does.

    Only `RequestException` is treated as unreachable. A broader catch
    would also swallow an ImportError from the lazy import below, so a
    missing `requests` install would report the host as permanently
    unreachable instead of surfacing the real cause.
    """
    import requests  # lazy: keeps the module importable off-device

    try:
        requests.head(url, timeout=timeout_s)
        return True
    except requests.RequestException as exc:
        print(f"[net] probe to {url} failed: {exc}", file=sys.stderr)
        return False
