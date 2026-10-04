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

# Obstacle warning thresholds. The main app polls both ultrasonic sensors
# in the fall-detection loop and fires vibration + (for TOP only) buzzer
# alerts when the reading crosses into the warning or danger zone. See
# app.py for the full pattern definitions.
OBSTACLE_WARNING_CM = 100.0      # early notice — obstacle within reach
OBSTACLE_DANGER_CM = 50.0        # imminent — user should stop

# How far the obstacle has to recede before that tier can fire again.
#
# Without it, alerts repeated on a fixed cooldown for as long as anything
# stayed in range: a field log shows `danger at 42 cm` firing every two
# seconds for minutes, each one a motor pulse. Walking a corridor with a
# wall an arm's length away would buzz continuously, and a signal that
# never stops is one the wearer learns to ignore.
#
# A plain "only fire when the distance changes" rule does not work either,
# and the reason is the cane itself: a hand holding it moves centimetres
# without the user going anywhere, so the reading is never still. The band
# has to be wide enough to swallow that jitter — 15 cm is comfortably
# above the sway seen sitting still, and well below the 50 cm step between
# tiers, so a genuine approach still crosses it.
OBSTACLE_RELEASE_CM = 15.0

# Backstop re-notify for the DANGER tier only. Someone walking a long wall
# at 42 cm should not be told once and then left; someone at 80 cm does
# not need reminding at all. Long enough not to nag, short enough that a
# standing hazard is not forgotten.
OBSTACLE_DANGER_REPEAT_S = 15.0

# How long a cached ultrasonic reading stays worth repeating.
#
# Read by `vision.describe` when the camera recognises nothing, so it can
# answer "something is about 40 centimetres away" instead of "I don't see
# anything I recognize". The DYP-A22 emits at ~10 Hz, so a reading older
# than this means the sensor has stopped reporting — and the user has had
# a second to move, which at walking pace is about a metre.
OBSTACLE_READING_MAX_AGE_S = 1.0

# How long the emergency button stays armed-down after firing.
#
# Someone who has just pressed a panic button presses it again — because
# nothing visibly happened, because they are frightened, because their
# hand is shaking. A field log shows three presses in a row, each one a
# full alert: three guardian notifications, three SMS attempts and three
# spoken confirmations talking over each other, all describing one event.
#
# Suppression here is only of the *re-send*. Every press still fires the
# full buzzer-and-motor pattern and still cancels whatever voice work is
# running. The buzzer especially: it is the only part of this device a
# bystander can perceive, so someone who needs attention now must be able
# to lean on the button and keep it sounding. See `_on_emergency_press`.
#
# The window is measured from the last alert that actually went out, not
# from the last press, so a held-down button does not postpone the next
# send indefinitely — it sends again every `EMERGENCY_REARM_S`.
#
# Short on purpose. This is a debounce for a panicking hand, not a rate
# limit: a genuine second emergency ten seconds after the first is a real
# thing and must get through. The window is also cleared early when the
# first alert is reported as having reached nobody, so that pressing again
# after a failure retries instead of being ignored.
EMERGENCY_REARM_S = 10.0

# The "still working on it" blip played while a voice command is being
# transcribed and classified.
#
# That stretch is 3-7 s of total silence on the Pi — speech-to-text, then
# a 1.7B model on a CPU — and the user has already had their stop chime,
# so from their side nothing distinguishes it from a device that died.
# "Let me think about that" only covers the cloud path, and only after the
# local model has already spent its seconds deciding to escalate.
#
# `DELAY` is the grace period before the first blip: a command answered
# faster than this never ticks at all, so the common quick reply ("what
# time is it") stays clean. `INTERVAL` is the gap between blips after
# that — slow enough to read as a heartbeat rather than a countdown.
WAITING_CUE_DELAY_S = 1.5
WAITING_CUE_INTERVAL_S = 1.2

# Bench mute for the obstacle buzzer. The active buzzer is deliberately
# loud — it has to cut through street noise — which makes indoor desk
# testing unpleasant for everyone in the room. With this False the TOP
# sensor's warning and danger tiers fire their vibration patterns as
# normal and simply skip the beep; nothing else about the tiering,
# cooldowns or logging changes, so the obstacle path is still fully
# exercised while testing.
#
# This only silences obstacle warnings. The emergency alert keeps its
# beep unconditionally — a safety signal must not be mutable by a
# convenience flag.
#
# MUST be True for any demo, field test or deployment.
OBSTACLE_BUZZER_ENABLED = False

