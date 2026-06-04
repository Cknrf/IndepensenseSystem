import serial
import time

class DYP_A22:
    def __init__(self, port="/dev/serial0", baudrate=9600):
        self.ser = serial.Serial(port, baudrate, timeout=1)
        time.sleep(2)

    def read_distance(self):
        if self.ser.in_waiting:
            data = self.ser.read(4)  # depends on protocol
            return data
        return None


if __name__ == "__main__":
    sensor = DYP_A22()

    while True:
        reading = sensor.read_distance()
        print("Raw:", reading)
        time.sleep(0.2)