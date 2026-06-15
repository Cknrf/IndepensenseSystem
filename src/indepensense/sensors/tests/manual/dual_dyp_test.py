"""Manual hardware test: read from two DYP-A22 sensors simultaneously.

Run on a Raspberry Pi 5 with sensors on /dev/ttyAMA0 and /dev/ttyAMA4.
Run from repo root with:
    python -m indepensense.sensors.tests.manual.dual_dyp_test
"""
import time

from indepensense.sensors.dyp_a22 import DYPA22

PORT_1 = "/dev/ttyAMA0"
PORT_2 = "/dev/ttyAMA4"


def main():
    sensor1 = DYPA22(PORT_1)
    sensor2 = DYPA22(PORT_2)
    print(f"Reading from {PORT_1} and {PORT_2}. Ctrl-C to stop.")
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