# MPU6050 IMU — I²C wiring on the Raspberry Pi 5 (I2C1 bus, shared with
# the UPS HAT only; the compass has its own bus, see MAG_I2C_BUS).
# Accelerometer + gyroscope only; heading comes from the separate
# QMC5883P below. (The MPU9250 bought as an upgrade turned out to be a
# relabelled MPU6500 with no magnetometer die, so there is no upgrade
# path here — this is the IMU.)
MPU6050_I2C_BUS = 1
MPU6050_ADDRESS = 0x68

# QMC5883P magnetometer — a standalone compass chip on its own I²C bus
# (I2C4, header pins 24/21), at its own fixed address.
#
# Bus 4, not 1: with the compass on I2C1 alongside the MPU6050 and the
# UPS HAT, three sets of breakout pull-ups in parallel dropped the bus
# to ~1 kΩ, below what a device can reliably sink. The bus failed
# intermittently and the failure migrated between devices. Bus 4 is a
# software (bit-banged) bus and needs
# `dtoverlay=i2c-gpio,bus=4,i2c_gpio_sda=8,i2c_gpio_scl=9` in
# /boot/firmware/config.txt — the hardware `i2c4` overlay is BCM2711
# (Pi 4) only and does nothing here. See docs/hardware.md.
#
# 0x2C is the QMC5883P. The board was sold as a "QMC5883L", which would
# be 0x0D — a different chip with an incompatible register map. Confirm
# with `i2cdetect -y 4` before changing this; the address identifies the
# part.
MAG_I2C_BUS = 4
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
# Measured on the assembled vest with `magnetometer_axes`, 2026-10-03.
#
# Pass 1, run twice: spans x=77.6, y=21.1, z=79.6 and x=77.6, y=20.2,
# z=78.3 — y is vertical both times at a ratio of 0.26, comfortably
# inside the 0.35 limit. Matches the upright-on-the-back mount described
# above, so heading comes from z and x.
#
# Pass 2 saw 196° and 81° of rightward turn across the two runs and
# agreed on these signs, which is the half that matters: the heading now
# rotates the correct way, and a mirrored one cannot be fixed by any
# later offset.
#
# PROVISIONAL on where zero sits. Four combinations rotate correctly and
# measured an identical turn, so pass 2 cannot separate them — they
# differ only by whole 90° steps. Confirm against one known bearing and
# step through this list if the heading is out by about 90, 180 or 270°:
#
#     forward="+x"  left="-z"
#     forward="-x"  left="+z"
#     forward="+z"  left="+x"
#     forward="-z"  left="-x"      <- in use
# Fine rotation applied to the computed heading, in degrees, added last.
#
# `MAG_FORWARD_AXIS` / `MAG_LEFT_AXIS` can only express whole 90° steps —
# they choose which axes to use and which way round. Whatever is left
# after that is a constant rotation: the board is not mounted perfectly
# square to the wearer's facing, and the mount is permanent, so the error
# is permanent too.
#
# Measured by `magnetometer_swing` against a phone compass, which is also
# where the rest of the horizontal calibration comes from.
MAG_HEADING_OFFSET_DEG = 0.0

MAG_FORWARD_AXIS = "-z"
MAG_LEFT_AXIS = "-x"

# Whether the compass may be acted upon. **Leave False until calibrated.**
#
# The offsets and scales above are at their identity values and the axis
# roles are the flat-board defaults, so the heading this produces today is
# not merely imprecise — it can be mirrored or off by tens of degrees while
# reading perfectly plausibly. That is the dangerous failure: a confident
# wrong bearing sends the user the wrong way, and they have no way to see
# that it is wrong.
#
# `App.latest_heading()` returns None while this is False, so every
# consumer degrades to the behaviour it had before the compass existed.
# The driver still opens and `_check_heading` still caches, so the manual
# tests and the calibration sweep work unaffected.
#
# To flip it, on the ASSEMBLED wearable:
#   1. Determine the real MAG_FORWARD_AXIS / MAG_LEFT_AXIS — the defaults
#      above assume a board lying flat, and a vest-mounted board is not.
#      Procedure in docs/hardware.md.
#   2. python -m indepensense.sensors.tests.manual.magnetometer_calibrate
#      and paste the printed offsets and scales above. It grades its own
#      sweep and refuses to print values for a bad one — a sweep taken
#      near steel produces offsets that look entirely reasonable and a
#      heading that is wrong, so the grade is the only thing between you
#      and a confident wrong bearing. Do it outdoors, clear of buildings.
#   3. Check the heading against a phone compass at all four cardinals.
#   4. Set this True.
COMPASS_CALIBRATED = False

