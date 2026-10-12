"""The per-host circuit breaker that keeps an offline device usable.

The defect this exists for is specific: **nothing in `requests` bounds
DNS resolution.** `socket.create_connection` calls `getaddrinfo` before
it applies the timeout, so on a link that blackholes packets — SIM
pulled, carrier dropped, WiFi off — name resolution blocks for whatever
`resolv.conf` says to retry, commonly 5 s per attempt times two attempts
per nameserver. A 2 s connect timeout does not help; it has not started.

Offline, that cost landed three times per utterance: STT and NLU on the
voice thread, TTS on the announcer. One command could stall for a minute
before any fallback ran, which reads as a hang rather than degradation.
"""
import pytest

from indepensense import net


@pytest.fixture
def breaker():
    return net.HostBreaker(cooldown_s=30.0)


def test_a_fresh_breaker_allows(breaker):
    assert breaker.allow()


def test_one_failure_is_enough_to_stop_trying(breaker):
    """Not a counter. The failure mode is a link that is simply gone,
    where every attempt costs tens of seconds — requiring a second
    failure before protecting the user would mean a second stall."""
    breaker.record_failure()

    assert not breaker.allow()


def test_the_cooldown_expires(breaker, monkeypatch):
    """The next attempt after the cooldown is what reopens it. There is
    no probe, because a probe would pay the same DNS stall this exists
    to avoid."""
    clock = [1000.0]
    monkeypatch.setattr(net.time, "monotonic", lambda: clock[0])

    breaker.record_failure()
    assert not breaker.allow()

    clock[0] += 29.0
    assert not breaker.allow()

    clock[0] += 2.0
    assert breaker.allow()


def test_success_clears_it_immediately(breaker):
    breaker.record_failure()
    breaker.record_success()

    assert breaker.allow()


# --- the registry -------------------------------------------------------------

def test_the_same_host_shares_one_breaker():
    """TTS and STT sit on one machine on different ports. A failure
    reaching either is evidence about both, and sharing means a single
    stalled call protects the rest of the utterance."""
    a = net.breaker_for("https://gpuer.example:8700/tts")
    b = net.breaker_for("https://gpuer.example:8710/stt")

    assert a is b


def test_different_hosts_do_not_share():
    """A Mistral outage must not stop the device trying its own TTS
    server. Only a dead link fails both, and the first failure of either
    discovers that anyway."""
    a = net.breaker_for("https://gpuer.example:8700/tts")
    b = net.breaker_for("https://api.mistral.ai/v1/chat/completions")

    a.record_failure()

    assert not a.allow()
    assert b.allow()


def test_reset_forgets_everything():
    """Used when the link is known to be back — a modem reconnect —
    where waiting out a stale cooldown costs a slow utterance for
    nothing."""
    net.breaker_for("https://gpuer.example:8700/tts").record_failure()
    net.reset_breakers()

    assert net.breaker_for("https://gpuer.example:8700/tts").allow()


# --- the no-route short circuit -----------------------------------------------

def test_the_route_check_sends_nothing_and_is_fast():
    """A UDP connect() transmits no packets — it only asks the kernel
    which interface it would use. That is what makes it usable on the
    voice thread before every cloud call."""
    import time

    t = time.perf_counter()
    net.has_network_route()
    elapsed_ms = (time.perf_counter() - t) * 1000

    assert elapsed_ms < 50, f"took {elapsed_ms:.1f} ms; must be negligible"


def test_no_route_is_reported_as_no_route(monkeypatch):
    """With no SIM and no WiFi the kernel has no default route and
    connect() fails immediately — the case that hung the device."""
    class _NoRoute:
        def settimeout(self, _): pass
        def connect(self, _): raise OSError(101, "Network is unreachable")
        def close(self): pass

    monkeypatch.setattr(net.socket, "socket", lambda *a, **kw: _NoRoute())

    assert net.has_network_route() is False


def test_an_unusable_socket_layer_does_not_refuse_the_call(monkeypatch):
    """If the check itself cannot run, let the caller try rather than
    deciding on its behalf that the network is down — a broken probe
    must not become a broken device."""
    def _boom(*a, **kw):
        raise OSError("no sockets today")

    monkeypatch.setattr(net.socket, "socket", _boom)

    assert net.has_network_route() is True


def test_the_route_check_has_no_cooldown(monkeypatch):
    """Unlike the breaker, this corrects itself instantly: the moment the
    modem reconnects the next command uses the cloud again, with no 30 s
    wait."""
    state = {"up": False}

    class _Sock:
        def settimeout(self, _): pass
        def connect(self, _):
            if not state["up"]:
                raise OSError(101, "Network is unreachable")
        def close(self): pass

    monkeypatch.setattr(net.socket, "socket", lambda *a, **kw: _Sock())

    assert net.has_network_route() is False
    state["up"] = True
    assert net.has_network_route() is True
