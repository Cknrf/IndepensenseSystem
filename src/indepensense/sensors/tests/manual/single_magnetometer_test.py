"""Manual hardware test: live magnetometer readout.

Run on a Raspberry Pi 5 with the MPU9250 wired to I²C1. Ctrl-C to stop.

    python -m indepensense.sensors.tests.manual.single_magnetometer_test

Prints raw magnetic field (μT on each axis) and computed heading in
degrees. Rotate the cane slowly and confirm heading changes smoothly
around 0-360.

If heading readings are very noisy or biased (e.g. always ~90°
regardless of rotation), you probably need to run the calibration
helper: `magnetometer_calibrate.py`.
"""
import time

from indepensense.config import (
    MAG_ADDRESS,
    MAG_OFFSET_X,
    MAG_OFFSET_Y,
    MAG_OFFSET_Z,
    MPU6050_ADDRESS,
    MPU6050_I2C_BUS,
)
from indepensense.sensors.magnetometer import AK8963Magnetometer


def main():
    mag = AK8963Magnetometer(
        bus_number=MPU6050_I2C_BUS,
        mpu9250_address=MPU6050_ADDRESS,
        magnetometer_address=MAG_ADDRESS,
        offset_x=MAG_OFFSET_X,
        offset_y=MAG_OFFSET_Y,
        offset_z=MAG_OFFSET_Z,
    )
    print("Live magnetometer. Rotate slowly through 0-360 degrees. Ctrl-C to stop.")
    try:
        while True:
            reading = mag.read()
            if reading is None:
                print("[read] failed")
            else:
                print(
                    f"heading={reading.heading_deg:6.1f}°  "
                    f"| x={reading.magnetic_x:+7.1f} "
                    f"y={reading.magnetic_y:+7.1f} "
                    f"z={reading.magnetic_z:+7.1f} μT"
                )
            time.sleep(0.2)
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        mag.close()


if __name__ == "__main__":
    main()
