"""Manual hardware test: watch the still / walking classifier live.

Run on the Pi with the MPU6050 wired to I2C1, wearing the vest. Ctrl-C
to stop.

    python -m indepensense.safety.tests.manual.live_walking_test

Prints the rolling standard deviation of acceleration magnitude twice a
second next to the current state, and a `SET OFF` line on every still →
walking change — the event that re-alerts obstacles already in range.

This is how `WALKING_MOTION_STDDEV_G` gets tuned. Stand still, then
shift your weight, turn your head and gesture: note the highest stddev.
Then walk slowly: note the lowest. The threshold belongs between the
two, nearer the standing figure — calling a stationary user "walking"
costs a few extra reminders, the reverse costs a missed warning.
"""
import time

from indepensense.config import (
    MPU6050_ADDRESS,
    MPU6050_I2C_BUS,
    WALKING_MOTION_STDDEV_G,
    WALKING_STILL_HOLD_S,
    WALKING_WINDOW_S,
)
from indepensense.safety.fall_detector import magnitude_g, stddev
from indepensense.safety.walking_detector import WalkingDetector
from indepensense.sensors.mpu6050 import MPU6050

SAMPLE_INTERVAL_S = 0.01   # 100 Hz, the main loop's rate
PRINT_INTERVAL_S = 0.5


def main() -> None:
    imu = MPU6050(bus_number=MPU6050_I2C_BUS, address=MPU6050_ADDRESS)
    detector = WalkingDetector(
        window_s=WALKING_WINDOW_S,
        motion_stddev_g=WALKING_MOTION_STDDEV_G,
        still_hold_s=WALKING_STILL_HOLD_S,
    )
    # A second copy of the window, only so the live stddev can be shown.
    window: list[tuple[float, float]] = []

    print(
        f"Threshold {WALKING_MOTION_STDDEV_G:.3f} g over {WALKING_WINDOW_S:.1f} s; "
        f"still after {WALKING_STILL_HOLD_S:.1f} s of quiet. Ctrl-C to stop."
    )
    last_print = 0.0
    try:
        while True:
            reading = imu.read()
            if reading is not None:
                if detector.process(reading):
                    print(f"{time.strftime('%H:%M:%S')}  SET OFF")

                window.append((reading.timestamp, magnitude_g(reading)))
                window = [s for s in window if reading.timestamp - s[0] <= WALKING_WINDOW_S]

                now = time.monotonic()
                if now - last_print >= PRINT_INTERVAL_S:
                    last_print = now
                    spread = stddev([mag for _, mag in window])
                    state = "walking" if detector.walking else "still  "
                    bar = "#" * min(40, int(spread / 0.005))
                    print(f"{state}  stddev {spread:.3f} g  {bar}")
            time.sleep(SAMPLE_INTERVAL_S)
    except KeyboardInterrupt:
        pass
    finally:
        imu.close()


if __name__ == "__main__":
    main()
