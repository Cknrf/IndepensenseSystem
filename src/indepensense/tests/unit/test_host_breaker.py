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
