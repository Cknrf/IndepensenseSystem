"""Manual hardware test: read from two DYP-A22 sensors simultaneously.

Run on a Raspberry Pi 5 with sensors on the two UART ports configured in
`indepensense.config`. Run from repo root with:
    python -m indepensense.sensors.tests.manual.dual_dyp_test
"""
import time

from indepensense.config import (
    DYP_A22_BAUDRATE,
    DYP_A22_PRIMARY_PORT,
    DYP_A22_SECONDARY_PORT,
)
from indepensense.sensors.dyp_a22 import DYPA22


def main():
    sensor1 = DYPA22(DYP_A22_PRIMARY_PORT, baudrate=DYP_A22_BAUDRATE)
    sensor2 = DYPA22(DYP_A22_SECONDARY_PORT, baudrate=DYP_A22_BAUDRATE)
    print(f"Reading from {DYP_A22_PRIMARY_PORT} and {DYP_A22_SECONDARY_PORT}. Ctrl-C to stop.")
    try:
        while True:
            r1 = sensor1.read()
            r2 = sensor2.read()
            if r1 is not None:
                print(f"[Sensor 1]: {r1.distance_cm:6.1f} cm")
            if r2 is not None:
                print(f"\t\t\t[Sensor 2]: {r2.distance_cm:6.1f} cm")
            time.sleep(0.01)
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        sensor1.close()
        sensor2.close()


if __name__ == "__main__":
    main()