# Turn-to-face guidance: pointing the user the right way before they walk.
#
# Every number below is a starting point rather than a finding. Whether
# 800 ms reads as "slower" than 400 ms to somebody wearing the vest, and
# whether 15° is tight enough to set off usefully, are human-factors
# questions that need a calibrated prototype and a person in a corridor.
# They live here so that session is tuning, not rewriting.
#
# Skipped entirely while COMPASS_CALIBRATED is False.

# How far down the route to aim. A point two metres ahead gives a bearing
# that swings wildly with GPS jitter, and acting on it would spin the user
# on the spot.
ORIENTATION_MIN_TARGET_DISTANCE_M = 15.0

# Close enough to start walking. Tighter than the compass can actually
# resolve once mounted would be false precision, and a pedestrian converges
# onto the path within the first few metres anyway.
ORIENTATION_ALIGNED_TOLERANCE_DEG = 15.0

# Once aligned, the band widens to this. Without the hysteresis a user who
# drifts one degree past the boundary is told to turn back, overshoots, and
# oscillates — the device nagging somebody who is already facing the right
# way.
ORIENTATION_RELEASE_TOLERANCE_DEG = 30.0

# (error greater than N degrees, seconds between pulses). Widest first.
ORIENTATION_BANDS = (
    (90.0, 0.8),
    (30.0, 0.4),
    (0.0, 0.2),
)

# Give up after this long and let them start walking. It must never trap
# somebody standing in the street: a compass that cannot settle, or a user
# who does not understand the pulses, has to end with the wearable saying
# so rather than buzzing indefinitely.
ORIENTATION_TIMEOUT_S = 20.0

# Waveshare UPS HAT (E) — battery + power management, also on I2C1 bus.
# The HAT mounts under the Pi via pogo pins (no GPIO header conflict).
# I²C address `0x2D` — do NOT confuse with a generic INA219 at 0x43.
UPS_HAT_I2C_BUS = 1
UPS_HAT_I2C_ADDRESS = 0x2D

# What the HAT's fuel gauge reports when the pack is actually flat.
#
# The gauge does not read 0 at empty. Measured on this unit across three
# discharges: the Pi lost power, and on reconnecting the charger and
# reading immediately the gauge showed 59%. So 59 is the real floor and
# the usable span is 41 raw points, not 100.
#
# This was not cosmetic. `LOW_BATTERY_PERCENT` (15) and
# `CRITICAL_BATTERY_PERCENT` (5) both sit *below* a floor the gauge never
# reaches, so neither alert had ever fired or could: the wearable gave no
# warning at all and simply died. `WaveshareUPSHatE` now rescales the raw
# reading onto 0-100 against this constant, which puts the two thresholds
# back inside the range the gauge actually produces (raw ~65% and ~61%).
#
# Rounded UP from the measured 59, and deliberately so. The error is
# asymmetric: setting this *below* the true floor warns early, which
# costs the user nothing, while setting it above reports "10 percent
# left" on a pack that is already dead — a warning that arrives after it
# is useful. If a later discharge dies at a higher raw reading, raise
# this; never lower it to the smallest value ever seen.
#
# Re-measure with:
#   python -m indepensense.power.tests.manual.single_ups_test --csv
# through a full discharge. Its `mah_per_pct` column also settles whether
# the gauge is a voltage reading in disguise — if it is, the true curve
# sags in the lower half and this linear map over-reports in exactly the
# band the warnings live in. `raw_percentage` is kept on every
# `BatteryReading` so the correction can always be undone for analysis.
BATTERY_EMPTY_RAW_PERCENT = 60.0

# Low-battery alert thresholds, in CORRECTED percent (see
# `BATTERY_EMPTY_RAW_PERCENT`). Fires LOW_BATTERY when percentage drops
# BELOW `_PERCENT` (once, then latched until it recovers above
# `_RECOVERY_PERCENT`). This hysteresis prevents flapping alerts at
# the boundary.
LOW_BATTERY_PERCENT = 15
LOW_BATTERY_RECOVERY_PERCENT = 20
BATTERY_CHECK_INTERVAL_S = 10.0

