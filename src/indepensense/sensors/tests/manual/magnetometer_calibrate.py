"""Hard-iron calibration helper for the AK8963 magnetometer.

Rotate the assembled wearable through all orientations for ~30 s while
this script records the min and max magnetic field on each axis. The
offset for each axis is `(max + min) / 2`, which cancels the constant
bias from nearby ferromagnetic material (Pi, batteries, ultrasonic
metal mounts, motor magnets).

Run:
    python -m indepensense.sensors.tests.manual.magnetometer_calibrate

At the end, the script prints values you should paste into
`config.py`:

    MAG_OFFSET_X = ...
    MAG_OFFSET_Y = ...
    MAG_OFFSET_Z = ...

The calibration is device-specific — each assembled wearable needs its
own. Re-run if you significantly change the physical layout (relocate
batteries, add metal components, etc.). Not necessary if you just move
the wearable to a different room.

Runs with ZERO existing offsets (offset_*=0) so it captures raw min/max.
"""
import time

from indepensense.config import MAG_ADDRESS, MPU6050_ADDRESS, MPU6050_I2C_BUS
from indepensense.sensors.magnetometer import AK8963Magnetometer

DURATION_S = 30.0


def main():
    mag = AK8963Magnetometer(
        bus_number=MPU6050_I2C_BUS,
        mpu9250_address=MPU6050_ADDRESS,
        magnetometer_address=MAG_ADDRESS,
        offset_x=0.0,
        offset_y=0.0,
        offset_z=0.0,
    )

    print(f"Rotate the wearable through ALL orientations for the next "
          f"{DURATION_S:.0f} seconds:")
    print("  - Point the front UP, DOWN, LEFT, RIGHT, FORWARD, BACKWARD")
    print("  - Roll it, tilt it, swing it")
    print("  - The more coverage, the better the calibration")
    print()
    print("3... 2... 1...")
    time.sleep(3)
    print("GO!")

    x_min = x_max = None
    y_min = y_max = None
    z_min = z_max = None

    t_start = time.time()
    sample_count = 0
    try:
        while time.time() - t_start < DURATION_S:
            reading = mag.read()
            if reading is not None:
                sample_count += 1
                x_min = reading.magnetic_x if x_min is None else min(x_min, reading.magnetic_x)
                x_max = reading.magnetic_x if x_max is None else max(x_max, reading.magnetic_x)
                y_min = reading.magnetic_y if y_min is None else min(y_min, reading.magnetic_y)
                y_max = reading.magnetic_y if y_max is None else max(y_max, reading.magnetic_y)
                z_min = reading.magnetic_z if z_min is None else min(z_min, reading.magnetic_z)
                z_max = reading.magnetic_z if z_max is None else max(z_max, reading.magnetic_z)

                elapsed = time.time() - t_start
                print(
                    f"\r  [{elapsed:5.1f}s / {DURATION_S:.0f}s] "
                    f"x=[{x_min:+7.1f},{x_max:+7.1f}] "
                    f"y=[{y_min:+7.1f},{y_max:+7.1f}] "
                    f"z=[{z_min:+7.1f},{z_max:+7.1f}] μT",
                    end="",
                    flush=True,
                )
            time.sleep(0.05)
    except KeyboardInterrupt:
        print()
    finally:
        mag.close()

    print()
    print()
    if sample_count == 0 or x_min is None:
        print("No samples captured — the magnetometer isn't returning data.")
        print("Check `sudo i2cdetect -y 1` for address 0x0C.")
        return

    offset_x = (x_max + x_min) / 2
    offset_y = (y_max + y_min) / 2
    offset_z = (z_max + z_min) / 2

    print(f"Calibration complete. {sample_count} samples captured.")
    print()
    print("Paste these values into `src/indepensense/config.py`:")
    print()
    print(f"    MAG_OFFSET_X = {offset_x:.3f}")
    print(f"    MAG_OFFSET_Y = {offset_y:.3f}")
    print(f"    MAG_OFFSET_Z = {offset_z:.3f}")
    print()
    print("Then rerun `single_magnetometer_test.py` and verify that rotating")
    print("the cane through 360° gives smooth heading values.")


if __name__ == "__main__":
    main()
