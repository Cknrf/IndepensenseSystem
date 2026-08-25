"""Project-wide configuration.

Holds values that vary between environments (e.g. which UART port a sensor is
wired to on this particular Pi) or that the developer may want to tune (e.g.
mock sensor behaviour during off-device development).

Hardware **protocol** constants that are fixed by the chip itself (frame
layout, header byte, checksum formula) stay inside their driver module — they
are not configuration, they are part of the chip's contract.

Secrets (API keys) are NOT in this file — it is committed. They live in a
`.env` at the project root, which `.gitignore` excludes and which is
loaded into the environment on import. See `ENV_FILE` below.
"""
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Secrets, loaded into `os.environ` when this module is imported.
#
# Why a file rather than `export` in a shell: the wearable runs under
# systemd, which does not inherit your login shell's environment, and you
# also run manual tests over SSH in fresh shells. An exported variable
# would work for exactly one of those. A file on disk works for both, and
# survives a reboot.
#
# Precedence: a variable already present in the real environment WINS over
# the file, so a one-off `INDEPENSENSE_CLOUD_API_KEY=... python -m ...`
# still overrides for a single run without editing anything.
#
# Format is one `KEY=value` per line; `#` comments and blank lines are
# ignored, and surrounding quotes are stripped. Deliberately not a real
# dotenv parser — no interpolation, no multi-line values, no export
# keyword. Fewer behaviours means fewer ways for a key to be silently
# mangled, and this file holds a handful of secrets, not a config language.
#
# Create it with:
#     cp .env.example .env      # then paste your key
ENV_FILE = PROJECT_ROOT / ".env"


def _load_env_file(path: Path) -> None:
    """Merge `KEY=value` lines from `path` into `os.environ`.

    Missing file is not an error — the system runs without a cloud key,
    it just answers unknown utterances locally. A malformed line is
    skipped with a warning rather than raising: a typo in a secrets file
    must not stop a safety device from booting.
    """
    try:
        text = path.read_text()
    except FileNotFoundError:
        return
    except OSError as exc:
        print(f"[config] could not read {path}: {exc}")
        return

    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or not key.strip():
            print(f"[config] {path}:{number}: expected KEY=value, skipping")
            continue
        key = key.strip()
        # Real environment wins — see the precedence note above.
        if key in os.environ:
            continue
        os.environ[key] = value.strip().strip("'\"")


_load_env_file(ENV_FILE)

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

# MPU6050 IMU — I²C wiring on the Raspberry Pi 5 (I2C1 bus).
# Accelerometer + gyroscope only; heading comes from the separate
# QMC5883P below. (The MPU9250 bought as an upgrade turned out to be a
# relabelled MPU6500 with no magnetometer die, so there is no upgrade
# path here — this is the IMU.)
MPU6050_I2C_BUS = 1
MPU6050_ADDRESS = 0x68

# QMC5883P magnetometer — a standalone compass chip on the same I2C1
# bus, at its own fixed address. Its own bus constant rather than
# reusing MPU6050_I2C_BUS: this is an unrelated device that merely
# shares the wires, and conflating them would hide that.
#
# 0x2C is the QMC5883P. The board was sold as a "QMC5883L", which would
# be 0x0D — a different chip with an incompatible register map. Confirm
# with `i2cdetect -y 1` before changing this; the address identifies the
# part. See docs/hardware.md.
MAG_I2C_BUS = 1
MAG_ADDRESS = 0x2C

# How often the main loop samples the compass. The QMC5883P is
# configured for a 10 Hz output rate (see the driver docstring), and no
# consumer needs heading even that fast — it changes on human
# timescales. 2 Hz keeps the shared I²C bus free for the things that
# are latency-sensitive: the IMU at 100 Hz, both DYP-A22 ultrasonics,
# and the UPS HAT.
HEADING_CHECK_INTERVAL_S = 0.5

# Magnetometer calibration. Identity values until you run the helper:
#   python -m indepensense.sensors.tests.manual.magnetometer_calibrate
# Paste the printed values here. Re-run whenever the wearable's
# physical layout changes materially (batteries moved, motor added,
# ferromagnetic component relocated).
#
# OFFSET (μT) cancels hard-iron bias — the constant pull of permanent
# magnets and ferrous mass bolted to the cane. SCALE (dimensionless)
# cancels soft-iron distortion, which stretches the field sphere into an
# ellipsoid so that a given rotation reads as a different number of
# degrees depending on which way you face.
MAG_OFFSET_X = 0.0
MAG_OFFSET_Y = 0.0
MAG_OFFSET_Z = 0.0
MAG_SCALE_X = 1.0
MAG_SCALE_Y = 1.0
MAG_SCALE_Z = 1.0