# Second, spoken-only tier. The wearer is told at `LOW_BATTERY_PERCENT`
# ("charge soon") and again here ("about to shut down"), because those are
# different instructions and 15% on this pack is still a long while.
#
# Only the critical one preempts speech in progress. A 15% warning is not
# worth cutting off a turn instruction the user is mid-way through hearing;
# "your device is about to die" is, because everything else the wearable
# might be saying stops mattering shortly afterwards.
#
# No second guardian alert fires here. They were already told at 15% over
# both SMS and the dashboard, and texting them again as the battery dies
# tells them nothing they can act on.
CRITICAL_BATTERY_PERCENT = 5
CRITICAL_BATTERY_RECOVERY_PERCENT = 10

# Separate latch file from the 15% one, so the two tiers cannot clear each
# other. Same presence-is-the-state trick — see `LOW_BATTERY_STATE_PATH`.
CRITICAL_BATTERY_STATE_PATH = PROJECT_ROOT / "var" / "critical_battery_alerted"

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

# Where the UPS manual test writes its CSV logs. Same reasoning as
# `PERF_LOG_DIR` — a battery trace is evaluation data, not source, and a
# charge cycle takes hours, so it must not matter which directory you
# happened to launch the test from.
BATTERY_LOG_DIR = PROJECT_ROOT / "data" / "battery"

# Where a face-at-a-time calibration sweep accumulates its samples.
#
# The six faces can be recorded as six separate commands, minutes apart,
# so the samples have to outlive the process that captured them. Same
# reasoning as the two above: it must not matter which directory the test
# was launched from, and this is working data rather than source.
MAG_SWEEP_DIR = PROJECT_ROOT / "data" / "calibration"

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

# How many candidates to pull from Photon before deciding which one the
# user meant (`routing/ranking.py`).
#
# This used to be 1, which is the bug that sent a user in Lipa toward a
# Jollibee in Tacloban: Photon ranks by its own blend of text relevance and
# an opaque location bias, and asking for a single result means accepting
# that blend with no recourse. You cannot re-rank a list of one.
#
# 10 is "enough that the intended branch is almost certainly in the set,
# small enough that the response stays tiny and the sort is free". Not a
# magic number — raise it if a chain turns out to have more nearby
# branches than this in one city.
GEOCODE_CANDIDATE_LIMIT = 10

# Voice — see docs/voice.md for model downloads.
#
# TTS is two engines, not one. Piper has no Filipino/Tagalog voice, so the
# `tl` slot was an Indonesian voice standing in on shared Austronesian
# phonology — intelligible but audibly not Tagalog, and its espeak-ng
# frontend read digits out as Indonesian numbers. Tagalog now uses Meta's
# natively-trained `facebook/mms-tts-tgl`. `MultiEngineTTS` in
# voice/router.py is what puts the two behind one interface.
#
# Together these two dicts must cover `intents.messages.LANGUAGES`.
PIPER_VOICES = {
    "en": PROJECT_ROOT / "models" / "voices" / "en_US-lessac-medium.onnx",
}

