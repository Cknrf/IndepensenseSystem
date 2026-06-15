"""DYP-A22 ultrasonic distance sensor driver (UART auto-mode).

Frame format (4 bytes, sent continuously by the sensor):
    byte 0: 0xFF        header
    byte 1: high byte   distance high byte (mm)
    byte 2: low byte    distance low byte (mm)
    byte 3: checksum    (0xFF + high + low) & 0xFF

A distance of 0 mm means "no echo / out of range".
"""
import time

from indepensense.sensors.base import UltrasonicReading

DYP_HEADER = 0xFF
DYP_FRAME_SIZE = 4


def parse_dyp_frame(frame: bytes) -> float | None:
    """Parse a 4-byte DYP-A22 frame. Returns distance in cm, or None on error."""
    if len(frame) != DYP_FRAME_SIZE or frame[0] != DYP_HEADER:
        return None
    high, low, checksum = frame[1], frame[2], frame[3]
    if ((DYP_HEADER + high + low) & 0xFF) != checksum:
        return None
    distance_mm = (high << 8) + low
    if distance_mm == 0:
        return None
    return distance_mm / 10.0


class DYPA22:
    def __init__(self, port: str, baudrate: int = 115200, timeout_s: float = 0.05):
        import serial  # imported lazily so the package can be imported on Mac

        self._ser = serial.Serial(port, baudrate=baudrate, timeout=timeout_s)
        self._ser.reset_input_buffer()

    def read(self) -> UltrasonicReading | None:
        if self._ser.in_waiting < DYP_FRAME_SIZE:
            return None
        if self._ser.read(1) != bytes([DYP_HEADER]):
            return None
        tail = self._ser.read(DYP_FRAME_SIZE - 1)
        distance_cm = parse_dyp_frame(bytes([DYP_HEADER]) + tail)
        if distance_cm is None:
            return None
        return UltrasonicReading(distance_cm=distance_cm, timestamp=time.time())

    def close(self) -> None:
        self._ser.close()