# Mount orientation: which sensor axis ends up pointing where on the
# assembled wearable. Heading is computed from the two axes that are
# HORIZONTAL once mounted, so these change with the mount, not with the
# chip — which is why they live here and not in the driver.
#
# Each is an axis letter with an optional sign: "x", "+y", "-z". The sign
# matters because flipping the board over reverses an axis without
# changing which axis it is.
#
#   Board lying FLAT (bench testing): x and y are horizontal, z is
#   vertical. Forward is whichever of x/y points away from you.
#
#   Board mounted UPRIGHT on the back of the vest: the board normal (z)
#   becomes horizontal — front/back — while y becomes vertical. Heading
#   then comes from z and x, e.g. MAG_FORWARD_AXIS = "-z" if +z points at
#   the wearer's back, with MAG_LEFT_AXIS following from it.
#
# Determine the signs empirically on the assembled unit — see the
# procedure in docs/hardware.md. Getting a sign wrong mirrors the
# heading, which reads plausibly while sending the user the wrong way.
MAG_FORWARD_AXIS = "+x"
MAG_LEFT_AXIS = "+y"

# Waveshare UPS HAT (E) — battery + power management, also on I2C1 bus.
# The HAT mounts under the Pi via pogo pins (no GPIO header conflict).
# I²C address `0x2D` — do NOT confuse with a generic INA219 at 0x43.
UPS_HAT_I2C_BUS = 1
UPS_HAT_I2C_ADDRESS = 0x2D

# Low-battery alert thresholds. Fires LOW_BATTERY when percentage drops
# BELOW `_PERCENT` (once, then latched until it recovers above
# `_RECOVERY_PERCENT`). This hysteresis prevents flapping alerts at
# the boundary.
LOW_BATTERY_PERCENT = 15
LOW_BATTERY_RECOVERY_PERCENT = 20
BATTERY_CHECK_INTERVAL_S = 10.0

# The latch is written here so it survives a restart.
#
# Without this it lives only in memory, and the systemd unit sets
# `Restart=on-failure`. A Pi crash-looping on a low battery would then
# re-alert on every boot — which, now that alerts fan out over SMS, texts
# every guardian each time. Needs a crash loop and a low battery at once,
# which is unlikely and exactly the kind of thing that happens during a
# demo.
LOW_BATTERY_STATE_PATH = PROJECT_ROOT / "var" / "low_battery_alerted"

# SIM7600G-H — GPS serial port. ModemManager labels this as (gps) in
# `mmcli -m <id>`. Enable GPS with `AT+CGPS=1` on /dev/ttyUSB2 first.
SIM7600_GPS_PORT = "/dev/ttyUSB1"
SIM7600_GPS_BAUDRATE = 115200

# Mock ultrasonic sensor — used for off-device development on macOS
MOCK_ULTRASONIC_MIN_CM = 20.0
MOCK_ULTRASONIC_MAX_CM = 200.0
MOCK_ULTRASONIC_PERIOD_S = 5.0

# Raspberry Pi Camera Module 3.
#
# 1280×720 gives YOLO ~4× more pixels per object than 640×480 — noticeably
# better detection of small items (mouse, phone, cables) at the cost of
# ~2× slower inference. For the wearable's on-demand vision.describe this
# tradeoff is fine (~1.5 s YOLO time invisible next to STT+LLM+TTS chain).
# Drop back to 640×480 if you need higher preview FPS.
CAMERA_WIDTH = 1280
CAMERA_HEIGHT = 720
CAMERA_FPS = 15
TEST_RECORDING_DIR = PROJECT_ROOT / "data" / "test" / "recordings"

# Where `tools/system_performance` writes its CSV logs.
#
# A fixed location rather than the current directory: `--csv perf.csv` used
# to land wherever you happened to be standing when you ran it, which on
# the Pi meant a stray CSV inside `src/indepensense/`. Profiling output is
# thesis evaluation data, not source.
#
# Under `data/`, which `.gitignore` already covers — these are generated
# measurements. Copy a run you want to keep somewhere tracked, with a note
# on what the device was doing at the time; a CPU trace is much less
# useful if you cannot say what was running.
PERF_LOG_DIR = PROJECT_ROOT / "data" / "performance"

