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

# SIM7600G-H — GPS serial port. ModemManager labels this as (gps) in
# `mmcli -m <id>`. Enable GPS with `AT+CGPS=1` on /dev/ttyUSB2 first.
SIM7600_GPS_PORT = "/dev/ttyUSB1"
SIM7600_GPS_BAUDRATE = 115200

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

# Local routing / geocoding services (see docs/graphhopper.md, docs/photon.md).
# When running from a Mac against the Pi, replace 127.0.0.1 with the Pi's LAN IP.
GRAPHHOPPER_URL = "http://127.0.0.1:8989"
PHOTON_URL = "http://127.0.0.1:2322"

# Voice — see docs/voice.md for model downloads.
#
# Piper does not yet ship a native Filipino/Tagalog voice. As a workaround the
# Indonesian voice `id_ID-news_tts-medium` is used to synthesise Tagalog text
# (both are Austronesian languages with matching vowel systems). Language
# switching between English and Tagalog is not wired up yet — the multi-voice
# structure is in place so it can be enabled later without refactoring.
PIPER_VOICES = {
    "en": PROJECT_ROOT / "models" / "voices" / "en_US-lessac-medium.onnx",
    "tl": PROJECT_ROOT / "models" / "voices" / "id_ID-news_tts-medium.onnx",
}
WHISPER_MODEL_DIR = PROJECT_ROOT / "models" / "whisper"

# Whisper model size per language. English uses `tiny` because it's accurate
# enough and keeps STT latency ~1.4 s per 25 s clip. Tagalog uses `small`
# because Tagalog is underrepresented in Whisper's training data and both
# `tiny` and `base` produced too-mangled transcripts to be usable
# (validated 2026-07-19).
WHISPER_MODELS = {
    "en": "tiny",
    "tl": "small",
}
VOICE_TEST_DIR = PROJECT_ROOT / "data" / "test" / "voice"

# Active system language. Currently fixed at build time; will become a
# runtime setting once guardian-dashboard control is implemented.
SYSTEM_LANGUAGE = "en"

# Fall detection thresholds (starting from the literature; tune empirically)
FALL_FREEFALL_THRESHOLD_G = 0.5
FALL_FREEFALL_MIN_DURATION_S = 0.1
FALL_IMPACT_THRESHOLD_G = 2.0
FALL_IMPACT_WINDOW_S = 0.5
FALL_STILLNESS_MAX_STDDEV_G = 0.15
FALL_STILLNESS_DURATION_S = 2.0