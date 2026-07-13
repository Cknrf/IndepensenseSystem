"""Mock ultrasonic sensor for off-device development.

Returns a sine-wave varying distance so navigation/fusion logic can be exercised
on a machine without real hardware (e.g. a Mac dev box).
"""
import math
import time

from indepensense.sensors.base import GPSFix, IMUReading, UltrasonicReading


class MockUltrasonic:
    def __init__(self, min_cm: float = 20.0, max_cm: float = 200.0, period_s: float = 5.0):
        self._min = min_cm
        self._max = max_cm
        self._period = period_s
        self._start = time.time()

    def read(self) -> UltrasonicReading | None:
        now = time.time()
        amplitude = (self._max - self._min) / 2.0
        midpoint = self._min + amplitude
        distance_cm = midpoint + amplitude * math.sin(2 * math.pi * (now - self._start) / self._period)
        return UltrasonicReading(distance_cm=distance_cm, timestamp=now)

    def close(self) -> None:
        pass


class MockIMU:
    """Mock IMU returning a still device on a level surface (gravity on +Z).

    Good enough for exercising navigation/safety logic on a Mac; not realistic
    enough to develop fall detection against — for that, replay a recorded
    real-IMU trace (TODO when fall detection lands).
    """
    def read(self) -> IMUReading | None:
        return IMUReading(
            accel_x=0.0,
            accel_y=0.0,
            accel_z=1.0,
            gyro_x=0.0,
            gyro_y=0.0,
            gyro_z=0.0,
            temperature_c=25.0,
            timestamp=time.time(),
        )

    def close(self) -> None:
        pass


class MockGPS:
    """Mock GPS returning a fixed position — Manila (Rizal Park) by default.

    Enough to exercise navigation/routing code on a Mac without the SIM7600
    hardware. Not intended for realistic movement simulation — replay a real
    NMEA log if that becomes needed.
    """
    def __init__(self, lat: float = 14.5824, lon: float = 120.9760):
        self._lat = lat
        self._lon = lon

    def read(self) -> GPSFix | None:
        return GPSFix(
            lat=self._lat,
            lon=self._lon,
            altitude_m=15.0,
            speed_knots=0.0,
            course_deg=None,
            satellites=8,
            hdop=1.2,
            fix_quality=1,
            utc_time=None,
            timestamp=time.time(),
        )

    def close(self) -> None:
        pass