# YOLOv8 object detection.
#
# The `-oiv7` suffix picks the variant trained on Open Images V7 (600
# classes) instead of the default COCO (80 classes) — 7.5× more object
# types recognized, including doors, stairs, windows, and many things
# COCO omits that matter for an assistive wearable.
#
# Model size progression (all use OIV7 weights):
#   yolov8n  ~3 M params   ~300 ms   good for people/furniture
#   yolov8s  ~11 M params  ~950 ms   adds keyboards, bottles
#   yolov8m  ~26 M params  ~1500-2000 ms   adds smaller items, fewer false positives
#   yolov8l  ~44 M params  ~3-5 s (borderline unusable on Pi CPU)
#
# yolov8m is the practical ceiling on Pi 5 CPU. For on-demand
# vision.describe the ~2 s inference is acceptable next to the ~5 s
# STT+LLM+TTS chain. Continuous testing at this size is painful
# (~0.5 FPS) but production doesn't run continuously.
#
# Ultralytics auto-downloads the weights (~52 MB) on first use.
YOLO_MODEL_PATH = PROJECT_ROOT / "models" / "yolov8m-oiv7.pt"
# 0.3 (was 0.5) — more permissive so small/uncertain objects like a
# distant mouse or partially-occluded cable don't get silently filtered.
# Trade-off: more false positives. Watch the continuous_detect_test
# output for hallucinations; if they return, dial back up to 0.4.
YOLO_CONFIDENCE_THRESHOLD = 0.3

# Tesseract OCR — reads printed text via `vision.read` intent.
# `OCR_LANGUAGES` maps our language codes to Tesseract language
# packs.
#
# Installation on the Pi:
#   sudo apt install -y tesseract-ocr tesseract-ocr-eng
# The Debian Trixie apt repo does NOT ship `tesseract-ocr-tgl`, so
# Tagalog data must be downloaded manually from upstream. Use the
# standard tessdata repo (the `tessdata_fast` variant does not have
# a Tagalog model as of 2026-07):
#   sudo wget -O /usr/share/tesseract-ocr/5/tessdata/tgl.traineddata \
#       https://github.com/tesseract-ocr/tessdata/raw/main/tgl.traineddata
# Verify with:  tesseract --list-langs   (should list eng, osd, tgl)
#
# If `tgl` isn't installed and the active language is "tl", vision.read
# will fail with a graceful "couldn't read the text" spoken response —
# the wearable doesn't crash.
#
# `OCR_MAX_CHARS` caps spoken responses — a full receipt/menu can be
# 1000+ characters, which is ~90 s of Piper speech. Truncating to
# ~500 characters (~30 s) keeps responses digestible.
OCR_LANGUAGES = {
    "en": "eng",
    "tl": "tgl",
}
OCR_MAX_CHARS = 500

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

# Language the wearable starts in, and the set it can switch between.
#
# Tagalog is the default because it is the system's priority language and
# most of the intended users speak it first. The user switches with a
# voice command ("lumipat sa Ingles" / "switch to Tagalog") and the choice
# persists to `LANGUAGE_STATE_PATH` so it survives a reboot.
#
# The switch phrase must be spoken in the language currently active.
# Whisper is pinned per language (`whisper.py` passes `language=`) rather
# than auto-detecting, because detection on a two-second command is
# unreliable and because each language loads a different model size —
# auto-detect would mean transcribing twice on a CPU-only Pi. See
# docs/voice.md.
DEFAULT_LANGUAGE = "tl"
SUPPORTED_LANGUAGES = ("en", "tl")
LANGUAGE_STATE_PATH = PROJECT_ROOT / "var" / "language"


# Physical buttons (KY-004 style breakouts with on-board 10kΩ pull-down)
PTT_BUTTON_GPIO = 23         # physical pin 16 — push-to-talk (click to start, click to stop)
EMERGENCY_BUTTON_GPIO = 24   # physical pin 18 — single click fires emergency.trigger
REPEAT_BUTTON_GPIO = 25      # physical pin 22 — single click repeats last instruction

# Active buzzer — direct GPIO drive (see feedback/gpio_buzzer.py for the
# current-draw caveat if the Pi shows undervoltage warnings).
BUZZER_GPIO = 18             # physical pin 12

