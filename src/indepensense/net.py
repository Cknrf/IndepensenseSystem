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
import socket
import sys
import threading
import time
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


class HostBreaker:
    """Per-host failure memory, so a dead service is skipped rather than
    re-attempted on every utterance.

    The problem this exists for is not slowness, it is that **nothing in
    `requests` bounds DNS resolution**. `socket.create_connection` calls
    `getaddrinfo` before it applies the timeout, so on a link that
    blackholes packets — no route, SIM pulled, carrier dropped — name
    resolution blocks for however long `resolv.conf` says to retry,
    typically 5 s per attempt times two attempts per nameserver. A
    connect timeout of 2 s does not help; it has not started yet.

    Offline, that cost landed three times per utterance: speech-to-text
    and intent parsing on the voice thread, synthesis on the announcer.
    A single command could stall for a minute before any fallback ran,
    which read as the device hanging rather than degrading.

    So the first failure is remembered. For `cooldown_s` afterwards the
    host is presumed down and callers go straight to their local path,
    turning "every utterance is unusable" into "one utterance is slow,
    then the device works offline". The next attempt after the cooldown
    is what reopens it: there is no probe, because a probe would pay the
    same DNS stall this exists to avoid.

    Keyed per host rather than globally. A Mistral outage must not stop
    the device trying its own TTS server, and vice versa — they fail
    independently and only a dead *link* fails both, which the first
    failure of either will discover anyway.
    """

    def __init__(self, cooldown_s: float = 30.0):
        self._cooldown_s = cooldown_s
        self._open_until = 0.0
        self._lock = threading.Lock()

    def allow(self) -> bool:
        """False while the host is presumed down."""
        with self._lock:
            return time.monotonic() >= self._open_until

    def record_success(self) -> None:
        with self._lock:
            self._open_until = 0.0

    def record_failure(self) -> None:
        """One failure is enough.

        Not a counter: the failure mode being defended against is a link
        that is simply gone, where every attempt costs tens of seconds.
        Requiring two failures before protecting the user would mean two
        of those, and the cost of being wrong is only that the device
        runs on its local models for `cooldown_s` — degraded, not broken.
        """
        with self._lock:
            self._open_until = time.monotonic() + self._cooldown_s


_breakers: dict[str, HostBreaker] = {}
_breakers_lock = threading.Lock()


def breaker_for(url: str, cooldown_s: float = 30.0) -> HostBreaker:
    """The breaker for this URL's host, created once and shared.

    Shared across callers of the same host on purpose: the TTS and STT
    endpoints sit on one machine, so a failure reaching one is evidence
    about the other, and sharing means a single stalled call protects
    both for the rest of the cooldown.
    """
    host = urlparse(url).hostname or url
    with _breakers_lock:
        breaker = _breakers.get(host)
        if breaker is None:
            breaker = _breakers[host] = HostBreaker(cooldown_s)
        return breaker


def reset_breakers() -> None:
    """Forget every host's failure state.

    Two callers. The tests, which must not let one case's failure leak
    into the next through module-level state. And anything that learns
    the link is back — a modem reconnect, an interface coming up — where
    waiting out a cooldown that is already stale costs the user a slow
    utterance for no reason.
    """
    with _breakers_lock:
        _breakers.clear()


# RFC 5737 documentation space. Never assigned to a real host, so it
# matches a default route if one exists and nothing else — unlike a
# well-known resolver, which a carrier may blackhole with a specific
# route. See `net.py`'s opening docstring for how that bit us before.
_ROUTE_PROBE_ADDR = ("192.0.2.1", 33434)


def has_network_route() -> bool:
    """True if the kernel can pick a route off this machine.

    **Sends nothing.** `connect()` on a UDP socket transmits no packets;
    it only asks the kernel which interface and source address it would
    use. With no SIM and no WiFi there is no default route, the call
    fails immediately, and the answer costs ~0.2 ms.

    This is the cheap half of staying usable offline. The expensive
    failure is DNS: `socket.create_connection` resolves the hostname
    before it applies any timeout, so on a dead link a lookup blocks for
    however long `resolv.conf` retries — commonly 10-20 s — three times
    per voice command. `HostBreaker` limits that to the *first* command;
    this avoids it even on the first, for the case that actually matters
    in the field, which is having no connection at all.

    Deliberately not a reachability test. A route existing does not mean
    the internet works, and proving that it does would mean sending
    something and waiting — exactly the cost being avoided. The breaker
    covers the route-exists-but-broken case; this covers no-route, and
    between them the only unbounded stall left is the first command on a
    link that is up but silent.

    Unlike the breaker, a false answer here corrects itself instantly:
    there is no cooldown, so the moment the modem reconnects the next
    command uses the cloud again.
    """
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    except OSError:
        return True   # cannot tell; let the caller try rather than refuse
    try:
        probe.settimeout(0.05)
        probe.connect(_ROUTE_PROBE_ADDR)
        return True
    except OSError:
        return False
    finally:
        probe.close()
