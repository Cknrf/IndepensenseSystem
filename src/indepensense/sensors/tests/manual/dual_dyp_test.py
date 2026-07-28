"""Manual hardware test: read from two DYP-A22 sensors simultaneously.

Run on a Raspberry Pi 5 with sensors on the two UART ports configured in
`indepensense.config`. Run from repo root with:
    python -m indepensense.sensors.tests.manual.dual_dyp_test
"""
import time

from indepensense.config import (
    DYP_A22_BAUDRATE,
    DYP_A22_BOTTOM_PORT,
    DYP_A22_TOP_PORT,
)
from indepensense.sensors.dyp_a22 import DYPA22


def main():
    top = DYPA22(DYP_A22_TOP_PORT, baudrate=DYP_A22_BAUDRATE)
    bottom = DYPA22(DYP_A22_BOTTOM_PORT, baudrate=DYP_A22_BAUDRATE)
    print(f"Reading TOP on {DYP_A22_TOP_PORT} and BOTTOM on {DYP_A22_BOTTOM_PORT}. Ctrl-C to stop.")
    try:
        while True:
            r1 = top.read()
            r2 = bottom.read()
            if r1 is not None:
                print(f"[TOP]:    {r1.distance_cm:6.1f} cm")
            if r2 is not None:
                print(f"\t\t\t[BOTTOM]: {r2.distance_cm:6.1f} cm")
            time.sleep(0.01)
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        top.close()
        bottom.close()


if __name__ == "__main__":
    main()