# One MMS checkpoint per language, as a local snapshot of the Hugging Face
# repo. Licensed CC-BY-NC 4.0 — fine for academic use, but a commercial
# build would need a differently-licensed Tagalog voice.
MMS_VOICES = {
    "tl": PROJECT_ROOT / "models" / "voices" / "mms-tts-tgl",
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

# Pre-rendered speech played before the models are loaded.
#
# Startup takes 2-3 minutes — Whisper, two TTS engines, and the Ollama
# warmup — and to a blind user silence is indistinguishable from a device
# that failed to boot. The wearable has to say something immediately, but
# it cannot *synthesise* anything yet: TTS is one of the things still
# loading. So the greeting is rendered once, to a file, and replayed from
# disk on every later boot. Playback needs only `soundfile` + PortAudio,
# both available at the first line of `start()`.
#
# Filenames embed a hash of the message text, so editing
# `messages.get("system.starting")` invalidates the old recording instead
# of leaving the wearable saying something that is no longer in the source.
# Gitignored and regenerated on demand rather than committed — a binary in
# git that must stay in step with a string in Python is a drift waiting to
# happen.
STARTUP_AUDIO_DIR = PROJECT_ROOT / "data" / "audio"

# How the wearable powers itself off for `system.shutdown`.
#
# `systemctl poweroff` rather than `shutdown -h now` because it is one
# fixed argv with no time argument to get wrong, which makes the sudoers
# rule it needs exact:
#
#   cknrf ALL=(root) NOPASSWD: /usr/bin/systemctl poweroff
#
# A tuple, not a shell string — nothing here goes near a shell, so there
# is no quoting to get wrong and no way for a transcript to influence it.
SHUTDOWN_COMMAND = ("sudo", "-n", "/usr/bin/systemctl", "poweroff")

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

# Speaker volume, as a percentage of the audio sink's range.
#
# The 20% floor is a hard clamp, not a suggestion. Speech is this device's
# only channel to its user, so a volume low enough to be inaudible on a
# busy road is a trap with no way out: the user cannot hear the response
# that would let them turn it back up, and there is no screen to fall back
# on. `VolumeState` refuses to go below it whatever is asked.
#
# The buzzer is unaffected by all of this — it is driven straight from GPIO
# and never passes through the audio sink, so obstacle and emergency alerts
# keep their loudness no matter what the user sets here.
#
# 10% steps: small enough to tune, large enough that "louder" is audibly
# louder on the first try rather than needing four presses.
VOLUME_DEFAULT_PERCENT = 80
VOLUME_MIN_PERCENT = 20
VOLUME_MAX_PERCENT = 100
VOLUME_STEP_PERCENT = 10
VOLUME_STATE_PATH = PROJECT_ROOT / "var" / "volume"


# Physical buttons (KY-004 style breakouts with on-board 10kΩ pull-down)
PTT_BUTTON_GPIO = 23         # physical pin 16 — push-to-talk (click to start, click to stop)
EMERGENCY_BUTTON_GPIO = 25   # physical pin 18 — single click fires emergency.trigger
REPEAT_BUTTON_GPIO = 24      # physical pin 22 — single click repeats last instruction

# Active buzzer — direct GPIO drive (see feedback/gpio_buzzer.py for the
# current-draw caveat if the Pi shows undervoltage warnings).
BUZZER_GPIO = 18             # physical pin 12

# How long the wearable waits for the user to approve a destination before
# it starts routing. A press within this window means yes; silence means no.
#
# Silence-as-decline is what lets a three-button prototype ask a yes/no
# question at all — a "no" button would have needed a fourth. It also fails
# in the safe direction: a user who did not hear the question, or who is not
# holding the device, is never sent walking somewhere they did not choose.
#
# 4 s is long enough to hear the question end and react without hurrying,
# short enough that a decline doesn't feel like the device has hung. The
# whole confirmation costs ~3-4 s in the common case, since a yes lands as
# soon as the user presses.
DESTINATION_CONFIRM_TIMEOUT_S = 4.0

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

# Posture route — the second way to confirm a fall. See the module
# docstring in safety/fall_detector.py for the full derivation.
#
# The thresholds above describe a straight-down collapse and detect
# nothing else: measured on the assembled vest, forward/backward/sideways
# falls spent as little as 10 ms below the freefall threshold against the
# 100 ms requirement, because a chest-mounted sensor in a trip swings
# about the feet rather than dropping. Sensitivity on recorded trips was
# 0%.
#
# No single signal fixes that — every one of them overlaps between falls
# and ordinary activity:
#
#   signal              falls        activities    separates?
#   lowest |a|          0.12-0.38    0.07-0.95     no
#   peak |a|            3.58-6.76    1.05-7.01     no
#   peak rotation °/s    315-427       13-359      no
#   posture change °       9-95         1-102      no
#
# The pair does. Sitting down hard is violent but upright (7.01 g, 13°);
# lying down and bending are horizontal but gentle (2.15 g at 102°,
# 1.60 g at 75°). Requiring BOTH a hard impact and a large orientation
# change rejects all of them and caught every recorded fall: 3/3 falls,
# 7/7 activities.
#
# Chosen mid-gap rather than at either edge. Impact: real falls bottomed
# out at 3.65 g, the hardest horizontal activity reached 2.15 g — any
# value in 2.2-3.6 works. Tilt: falls ran 73-95°, the activities that
# clear the impact gate sat at 13° and 25° — any value in 26-72° works.
#
# Caveat for the write-up: 4 falls and 7 activities, all onto a mattress.
# Enough to choose a design, not enough to publish a sensitivity figure.
FALL_POSTURE_IMPACT_THRESHOLD_G = 3.0
FALL_POSTURE_TILT_THRESHOLD_DEG = 50.0

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
# With the flag True and a provider wired, the API key is what actually
# decides whether this path is live: an unset `INDEPENSENSE_CLOUD_API_KEY`
# makes `_try_open_cloud_answerer` return None and the wearable answers
# unknown utterances exactly as it did before. The key belongs in the
# environment, never in this file — config.py is committed.
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

# How long a cloud exchange stays usable as follow-up context.
#
# The fallback keeps the last question and answer and replays them, so
# "what is the tallest mountain" can be followed by "what about the
# second". A pronoun resolves against what was *just* said, though — a
# question asked ten minutes later is a new conversation, and silently
# attaching it to an old one is how "what about the second" gets answered
# about the wrong subject. Two minutes is comfortably longer than anyone
# pauses mid-thought and far shorter than they would leave a topic and
# come back expecting to be understood.
#
# Also cleared outright on a language switch: the stored turn is in the
# language just left.
CLOUD_CONTEXT_TTL_S = 120.0

OLLAMA_URL = "http://127.0.0.1:11434"
NLU_MODEL = "qwen3:1.7b"
NLU_PROMPT_PATH = PROJECT_ROOT / "prompts" / "nlu_system.md"
NLU_TIMEOUT_S = 30.0
NLU_WARMUP_TIMEOUT_S = 90.0

# Semantic fast path in front of the LLM — see intents/embeddings.py for
# the full rationale and prompts/nlu_examples.md for the example bank.
#
# Model choice — `intfloat/multilingual-e5-small` over XLM-RoBERTa:
# XLM-R is a masked-LM encoder, not a sentence encoder. Its pooled output
# is poor under cosine similarity without sentence-level fine-tuning (the
# same result that produced SBERT from BERT), and at 278M parameters it
# would cost more RAM than e5 to do the job worse. e5-small is 118M
# parameters, 384-dimensional, sentence-trained, and covers XLM-R's 100
# languages including Tagalog. It runs on the torch + transformers install
# that YOLO and MMS-TTS already require, so it adds no second inference
# runtime — the same argument that selected MMS-TTS for Tagalog speech.
#
# Both thresholds must be cleared before the fast path answers, and they
# measure different things. `SCORE` is cosine similarity to the nearest
# labelled example: "does this resemble anything we know?". `MARGIN` is
# the gap to the nearest example of a *different* decision: "is the
# choice contested?".
#
# Values chosen from `embedding_probe --sweep` over the 98 held-out
# prompts (measured on a Mac; re-run on the Pi for latency, the accuracy
# is hardware-independent). At score 0.86 / margin 0.02:
#
#     group          cases  answerable  coverage  capture  precision
#     english           47          32     59.6%    87.5%     100.0%
#     tagalog           26          19     61.5%    84.2%     100.0%
#     adversarial       25           8     28.0%    87.5%     100.0%
#     OVERALL           98          59     52.0%    86.4%     100.0%
#
# Read `capture` rather than `coverage`: 39 of the 98 prompts have an
# open text slot, so escalating them is correct and coverage can never
# approach 100%. The fast path takes 86% of the work it is allowed to
# take, at no cost in precision, and Tagalog tracks English closely
# enough that the priority language is not being carried by the other.
#
# The sweep produced one finding worth keeping: **the score threshold is
# nearly inert for this model.** e5's cosine values are compressed into a
# narrow high band, so every point between 0.80 and 0.88 gives an
# identical result and the margin does all the filtering. 0.86 sits in
# the middle of that flat region rather than at its edge, so a shift in
# phrasing distribution does not fall off a cliff. Margin 0.01 would buy
# 2 points of coverage and cost the first wrong answer — not a trade
# worth making on a device where a wrong action is worse than no action.
NLU_EMBEDDING_MODEL = "intfloat/multilingual-e5-small"
NLU_EMBEDDING_BANK_PATH = PROJECT_ROOT / "prompts" / "nlu_examples.md"
NLU_EMBEDDING_SCORE_THRESHOLD = 0.86
NLU_EMBEDDING_MARGIN_THRESHOLD = 0.02

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
# Places the user has named and saved ("home", "my sister's house").
#
# Under `var/` with the other runtime state, and deliberately NOT in the
# repo: this is one person's list of where they live and who they visit.
# It is also the only destination source that works with no data
# connection, which is much of why the feature exists — see
# `routing/places.py`.
SAVED_PLACES_PATH = PROJECT_ROOT / "var" / "places.json"

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