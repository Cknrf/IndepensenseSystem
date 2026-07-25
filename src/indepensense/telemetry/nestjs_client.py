"""HTTP client for the NestJS backend at `../IndepenSense`.

Two endpoints, both under `/raspberry/*`:

- `POST /raspberry/interval-information` — periodic heartbeat.
- `POST /raspberry/alert` — event notifications the guardian must see.

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

Both `send_*` methods return a boolean:

- `True` on any HTTP 2xx.
- `False` on 4xx (client bug, retrying won't help), 5xx (server issue,
  worth retrying later), timeouts, and connection failures.

Errors are logged to stderr with the HTTP status and a truncated
response body before returning False. Phase 2 (`buffered.py`) wraps this
client with a retry queue that treats 2xx/4xx as terminal and everything
else as retryable.
"""
import sys
from typing import Any

from indepensense.telemetry.base import AlertEvent, IntervalInformation

_HEARTBEAT_PATH = "/raspberry/interval-information"
_ALERT_PATH = "/raspberry/alert"


def heartbeat_payload(info: IntervalInformation) -> dict[str, Any]:
    """Serialise a heartbeat to the exact JSON shape the backend expects."""
    return {
        "deviceID": info.device_id,
        "batteryHealth": info.battery_health,
        "internetStatus": info.internet_status,
        "latitude": info.latitude,
        "longitude": info.longitude,
        "createdAt": info.created_at.isoformat(),
    }


def alert_payload(event: AlertEvent) -> dict[str, Any]:
    """Serialise an alert to the exact JSON shape the backend expects.

    Note the `occuredAt` key intentionally matches the backend's spelling
    (missing 'r'). Do NOT change this without a coordinated backend edit.
    """
    return {
        "deviceID": event.device_id,
        "eventType": event.event_type.value,
        "latitude": event.latitude,
        "longitude": event.longitude,
        "occuredAt": event.occurred_at.isoformat(),
    }


class NestJSTelemetryClient:
    def __init__(self, base_url: str, timeout_s: float = 5.0):
        self._base_url = base_url.rstrip("/")
        self._timeout_s = timeout_s

    def send_heartbeat(self, info: IntervalInformation) -> bool:
        return self._post(_HEARTBEAT_PATH, heartbeat_payload(info))

    def send_alert(self, event: AlertEvent) -> bool:
        return self._post(_ALERT_PATH, alert_payload(event))

    def _post(self, path: str, payload: dict[str, Any]) -> bool:
        import requests

        url = f"{self._base_url}{path}"
        try:
            response = requests.post(url, json=payload, timeout=self._timeout_s)
        except requests.RequestException as exc:
            print(f"[telemetry] POST {path} network error: {exc}", file=sys.stderr)
            return False

        if not response.ok:
            body_preview = response.text[:200] if response.text else "(empty)"
            print(
                f"[telemetry] POST {path} returned {response.status_code}: {body_preview}",
                file=sys.stderr,
            )
            return False

        return True