# Voice pipeline safety cap. If the user presses PTT and never presses
# again (or does so out of habit and forgets), recording auto-stops
# after this many seconds. Downstream STT/LLM still runs on whatever
# was captured — so worst case the user hears "Sorry, I didn't catch
# that" and can retry. 30 s is comfortable for any real command; longer
# recordings are almost always accidental.
PTT_MAX_RECORDING_S = 30.0

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
#
# Model choice — Qwen 3 1.7B over Qwen 2.5 1.5B Instruct:
# Qwen 2.5's model card claims 29 languages and Tagalog/Filipino is NOT among
# them; it classified our Tagalog probe cases by pattern-matching the few-shot
# examples in the system prompt rather than from real language coverage. Qwen 3
# expands to 119 languages/dialects, Tagalog included. With Tagalog as the
# system's priority language that support has to be in the model, not carried
# entirely by prompt exemplars. The 1.7B tier keeps us in the same size class,
# so the RAM and latency profile stays close to what the Pi 5 budget allows.
#
# Qwen 3 is a *hybrid reasoning* model — left alone it emits a `<think>` block
# before its answer, which breaks both the strict-JSON contract and the latency
# budget. The parser disables this per request (`"think": False`); see
# `intents/parser.py`.
#
# `NLU_TIMEOUT_S` is the per-query budget once the model is already loaded.
# Cold model loads are absorbed by the parser's startup warmup, which uses
# `NLU_WARMUP_TIMEOUT_S`.
# Cloud LLM fallback — see intents/cloud.py for the full rationale.
#
# When the local NLU returns `unknown` AND we are online, the transcript
# is forwarded to a cloud LLM instead of answering "I didn't catch that".
# `unknown` is the sole entry point on purpose: a dedicated cloud intent
# would give the local classifier a tempting bucket for anything it was
# unsure about, and "take me to the hospital" reaching a chatbot instead
# of navigation is a failure this device cannot afford.
#
# No provider is chosen yet. `CLOUD_LLM_ENABLED` stays False until a
# driver exists, so the wearable answers exactly as it does today. The
# API key belongs in the environment, never in this file — config.py is
# committed.
#
# `CLOUD_MAX_RESPONSE_CHARS` is a backstop, not the real control. The
# answer is spoken by Piper, so a provider returning three paragraphs is
# a 90-second monologue; the driver's prompt should ask for brevity and
# this catches the times it doesn't. Same reasoning and same size as
# OCR_MAX_CHARS above.
CLOUD_LLM_ENABLED = True
CLOUD_LLM_API_KEY_ENV = "INDEPENSENSE_CLOUD_API_KEY"

# Mistral. The env var above is provider-neutral on purpose — the driver
# is one implementation of the `CloudAnswerer` protocol and swapping it
# should not mean renaming a secret.
#
# `mistral-small-latest` over `mistral-large-latest`: the job here is a
# one-or-two-sentence factual answer, not reasoning, and the small model
# is markedly faster and cheaper for that. Revisit only if answer quality
# proves inadequate — not for its own sake.
#
# 100 max tokens is a latency control first and a cost control second.
# Generation time scales with output length, so this is the biggest lever
# available; the system prompt also asks for at most 40 words, because
# `max_tokens` truncates mid-sentence while an instruction yields a
# complete short answer.
CLOUD_LLM_URL = "https://api.mistral.ai/v1/chat/completions"
CLOUD_LLM_MODEL = "mistral-small-latest"
CLOUD_LLM_MAX_TOKENS = 100

# 10 s, and the constraint is the user's patience, not the provider's.
# The cloud call sits on top of a chain that already costs 4-6 s (Tagalog
# STT ~2-3 s, local NLU ~1-2 s, Piper ~1 s), so by the time this timeout
# expires the user has been holding a cane on a street corner for fifteen
# seconds with nothing but the "thinking" cue. Failing into "I couldn't
# get an answer" at 10 s respects them more than succeeding at 20 s.
#
# Two things matter more than this value for actual latency:
#   - cap the provider's max output tokens (~100). Generation time scales
#     with output length, so this is the largest single lever — and it
#     keeps answers short enough to speak, which is wanted anyway.
#   - reuse the HTTP connection. A cold TLS handshake is ~3 round trips
#     before the request is even sent; against an EU-hosted provider from
#     the Philippines that is roughly 0.75 s of pure setup. A persistent
#     session inside the driver removes it from every call after the first.
CLOUD_LLM_TIMEOUT_S = 10.0
CLOUD_MAX_RESPONSE_CHARS = 500

