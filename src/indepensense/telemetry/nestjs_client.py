"""HTTP client for the NestJS backend at `../IndepenSense`.

Two endpoints, both under `/raspberry/*`:

- `POST /raspberry/interval-information` — periodic heartbeat.
- `POST /raspberry/alert` — event notifications the guardian must see.

Authentication
--------------

Every request carries the device credential as
`Authorization: Bearer <uuid>.<secret>`, and the backend derives which
device is calling from that alone. Nothing sends a `deviceID` field any
more — that was a claim any caller could make, which made these endpoints
effectively public.

Two consequences for this module:

- `base_url` must be https (see `net.require_https`). The credential is a
  password travelling in a header on every request.
- The payload functions no longer emit `deviceID`. `AlertEvent` and
  `IntervalInformation` still carry `device_id` because it identifies the
  unit in local logs, but it is not sent.

The backend expects camelCase JSON keys; our internal dataclasses are
snake_case (Python convention). The `heartbeat_payload` and
`alert_payload` pure functions do the translation and are the single
place where the wire format lives.

Field-name warning: the alert payload uses `occuredAt` (missing an 'r' in
"occurred"). This matches the backend's schema exactly. The unit tests
guard against someone "correcting" the spelling and silently breaking
integration.

Returns and errors
------------------

`send_*` return a boolean, except for one case that is not a boolean
question:

- `True` on any HTTP 2xx.
- **Raises `DeviceCredentialRejected` on 401.** The credential is wrong
  or revoked; retrying cannot help, and a caller that treats it as a
  normal failure would retry forever. `buffered.py` catches this and
  backs off hard.
- `False` on 400 (authenticated, but no assisted user is linked yet —
  normal on a fresh unit, so worth retrying periodically), 5xx, timeouts
  and connection failures.

Errors are logged to stderr with the HTTP status and a truncated
response body. The `Authorization` header is never logged.
"""
import sys
from typing import Any

from indepensense.credential import DeviceCredential
from indepensense.net import require_https
from indepensense.telemetry.base import (
    AlertEvent,
    DeviceCredentialRejected,
    IntervalInformation,
)

_HEARTBEAT_PATH = "/raspberry/interval-information"
_ALERT_PATH = "/raspberry/alert"


def heartbeat_payload(info: IntervalInformation) -> dict[str, Any]:
    """Serialise a heartbeat to the exact JSON shape the backend expects.

    No `deviceID` — identity comes from the bearer token. No `createdAt`
    either: the server timestamps the row itself, and sending a
    device-side clock invited disagreement with it (the Pi has no RTC, so
    its clock is wrong until NTP settles after boot).
    """
    return {
        "batteryHealth": info.battery_health,
        "internetStatus": info.internet_status,
        "latitude": info.latitude,
        "longitude": info.longitude,
    }


def alert_payload(event: AlertEvent) -> dict[str, Any]:
    """Serialise an alert to the exact JSON shape the backend expects.

    Note the `occuredAt` key intentionally matches the backend's spelling
    (missing 'r'). Do NOT change this without a coordinated backend edit.

    No `deviceID` — identity comes from the bearer token. `occuredAt` is
    kept because when a fall happened is not when it was delivered: an
    alert can sit in the retry queue for hours while offline.
    """
    return {
        "eventType": event.event_type.value,
        "latitude": event.latitude,
        "longitude": event.longitude,
        "occuredAt": event.occurred_at.isoformat(),
    }


class NestJSTelemetryClient:
    def __init__(
        self,
        base_url: str,
        credential: DeviceCredential,
        timeout_s: float = 5.0,
    ):
        """Raises if `base_url` is not https — see `net.require_https`.

        The credential is required rather than optional: without it every
        request is a 401, so constructing a client that cannot possibly
        succeed only defers the error to a confusing place. `app.py`
        skips building one at all when no credential is present.
        """
        require_https(base_url, "BACKEND_URL")
        self._base_url = base_url.rstrip("/")
        self._credential = credential
        self._timeout_s = timeout_s

    def send_heartbeat(self, info: IntervalInformation) -> bool:
        return self._post(_HEARTBEAT_PATH, heartbeat_payload(info))

    def send_alert(self, event: AlertEvent) -> bool:
        return self._post(_ALERT_PATH, alert_payload(event))

    def _post(self, path: str, payload: dict[str, Any]) -> bool:
        import requests

        url = f"{self._base_url}{path}"
        try:
            response = requests.post(
                url,
                json=payload,
                headers={"Authorization": self._credential.authorization_header()},
                timeout=self._timeout_s,
            )
        except requests.RequestException as exc:
            print(f"[telemetry] POST {path} network error: {exc}", file=sys.stderr)
            return False

        if response.status_code == 401:
            # Not a transient failure. Raised so `buffered.py` can back off
            # for a quarter of an hour instead of retrying every 10 s
            # against a request that can never succeed.
            raise DeviceCredentialRejected(
                f"backend rejected the device credential for {path} "
                f"(device {self._credential.device_id})"
            )

        if not response.ok:
            body_preview = response.text[:200] if response.text else "(empty)"
            print(
                f"[telemetry] POST {path} returned {response.status_code}: {body_preview}",
                file=sys.stderr,
            )
            return False

        return True
