"""Keep retry backoff out of the clock for telemetry unit tests.

Both the HTTP client and the SMS notifier retry with real `time.sleep`
between attempts. Left alone, the suite pays for them: four `test_auth`
cases sat at 3.5 s each proving that a 404 is *not* retried, and the
whole run went from 22 s to 52 s when the retries landed.

A test that sleeps through a backoff spends seconds asserting what a
call counter already knows. This is the same rule `CLAUDE.md` states for
the network — *"otherwise the suite passes or fails depending on whether
the dev machine is online, and stalls for the timeout when it isn't"* —
with a different clock.

Autouse, because correctness here must not depend on each new test file
remembering. Tests that specifically exercise timing override these
locally by passing explicit values to the constructor.
"""
import pytest

from indepensense.telemetry import nestjs_client, sms_alerts


@pytest.fixture(autouse=True)
def _fast_retries(monkeypatch):
    # Zero, not merely small: these schedules exist to space out real
    # modems and real networks, and no assertion in this directory is
    # about how long the gap was.
    monkeypatch.setattr(nestjs_client, "_BACKOFF_DELAYS_S", [0.0, 0.0, 0.0])
    monkeypatch.setattr(sms_alerts, "SMS_ATTEMPT_DELAYS_S", (0.0, 0.0, 0.0))
    monkeypatch.setattr(sms_alerts, "SMS_REPORT_DEADLINE_S", 5.0)
    # The background window keeps a daemon thread alive past the test
    # that started it. Left at five minutes, a few hundred of them
    # accumulate across a run, each waking every fifteen seconds.
    monkeypatch.setattr(sms_alerts, "SMS_RETRY_WINDOW_S", 0.0)
    monkeypatch.setattr(sms_alerts, "SMS_RETRY_BACKOFF_S", ())
