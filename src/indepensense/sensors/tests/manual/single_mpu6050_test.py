"""Manual hardware test: stream accelerometer + gyroscope readings from MPU6050.

Run on a Raspberry Pi 5 with the IMU wired to I2C1:
    SDA -> Pi pin 3 (GPIO 2)
    SCL -> Pi pin 5 (GPIO 3)

Confirm the device is visible first with:
    i2cdetect -y 1     # should show 0x68 (or 0x69 if AD0 is pulled high)

Run from repo root with:
    python -m indepensense.sensors.tests.manual.single_mpu6050_test
"""
import time

from indepensense.config import MPU6050_ADDRESS, MPU6050_I2C_BUS
from indepensense.safety.fall_detector import magnitude_g
from indepensense.sensors.mpu6050 import MPU6050


def main():
    imu = MPU6050(bus_number=MPU6050_I2C_BUS, address=MPU6050_ADDRESS)
    print(f"Reading MPU6050 on I2C bus {MPU6050_I2C_BUS} at 0x{MPU6050_ADDRESS:02x}. Ctrl-C to stop.")
    try:
        while True:
            reading = imu.read()
            if reading is not None:
                # |a| is the validation number, so it is printed rather
                # than left to be worked out from the axes. At rest it
                # must read 1.00 g in ANY orientation — the fall detector
                # thresholds on this magnitude and never on a single
                # axis, so a sensor glued vertically to the vest is just
                # as valid as one lying flat. A reading near 0.25 or 4.00
                # means the full-scale range is wrong; an erratic one
                # means the high and low bytes are swapped.
                print(
                    f"|a|={magnitude_g(reading):5.2f} g | "
                    f"accel(g): x={reading.accel_x:+6.2f} y={reading.accel_y:+6.2f} z={reading.accel_z:+6.2f} | "
                    f"gyro(dps): x={reading.gyro_x:+7.1f} y={reading.gyro_y:+7.1f} z={reading.gyro_z:+7.1f} | "
                    f"temp={reading.temperature_c:5.1f}°C"
                )
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        imu.close()


if __name__ == "__main__":
    main()
