"""Project-wide configuration.

Holds values that vary between environments (e.g. which UART port a sensor is
wired to on this particular Pi) or that the developer may want to tune (e.g.
mock sensor behaviour during off-device development).

Hardware **protocol** constants that are fixed by the chip itself (frame
layout, header byte, checksum formula) stay inside their driver module — they
are not configuration, they are part of the chip's contract.
"""
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# DYP-A22 ultrasonic sensors — UART wiring on the Raspberry Pi 5
DYP_A22_PRIMARY_PORT = "/dev/ttyAMA0"
DYP_A22_SECONDARY_PORT = "/dev/ttyAMA4"
DYP_A22_BAUDRATE = 115200

# MPU6050 IMU — I²C wiring on the Raspberry Pi 5 (I2C1 bus)
MPU6050_I2C_BUS = 1
MPU6050_ADDRESS = 0x68

# Mock ultrasonic sensor — used for off-device development on macOS
MOCK_ULTRASONIC_MIN_CM = 20.0
MOCK_ULTRASONIC_MAX_CM = 200.0
MOCK_ULTRASONIC_PERIOD_S = 5.0

# Raspberry Pi Camera Module 3
CAMERA_WIDTH = 640
CAMERA_HEIGHT = 480
CAMERA_FPS = 15
TEST_RECORDING_DIR = PROJECT_ROOT / "data" / "test" / "recordings"

# YOLOv8 object detection
YOLO_MODEL_PATH = PROJECT_ROOT / "models" / "yolov8n.pt"
YOLO_CONFIDENCE_THRESHOLD = 0.5
