"""Mock ultrasonic sensor for off-device development.

Returns a sine-wave varying distance so navigation/fusion logic can be exercised
on a machine without real hardware (e.g. a Mac dev box).
"""
import math
import time

from indepensense.sensors.base import UltrasonicReading


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
