"""Manual hardware test: stream real IMU readings through the fall detector.

Run on the Pi with the MPU6050 wired to I2C1. Ctrl-C to stop.

    python -m indepensense.safety.tests.manual.live_fall_test

The script prints the current detector state and any FallEvent that fires.
To exercise it, drop the wearable onto a soft surface (mattress, thick
cushion) — you should see states progress IDLE -> POST_FREEFALL -> POST_IMPACT
and eventually a FALL_DETECTED line after ~2 s of stillness on the surface.

Do not drop the wearable onto a hard surface — the MPU6050 breakout board is
not shock-rated.
"""
import time

from indepensense.config import MPU6050_ADDRESS, MPU6050_I2C_BUS
from indepensense.safety.base import DetectorState
from indepensense.safety.fall_detector import ThresholdFallDetector
from indepensense.sensors.mpu6050 import MPU6050


def main():
    imu = MPU6050(bus_number=MPU6050_I2C_BUS, address=MPU6050_ADDRESS)
    detector = ThresholdFallDetector()

    print("Fall detector running. Ctrl-C to stop.")
    print("Try dropping the wearable onto a soft surface to trigger a fall.")

    last_state = DetectorState.IDLE
    try:
        while True:
            reading = imu.read()
            if reading is None:
                time.sleep(0.02)
                continue

            event = detector.process(reading)

            if detector.state is not last_state:
                print(f"[state] {last_state.value} -> {detector.state.value}")
                last_state = detector.state

            if event is not None:
                print(
                    f"[FALL DETECTED] "
                    f"impact={event.impact_magnitude_g:.2f} g, "
                    f"freefall={event.freefall_duration_s*1000:.0f} ms"
                )

            # ~50 Hz sampling
            time.sleep(0.02)
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        imu.close()


if __name__ == "__main__":
    main()
