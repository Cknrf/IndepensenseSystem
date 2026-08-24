"""Calibration helper for the QMC5883L magnetometer.

Rotate the assembled wearable through all orientations for ~30 s while
this script records the min and max field on each axis. From that one
sweep it derives both corrections the driver needs:

  * Hard-iron offset — `(max + min) / 2` per axis. This is the centre of
    the swing, i.e. the constant bias contributed by permanent magnets
    and ferrous mass on the cane (motor magnets, battery pack, the Pi).
    Subtracting it re-centres the field sphere on the origin.

  * Soft-iron scale — the axis half-spans `(max - min) / 2` should all be
    equal, because rotating through every orientation sweeps the same
    field magnitude on every axis. When they are not, the sphere has been
    stretched into an ellipsoid. Scaling each axis by
    `average_span / axis_span` restores it. Without this, heading error
    varies with which way you face, so it can't be trimmed out with a
    constant.

Run:
    python -m indepensense.sensors.tests.manual.magnetometer_calibrate

At the end, paste the printed values into `src/indepensense/config.py`:

    MAG_OFFSET_X/Y/Z
    MAG_SCALE_X/Y/Z

The calibration is device-specific — each assembled wearable needs its
own. Re-run if you significantly change the physical layout (relocate
batteries, add metal components, etc.). Not necessary if you just move
the wearable to a different room.

Runs with identity calibration (offsets 0, scales 1) so it captures the
raw min/max. Do this away from desks, speakers, laptops and steel
furniture — a local distortion baked into the offsets is worse than no
calibration at all.
"""
import time

from indepensense.config import MAG_ADDRESS, MAG_I2C_BUS
from indepensense.sensors.qmc5883l import QMC5883L

DURATION_S = 30.0


def main():
    mag = QMC5883L(bus_number=MAG_I2C_BUS, address=MAG_ADDRESS)

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
        print(f"Check `sudo i2cdetect -y 1` for address 0x{MAG_ADDRESS:02X}.")
        return

    offset_x = (x_max + x_min) / 2
    offset_y = (y_max + y_min) / 2
    offset_z = (z_max + z_min) / 2

    span_x = (x_max - x_min) / 2
    span_y = (y_max - y_min) / 2
    span_z = (z_max - z_min) / 2

    if min(span_x, span_y, span_z) <= 0.0:
        print("At least one axis never moved — the sweep didn't cover enough")
        print("orientations, or an axis is dead. Re-run and rotate more fully.")
        return

    span_avg = (span_x + span_y + span_z) / 3
    scale_x = span_avg / span_x
    scale_y = span_avg / span_y
    scale_z = span_avg / span_z

    print(f"Calibration complete. {sample_count} samples captured.")
    print()
    print(f"Axis half-spans: x={span_x:.1f}  y={span_y:.1f}  z={span_z:.1f} μT "
          f"(mean {span_avg:.1f})")
    print("Expect the mean to land in 25-65 μT — Earth's field. Much less means")
    print("the sweep was incomplete; much more means something magnetic is close.")
    print()
    print("Paste these values into `src/indepensense/config.py`:")
    print()
    print(f"    MAG_OFFSET_X = {offset_x:.3f}")
    print(f"    MAG_OFFSET_Y = {offset_y:.3f}")
    print(f"    MAG_OFFSET_Z = {offset_z:.3f}")
    print(f"    MAG_SCALE_X = {scale_x:.4f}")
    print(f"    MAG_SCALE_Y = {scale_y:.4f}")
    print(f"    MAG_SCALE_Z = {scale_z:.4f}")
    print()
    print("Then rerun `single_magnetometer_test.py` and verify that rotating")
    print("the cane through 360° gives smooth heading values and a roughly")
    print("constant |B|.")


if __name__ == "__main__":
    main()
