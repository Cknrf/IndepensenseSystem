"""Unit tests for backend authentication and the 401 retry policy.

The policy is the point. Everything else in this layer retries every
10 seconds; a 401 cannot be fixed by retrying, so doing that would hammer
the backend forever with a request that can never succeed.
"""
import time
from datetime import datetime, timezone

import pytest
import requests

from indepensense.conftest import TEST_BACKEND_URL, make_credential
from indepensense.telemetry.base import (
    AlertEvent,
    DeviceCredentialRejected,
    EventType,
    IntervalInformation,
)
from indepensense.telemetry.buffered import BufferedTelemetryClient
from indepensense.telemetry.nestjs_client import NestJSTelemetryClient

_AT = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)


def _alert():
    return AlertEvent(
        device_id="dev", event_type=EventType.FALL_DETECTION,
        latitude=14.6, longitude=120.9, occurred_at=_AT,
    )


def _heartbeat():
    return IntervalInformation(
        device_id="dev", battery_health=88, internet_status=True,
        latitude=14.6, longitude=120.9, created_at=_AT,
    )


def _client(**kwargs):
    return NestJSTelemetryClient(
        base_url=TEST_BACKEND_URL, credential=make_credential(), **kwargs,
    )


def _capture(monkeypatch, status_code=201, body=""):
    """Patch requests.post and record what was sent."""
    sent = {}

    def _post(url, json=None, headers=None, timeout=None):
        sent["url"] = url
        sent["json"] = json
        sent["headers"] = headers
        response = requests.Response()
        response.status_code = status_code
        response._content = body.encode()
        return response

    monkeypatch.setattr(requests, "post", _post)
    return sent


def _wait_until(condition, timeout_s=2.0):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if condition():
            return True
        time.sleep(0.01)
    return False


# --- the request -------------------------------------------------------------

def test_the_credential_is_sent_as_a_bearer_token(monkeypatch):
    sent = _capture(monkeypatch)
    credential = make_credential()
    NestJSTelemetryClient(
        base_url=TEST_BACKEND_URL, credential=credential,
    ).send_alert(_alert())

    assert sent["headers"]["Authorization"] == f"Bearer {credential.token}"


def test_the_credential_is_not_in_the_url_or_body(monkeypatch):
    """It is a password. In a URL it lands in access logs and proxy logs."""
    sent = _capture(monkeypatch)
    credential = make_credential()
    NestJSTelemetryClient(
        base_url=TEST_BACKEND_URL, credential=credential,
    ).send_alert(_alert())

    assert credential.token not in sent["url"]
    assert credential.token not in str(sent["json"])


def test_the_guardian_path_has_no_device_id(monkeypatch):
    """`GET /raspberry/guardians` — the id used to be in the path, which
    meant anyone could request any device's guardian phone numbers by
    guessing a UUID."""
    from indepensense.telemetry.guardians import GuardianDirectory

    seen = {}

    def _get(url, headers=None, timeout=None):
        seen["url"] = url
        seen["headers"] = headers
        raise requests.ConnectionError("stop here, we only wanted the URL")

    monkeypatch.setattr(requests, "get", _get)
    GuardianDirectory(
        base_url=TEST_BACKEND_URL,
        credential=make_credential(),
        cache_path=__import__("pathlib").Path("/nonexistent/guardians.json"),
    ).refresh()

    assert seen["url"] == f"{TEST_BACKEND_URL}/raspberry/guardians"
    assert seen["headers"]["Authorization"].startswith("Bearer ")


# --- construction ------------------------------------------------------------

def test_plaintext_backend_url_is_refused():
    """Refuse at startup rather than leak the token quietly for weeks."""
    with pytest.raises(ValueError, match="https"):
        NestJSTelemetryClient(
            base_url="http://backend.example.com", credential=make_credential(),
        )


# --- 401 ---------------------------------------------------------------------

def test_a_401_raises_rather_than_returning_false(monkeypatch):
    """A boolean would put this in the same bucket as "network was down",
    and the retry policy for the two is completely different."""
    _capture(monkeypatch, status_code=401, body='{"message":"invalid device credential"}')

    with pytest.raises(DeviceCredentialRejected):
        _client().send_alert(_alert())


def test_a_401_on_heartbeat_also_raises(monkeypatch):
    _capture(monkeypatch, status_code=401)
    with pytest.raises(DeviceCredentialRejected):
        _client().send_heartbeat(_heartbeat())


def test_the_rejection_names_the_device_not_the_secret(monkeypatch):
    """The UUID is what a human quotes to get a unit un-revoked. The
    secret must not appear."""
    _capture(monkeypatch, status_code=401)
    credential = make_credential()
    client = NestJSTelemetryClient(
        base_url=TEST_BACKEND_URL, credential=credential,
    )

    with pytest.raises(DeviceCredentialRejected) as caught:
        client.send_alert(_alert())

    message = str(caught.value)
    assert credential.device_id in message
    assert credential.token not in message


@pytest.mark.parametrize("status", [400, 404, 500, 503])
def test_other_failures_still_return_false(monkeypatch, status):
    """400 means authenticated but not yet linked to an assisted user —
    normal on a fresh unit, and worth retrying. 5xx is transient."""
    _capture(monkeypatch, status_code=status, body="unknown or unlinked device")
    assert _client().send_alert(_alert()) is False


# --- the retry policy --------------------------------------------------------

class _RejectingClient:
    """Raises DeviceCredentialRejected until `accept` is set."""

    def __init__(self):
        self.attempts = 0
        self.accept = False

    def send_alert(self, event):
        self.attempts += 1
        if self.accept:
            return True
        raise DeviceCredentialRejected("revoked")

    def send_heartbeat(self, info):
        return self.send_alert(info)


def test_a_rejection_is_flagged_distinctly_from_no_network():
    """So nobody spends an afternoon debugging the cellular link over a
    revoked key."""
    inner = _RejectingClient()
    buffered = BufferedTelemetryClient(
        inner, retry_interval_s=0.01, auth_retry_interval_s=0.05,
    )
    try:
        buffered.send_alert(_alert())
        assert _wait_until(lambda: buffered.credential_rejected)
    finally:
        buffered.close(drain_timeout_s=0.5)


def test_a_rejection_backs_off_instead_of_hammering():
    """With a 10 s normal interval and a 15 min auth interval, a rejected
    credential must produce far fewer attempts than a network failure
    would over the same window."""
    inner = _RejectingClient()
    buffered = BufferedTelemetryClient(
        inner, retry_interval_s=0.01, auth_retry_interval_s=5.0,
    )
    try:
        buffered.send_alert(_alert())
        assert _wait_until(lambda: inner.attempts >= 1)
        time.sleep(0.3)
        # At the 10 ms normal interval this would be ~30 attempts.
        assert inner.attempts <= 2, inner.attempts
    finally:
        buffered.close(drain_timeout_s=0.5)


def test_the_item_stays_queued_through_a_rejection():
    """If the unit is un-revoked, the backlog must still deliver — a fall
    that happened while the credential was bad is not less real."""
    inner = _RejectingClient()
    buffered = BufferedTelemetryClient(
        inner, retry_interval_s=0.01, auth_retry_interval_s=0.05,
    )
    try:
        buffered.send_alert(_alert())
        assert _wait_until(lambda: buffered.credential_rejected)
        assert buffered.queue_depth() >= 1

        inner.accept = True
        assert _wait_until(lambda: buffered.delivered_alerts >= 1)
        assert buffered.credential_rejected is False
    finally:
        buffered.close(drain_timeout_s=0.5)
