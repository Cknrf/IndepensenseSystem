"""Manual test: send an alert to the running backend and verify it lands.

Prerequisites:
    - NestJS backend reachable at BACKEND_URL over **https**. The device
      credential is a bearer token; plaintext is refused at startup.
    - This unit provisioned: `config.DEVICE_KEY_PATH` holds a valid
      `<uuid>.<secret>` and is readable by your account.
    - The device linked to an assisted user, or the backend answers 400
      `unknown or unlinked device`.
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

from indepensense.config import BACKEND_URL, DEVICE_KEY_PATH, TELEMETRY_TIMEOUT_S
from indepensense.credential import load_device_credential
from indepensense.telemetry.base import (
    AlertEvent,
    DeviceCredentialRejected,
    EventType,
)
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

    credential = load_device_credential(DEVICE_KEY_PATH)
    if credential is None:
        print(f"No usable credential at {DEVICE_KEY_PATH} — see stderr above.")
        raise SystemExit(1)

    client = NestJSTelemetryClient(
        base_url=BACKEND_URL,
        credential=credential,
        timeout_s=TELEMETRY_TIMEOUT_S,
    )
    event = AlertEvent(
        device_id=credential.device_id,
        event_type=event_type,
        latitude=13.9374,   # Lipa area — replace with real GPS once integrated
        longitude=121.1186,
        occurred_at=datetime.now(timezone.utc),
    )
    print(f"POST {BACKEND_URL}/raspberry/alert  eventType={event.event_type.value}")
    print(f"  as device {credential.device_id}")

    try:
        ok = client.send_alert(event)
    except DeviceCredentialRejected as exc:
        # Deliberately distinct from a generic failure: this one will not
        # fix itself and no amount of retrying helps.
        print(f"REJECTED: {exc}")
        print("The unit needs re-provisioning or un-revoking by a human.")
        raise SystemExit(1)

    if ok:
        print("Sent successfully. Check the guardian dashboard for the SSE push.")
    else:
        print("Send failed — see stderr above. A 400 'unknown or unlinked")
        print("device' means auth worked but no assisted user is paired yet.")


if __name__ == "__main__":
    main()
