"""Manual test: send a heartbeat to the running backend.

Prerequisites: see `send_alert_test.py` — same setup.

Run from repo root:
    python -m indepensense.telemetry.tests.manual.send_heartbeat_test
"""
from datetime import datetime, timezone

from indepensense.config import BACKEND_URL, DEVICE_KEY_PATH, TELEMETRY_TIMEOUT_S
from indepensense.credential import load_device_credential
from indepensense.telemetry.base import DeviceCredentialRejected, IntervalInformation
from indepensense.telemetry.nestjs_client import NestJSTelemetryClient


def main():
    credential = load_device_credential(DEVICE_KEY_PATH)
    if credential is None:
        print(f"No usable credential at {DEVICE_KEY_PATH} — see stderr above.")
        raise SystemExit(1)

    client = NestJSTelemetryClient(
        base_url=BACKEND_URL,
        credential=credential,
        timeout_s=TELEMETRY_TIMEOUT_S,
    )
    info = IntervalInformation(
        device_id=credential.device_id,
        battery_health=100,       # TODO: read from Waveshare UPS HAT (E) once wired
        internet_status=True,     # TODO: derive from probe or last-post outcome
        latitude=13.9374,         # TODO: read from live GPS
        longitude=121.1186,
        # Not sent — the server timestamps the row. Kept because the
        # dataclass requires it and it is useful in local logs.
        created_at=datetime.now(timezone.utc),
    )
    print(f"POST {BACKEND_URL}/raspberry/interval-information")
    print(f"  as device {credential.device_id}")

    try:
        ok = client.send_heartbeat(info)
    except DeviceCredentialRejected as exc:
        print(f"REJECTED: {exc}")
        print("The unit needs re-provisioning or un-revoking by a human.")
        raise SystemExit(1)

    print("Sent successfully." if ok else "Send failed — see stderr above.")


if __name__ == "__main__":
    main()
