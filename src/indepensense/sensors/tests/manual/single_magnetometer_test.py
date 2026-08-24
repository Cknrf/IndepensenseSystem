"""Manual hardware test: live QMC5883L readout.

Run on a Raspberry Pi 5 with the QMC5883L wired to I²C1. Ctrl-C to stop.

    python -m indepensense.sensors.tests.manual.single_magnetometer_test

Prints the calibrated magnetic field (μT per axis), the total field
magnitude, and the computed heading. Rotate the cane slowly and check:

  * heading sweeps smoothly through 0-360 with no jumps or dead spots
  * magnitude stays roughly constant (25-65 μT depending on where you
    are). A magnitude that swells and shrinks as you turn is the
    signature of an uncalibrated sensor — run `magnetometer_calibrate`.

If construction fails with a chip-ID error, the part at `MAG_ADDRESS` is
not a QMC5883L. Check `sudo i2cdetect -y 1`: `0x0D` is the QMC5883L,
`0x1E` would be a genuine Honeywell HMC5883L (different registers, not
supported by this driver).
"""
import math
import time

from indepensense.config import (
    MAG_ADDRESS,
    MAG_I2C_BUS,
    MAG_OFFSET_X,
    MAG_OFFSET_Y,
    MAG_OFFSET_Z,
    MAG_SCALE_X,
    MAG_SCALE_Y,
    MAG_SCALE_Z,
)
from indepensense.sensors.qmc5883l import QMC5883L


def main():
    mag = QMC5883L(
        bus_number=MAG_I2C_BUS,
        address=MAG_ADDRESS,
        offset_x=MAG_OFFSET_X,
        offset_y=MAG_OFFSET_Y,
        offset_z=MAG_OFFSET_Z,
        scale_x=MAG_SCALE_X,
        scale_y=MAG_SCALE_Y,
        scale_z=MAG_SCALE_Z,
    )
    if (MAG_OFFSET_X, MAG_OFFSET_Y, MAG_OFFSET_Z) == (0.0, 0.0, 0.0):
        print("NOTE: calibration offsets are all zero — headings will be biased.")
        print("      Run `magnetometer_calibrate` and paste the values into config.py.")
        print()
    print("Live magnetometer. Rotate slowly through 0-360 degrees. Ctrl-C to stop.")
    try:
        while True:
            reading = mag.read()
            if reading is None:
                print("[read] failed or overflowed")
            else:
                magnitude = math.sqrt(
                    reading.magnetic_x ** 2
                    + reading.magnetic_y ** 2
                    + reading.magnetic_z ** 2
                )
                print(
                    f"heading={reading.heading_deg:6.1f}°  "
                    f"| x={reading.magnetic_x:+7.1f} "
                    f"y={reading.magnetic_y:+7.1f} "
                    f"z={reading.magnetic_z:+7.1f} μT "
                    f"| |B|={magnitude:6.1f} μT"
                )
            time.sleep(0.2)
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        mag.close()


if __name__ == "__main__":
    main()
