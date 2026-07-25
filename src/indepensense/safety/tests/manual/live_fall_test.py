"""Manual hardware test: stream real IMU readings through the fall detector.

Run on the Pi with the MPU6050 wired to I2C1. Ctrl-C to stop.

    python -m indepensense.safety.tests.manual.live_fall_test

The script prints the current detector state and any FallEvent that fires.
To exercise it, drop the wearable onto a soft surface (mattress, thick
cushion) — you should see states progress IDLE -> POST_FREEFALL -> POST_IMPACT
and eventually a FALL_DETECTED line after ~2 s of stillness on the surface.

Do not drop the wearable onto a hard surface — the MPU6050 breakout board is
not shock-rated.

When a fall is detected AND the guardian backend is reachable, this test
also POSTs a `Fall Detection` alert to /raspberry/alert with the current
GPS coordinates (0.0/0.0 fallback if no fix). The alert is fire-and-forget:
the guardian dashboard receives an SSE push in real time. Failures are
logged to stderr and do not stop the local fall-detection loop.
"""
import time
from datetime import datetime, timezone

from indepensense.config import (
    BACKEND_URL,
    DEVICE_ID,
    MPU6050_ADDRESS,
    MPU6050_I2C_BUS,
    SIM7600_GPS_PORT,
    TELEMETRY_TIMEOUT_S,
)
from indepensense.safety.base import DetectorState, FallEvent
from indepensense.safety.fall_detector import ThresholdFallDetector, magnitude_g
from indepensense.sensors.mpu6050 import MPU6050
from indepensense.telemetry.base import AlertEvent, EventType
from indepensense.telemetry.nestjs_client import NestJSTelemetryClient

SAMPLE_INTERVAL_S = 0.01   # 100 Hz — catches brief impact spikes better than 50 Hz


def _try_open_gps():
    """Try to open the SIM7600 GPS; return None if unavailable."""
    from indepensense.sensors.gps import SIM7600GPS
    try:
        return SIM7600GPS(port=SIM7600_GPS_PORT)
    except Exception as exc:
        print(f"  GPS unavailable ({exc}). Fall alerts will send 0.0/0.0 coords.")
        return None


def _send_fall_alert(
    telemetry: NestJSTelemetryClient,
    gps,
    event: FallEvent,
) -> None:
    """POST a Fall Detection alert to the guardian backend.

    Fire-and-forget: successes and failures both log a one-line status but
    never raise. Same design as the emergency-trigger path in the intent
    executor.
    """
    lat, lon = 0.0, 0.0
    if gps is not None:
        try:
            fix = gps.read()
            if fix is not None and fix.fix_quality > 0:
                lat, lon = fix.lat, fix.lon
        except Exception:
            pass   # keep 0.0/0.0 fallback on any GPS read glitch

    alert = AlertEvent(
        device_id=DEVICE_ID,
        event_type=EventType.FALL_DETECTION,
        latitude=lat,
        longitude=lon,
        occurred_at=datetime.now(timezone.utc),
    )
    if telemetry.send_alert(alert):
        print(f"  → alert POSTed to guardian ({lat:.5f}, {lon:.5f})")
    else:
        print("  → alert POST failed (see stderr)")


def main():
    imu = MPU6050(bus_number=MPU6050_I2C_BUS, address=MPU6050_ADDRESS)
    detector = ThresholdFallDetector()
    telemetry = NestJSTelemetryClient(base_url=BACKEND_URL, timeout_s=TELEMETRY_TIMEOUT_S)
    print("  Opening GPS...")
    gps = _try_open_gps()

    print("Fall detector running at 100 Hz. Ctrl-C to stop.")
    print(f"Fall alerts POST to {BACKEND_URL}/raspberry/alert as device {DEVICE_ID}.")
    print("Prints state transitions with the triggering magnitude, plus a")
    print("running peak magnitude every second so you can gauge drops.")

    last_state = DetectorState.IDLE
    last_status_time = time.time()
    peak_since_status = 0.0
    peak_during_phase = 0.0

    try:
        while True:
            reading = imu.read()
            if reading is None:
                time.sleep(SAMPLE_INTERVAL_S)
                continue

            mag = magnitude_g(reading)
            peak_since_status = max(peak_since_status, mag)
            peak_during_phase = max(peak_during_phase, mag)
            event = detector.process(reading)

            if detector.state is not last_state:
                phase_peak_str = (
                    f" (peak during {last_state.value}: {peak_during_phase:.2f} g)"
                    if last_state is not DetectorState.IDLE
                    else ""
                )
                print(
                    f"[state] {last_state.value} -> {detector.state.value}  "
                    f"triggered at mag={mag:.2f} g{phase_peak_str}"
                )
                last_state = detector.state
                peak_during_phase = mag

            if event is not None:
                print(
                    f"[FALL DETECTED] "
                    f"impact={event.impact_magnitude_g:.2f} g, "
                    f"freefall={event.freefall_duration_s*1000:.0f} ms"
                )
                _send_fall_alert(telemetry, gps, event)

            # Periodic baseline so you can see when the wearable is quiet.
            now = time.time()
            if now - last_status_time >= 1.0:
                print(
                    f"[stat] mag_now={mag:.2f} g  "
                    f"peak_last_1s={peak_since_status:.2f} g  "
                    f"state={detector.state.value}"
                )
                last_status_time = now
                peak_since_status = 0.0

            time.sleep(SAMPLE_INTERVAL_S)
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        imu.close()
        if gps is not None:
            gps.close()


if __name__ == "__main__":
    main()
