"""Manual test: send an alert to the running backend and verify it lands.

Prerequisites:
    - NestJS backend running on BACKEND_URL (default http://localhost:3000)
    - `npm run seed` has been executed so device UUID
      00000000-0000-0000-0000-000000000001 exists and is linked
    - `guardian1` account listening on the guardian dashboard SSE stream
      to confirm the alert arrives in real time

Run from repo root:
    python -m indepensense.telemetry.tests.manual.send_alert_test

Optionally pass an event type:
    python -m indepensense.telemetry.tests.manual.send_alert_test fall
    python -m indepensense.telemetry.tests.manual.send_alert_test emergency
    python -m indepensense.telemetry.tests.manual.send_alert_test battery
    python -m indepensense.telemetry.tests.manual.send_alert_test connectivity
"""
import sys
from datetime import datetime, timezone

from indepensense.config import BACKEND_URL, DEVICE_ID, TELEMETRY_TIMEOUT_S
from indepensense.telemetry.base import AlertEvent, EventType
from indepensense.telemetry.nestjs_client import NestJSTelemetryClient

_TYPE_ALIASES = {
    "emergency": EventType.EMERGENCY_ALERT,
    "fall":      EventType.FALL_DETECTION,
    "battery":   EventType.LOW_BATTERY,
    "connectivity": EventType.CONNECTIVITY,
}


def main():
    alias = sys.argv[1].lower() if len(sys.argv) > 1 else "emergency"
    if alias not in _TYPE_ALIASES:
        print(f"Unknown alias '{alias}'. Options: {list(_TYPE_ALIASES)}")
        return
    event_type = _TYPE_ALIASES[alias]

    client = NestJSTelemetryClient(base_url=BACKEND_URL, timeout_s=TELEMETRY_TIMEOUT_S)
    event = AlertEvent(
        device_id=DEVICE_ID,
        event_type=event_type,
        latitude=13.9374,   # Lipa area — replace with real GPS once integrated
        longitude=121.1186,
        occurred_at=datetime.now(timezone.utc),
    )
    print(f"POST {BACKEND_URL}/raspberry/alert  eventType={event.event_type.value}")
    ok = client.send_alert(event)
    if ok:
        print("Sent successfully. Check the guardian dashboard for the SSE push.")
    else:
        print("Send failed — see stderr above for the specific error.")


if __name__ == "__main__":
    main()
