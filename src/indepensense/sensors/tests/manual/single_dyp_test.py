"""Manual hardware test: read distance from one DYP-A22.

Run on a Raspberry Pi 5 with the sensor wired to the GPIO UART pins.
Run from repo root with:
    python -m indepensense.sensors.tests.manual.single_dyp_test
"""
import time

from indepensense.config import DYP_A22_BAUDRATE, DYP_A22_PRIMARY_PORT
from indepensense.sensors.dyp_a22 import DYPA22


def main():
    sensor = DYPA22(DYP_A22_PRIMARY_PORT, baudrate=DYP_A22_BAUDRATE)
    print(f"Reading DYP-A22 on {DYP_A22_PRIMARY_PORT}. Ctrl-C to stop.")
    try:
        while True:
            reading = sensor.read()
            if reading is not None:
                print(f"Distance: {reading.distance_cm:.1f} cm")
            time.sleep(0.01)
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        sensor.close()


if __name__ == "__main__":
    main()
