"""Manual test: send a heartbeat to the running backend.

Prerequisites: see `send_alert_test.py` — same setup.

Run from repo root:
    python -m indepensense.telemetry.tests.manual.send_heartbeat_test
"""
from datetime import datetime, timezone

from indepensense.config import BACKEND_URL, DEVICE_ID, TELEMETRY_TIMEOUT_S
from indepensense.telemetry.base import IntervalInformation
from indepensense.telemetry.nestjs_client import NestJSTelemetryClient


def main():
    client = NestJSTelemetryClient(base_url=BACKEND_URL, timeout_s=TELEMETRY_TIMEOUT_S)
    info = IntervalInformation(
        device_id=DEVICE_ID,
        battery_health=100,       # TODO: read from Waveshare UPS HAT (E) once wired
        internet_status=True,     # TODO: derive from probe or last-post outcome
        latitude=13.9374,         # TODO: read from live GPS
        longitude=121.1186,
        created_at=datetime.now(timezone.utc),
    )
    print(f"POST {BACKEND_URL}/raspberry/interval-information")
    ok = client.send_heartbeat(info)
    print("Sent successfully." if ok else "Send failed — see stderr above.")


if __name__ == "__main__":
    main()
