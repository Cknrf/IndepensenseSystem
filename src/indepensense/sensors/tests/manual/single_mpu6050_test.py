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
from indepensense.sensors.mpu6050 import MPU6050


def main():
    imu = MPU6050(bus_number=MPU6050_I2C_BUS, address=MPU6050_ADDRESS)
    print(f"Reading MPU6050 on I2C bus {MPU6050_I2C_BUS} at 0x{MPU6050_ADDRESS:02x}. Ctrl-C to stop.")
    try:
        while True:
            reading = imu.read()
            if reading is not None:
                print(
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