OLLAMA_URL = "http://127.0.0.1:11434"
NLU_MODEL = "qwen3:1.7b"
NLU_PROMPT_PATH = PROJECT_ROOT / "prompts" / "nlu_system.md"
NLU_TIMEOUT_S = 30.0
NLU_WARMUP_TIMEOUT_S = 90.0

# Internet connectivity probe. The heartbeat sender uses this before
# each POST to populate `internet_status` honestly (rather than
# hardcoded True). Cloudflare's 1.1.1.1 is the target — direct IP so
# DNS breakage doesn't confuse it with internet breakage, high uptime,
# fast response globally.
INTERNET_PROBE_URL = "http://1.1.1.1"
INTERNET_PROBE_TIMEOUT_S = 2.0

# Guardian-dashboard backend (NestJS + MySQL, see ../IndepenSense).
#
# Production. No port: https implies 443.
#
# MUST be https. Every `/raspberry/*` request carries the device
# credential as a bearer token, and over plaintext that is readable by
# every hop in between — so `net.require_https` refuses at startup rather
# than leaking it quietly. Only `http://localhost` is exempt, because that
# traffic never reaches a network.
#
# For local backend work, point this at `http://localhost:3000` rather
# than a LAN or Tailscale address — loopback is the only plaintext form
# that will start.
BACKEND_URL = "https://indepensense-api.maendou.com"
HEARTBEAT_INTERVAL_S = 30
TELEMETRY_TIMEOUT_S = 5.0

# Per-device credential, written by provisioning as one line:
#
#     <device-uuid>.<secret>
#
# There is deliberately no `DEVICE_ID` constant any more. It used to be
# hardcoded here and sent in every request body, which meant two problems:
# the backend trusted an identifier the caller simply asserted, and the
# value had to be hand-edited per unit — so a cloned SD card silently
# reported as the wrong device. The UUID now comes out of this file, so
# identity and authority are the same fact and cannot drift apart.
#
# The file must be readable by the account the service runs as (`User=` in
# deploy/systemd/indepensense.service). Root-owned mode 0600 is NOT
# readable by that account — see deploy/systemd/README.md.
DEVICE_KEY_PATH = Path("/etc/indepensense/device.key")

# Guardian contact list, used for emergency SMS.
#
# Fetched once at startup from the backend and written to disk. The cache
# is what makes SMS work at all: the device needs these numbers precisely
# when it has no data connection, which is also when it cannot fetch
# them. A boot with no network falls back to the last known list.
#
# Consequence to be aware of: a guardian added while the device is
# running is not known to it until the next restart. Accepted — guardian
# lists change on human timescales, and re-fetching on a timer would
# spend metered cellular data to re-transmit an almost always identical
# list.
GUARDIAN_CACHE_PATH = PROJECT_ROOT / "var" / "guardians.json"
GUARDIAN_FETCH_TIMEOUT_S = 10.0

# Emergency SMS via the SIM7600's cellular connection.
#
# SMS is sent on every alert below regardless of whether the data
# connection is up. That redundancy is deliberate: SMS traverses the
# control channel and gets through in marginal-signal conditions that
# defeat an HTTP POST, and a duplicate notification costs a guardian
# nothing while a missed one could cost much more. It is not conditional
# on a signal-strength reading — a heuristic that mis-fires in the one
# situation the feature exists for is worse than always sending.
#
# CONNECTIVITY is excluded: it fires on network transitions, which is
# both frequent and precisely the condition under which an SMS about
# connectivity tells the guardian nothing they can act on.
SMS_ENABLED = True
SMS_ALERT_EVENT_TYPES = ("Emergency Alert", "Fall Detection", "Low Battery")
SMS_SEND_TIMEOUT_S = 30.0
# Modem index for `mmcli -m N`. None auto-discovers via `mmcli -L`, which
# is what you want unless more than one modem is attached.
SMS_MODEM_INDEX = None
# Country calling code used to expand local numbers (0917... -> +63917...).
# The backend stores whatever the guardian typed into the web form.
SMS_DEFAULT_COUNTRY_CODE = "63"