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

# DYP-A22 ultrasonic sensors — UART wiring on the Raspberry Pi 5.
# The wearable is cane-mounted with both sensors facing forward:
# - TOP:    head-level obstacles (branches, signage, low awnings).
#           This is the sensor that provides unique value — the user's
#           cane can't sweep the air above them.
# - BOTTOM: foot-level obstacles (curbs, walls, planters). Supplements
#           what the cane already detects by touch.
DYP_A22_TOP_PORT = "/dev/ttyAMA0"
DYP_A22_BOTTOM_PORT = "/dev/ttyAMA4"
DYP_A22_BAUDRATE = 115200

# Obstacle warning thresholds and cooldown. The main app polls both
# ultrasonic sensors in the fall-detection loop and fires vibration +
# (for TOP only) buzzer alerts when the reading crosses into the
# warning or danger zone. See app.py for the full pattern definitions.
OBSTACLE_WARNING_CM = 100.0      # early notice — obstacle within reach
OBSTACLE_DANGER_CM = 50.0        # imminent — user should stop
OBSTACLE_COOLDOWN_S = 2.0        # per sensor: don't fire the same tier again

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

# Vocabulary hints for Whisper. Whisper reads `initial_prompt` as "recent
# context" and biases its decoder toward the words that appear in it.
# We use this to correct tiny-model mishearing of Filipino brand names
# (e.g. "Jollibee" got heard as "Jalebi" until we added it here).
# Hard limit ~224 tokens — keep each language's hint focused.
WHISPER_INITIAL_PROMPTS: dict[str, str] = {
    "en": (
        "This is a voice assistant for a person in the Philippines. "
        "The user may say Jollibee, McDonald's, KFC, Chowking, Mang Inasal, "
        "Greenwich, Max's, SM Lipa, Robinsons, Ayala, Puregold, Landers, "
        "Metrobank, BDO, BPI, Landbank, 7-Eleven, Mini Stop, "
        "Mercury Drug, Watsons, National Bookstore."
    ),
    "tl": "",   # Tagalog small model transcribes local brands well already
}

VOICE_TEST_DIR = PROJECT_ROOT / "data" / "test" / "voice"

# Active system language. Currently fixed at build time; will become a
# runtime setting once guardian-dashboard control is implemented.
SYSTEM_LANGUAGE = "en"

# Physical buttons (KY-004 style breakouts with on-board 10kΩ pull-down)
PTT_BUTTON_GPIO = 23         # physical pin 16 — push-to-talk (click to start, click to stop)
EMERGENCY_BUTTON_GPIO = 24   # physical pin 18 — single click fires emergency.trigger
REPEAT_BUTTON_GPIO = 25      # physical pin 22 — single click repeats last instruction

# Active buzzer — direct GPIO drive (see feedback/gpio_buzzer.py for the
# current-draw caveat if the Pi shows undervoltage warnings).
BUZZER_GPIO = 18             # physical pin 12

# Vibration motors — driven through NPN transistors (motors draw more
# current than a GPIO can safely source). See docs/hardware.md for the
# transistor + flyback-diode circuit each motor needs.
VIBRATION_FRONT_GPIO = 17    # physical pin 11
VIBRATION_RIGHT_GPIO = 27    # physical pin 13
VIBRATION_LEFT_GPIO = 22     # physical pin 15

# Fall detection thresholds (starting from the literature; tune empirically)
FALL_FREEFALL_THRESHOLD_G = 0.5
FALL_FREEFALL_MIN_DURATION_S = 0.1
FALL_IMPACT_THRESHOLD_G = 2.0
FALL_IMPACT_WINDOW_S = 0.5
FALL_STILLNESS_MAX_STDDEV_G = 0.15
FALL_STILLNESS_DURATION_S = 2.0

# Local LLM used for natural-language intent parsing. See prompts/nlu_system.md
# for the system prompt and docs/voice.md → intent parser section for setup.
# Qwen 2.5 1.5B Instruct was chosen empirically over 3B: 100% intent accuracy
# on our 30-case benchmark, ~2.8 s per query on Pi 5, ~1.4 GB RAM footprint.
#
# `NLU_TIMEOUT_S` is the per-query budget once the model is already loaded.
# Cold model loads (~25 s for 1.5B on Pi 5) are absorbed by the parser's
# startup warmup, which uses `NLU_WARMUP_TIMEOUT_S`.
OLLAMA_URL = "http://127.0.0.1:11434"
NLU_MODEL = "qwen2.5:1.5b-instruct"
NLU_PROMPT_PATH = PROJECT_ROOT / "prompts" / "nlu_system.md"
NLU_TIMEOUT_S = 30.0
NLU_WARMUP_TIMEOUT_S = 90.0

# Guardian-dashboard backend (NestJS + MySQL, see ../IndepenSense).
# The dev seed provisions DEVICE_ID with an assisted user + linked guardian.
# Every deployed wearable gets its own unique UUID here.
#
# Currently pointed at the dev laptop's Tailscale IP because the backend
# runs there during development, not on the Pi itself.
BACKEND_URL = "http://100.104.82.110:3000"
DEVICE_ID = "00000000-0000-0000-0000-000000000001"
HEARTBEAT_INTERVAL_S = 30
TELEMETRY_TIMEOUT_S = 5.0