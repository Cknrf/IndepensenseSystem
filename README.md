# IndepenSense

**An IoT-based wearable navigation and safety assistance system with computer vision and guardian monitoring.**

IndepenSense supports individuals with visual or mobility impairments by providing real-time navigation assistance, obstacle detection, and safety monitoring. It combines sensor fusion, on-device computer vision, and a remote guardian dashboard to enhance user independence in both indoor and outdoor environments.

## Table of Contents

- [Project Overview](#project-overview)
- [System Objectives](#system-objectives)
- [System Architecture](#system-architecture)
- [Core Features](#core-features)
- [Repository Scope & Collaborator Roles](#repository-scope--collaborator-roles)
- [Hardware Components](#hardware-components)
- [Wiring & Pin Alignment](#wiring--pin-alignment)
- [Software Stack](#software-stack)
- [External Services](#external-services)
- [Codebase Overview](#codebase-overview)
- [Getting Started](#getting-started)
- [Manual Verification Tests](#manual-verification-tests)
- [First-Boot Verification Checklist](#first-boot-verification-checklist)
- [Troubleshooting](#troubleshooting)
- [Voice Commands](#voice-commands)
- [System Workflow](#system-workflow)
- [Documentation Index](#documentation-index)

## Project Overview

The core objective of this thesis is to develop a lightweight, real-time assistive wearable system capable of:

- Detecting environmental obstacles
- Assisting navigation decisions
- Monitoring user safety conditions
- Sending alerts to guardians in real time

## System Objectives

- Provide real-time obstacle detection using sensors and computer vision
- Assist navigation through directional feedback (audio + vibration)
- Detect falls or abnormal motion using an IMU
- Enable emergency SOS alert triggering
- Allow guardians to monitor user status remotely
- Ensure low-latency edge processing on embedded hardware (Raspberry Pi 5)

## System Architecture

IndepenSense follows a modular edge + cloud hybrid architecture.

1. **Wearable Edge Device (Raspberry Pi 5)** — real-time processing, sensor integration, feedback generation.
2. **Computer Vision Module** — real-time object detection, OCR, and scene description via the Raspberry Pi Camera.
3. **Sensor Fusion Layer** — combines ultrasonic distance, motion (IMU), magnetometer, GPS, and camera-based detection.
4. **Navigation & Decision Module** — obstacle-proximity risk, turn-by-turn guidance, off-route deviation warnings.
5. **Guardian Monitoring System** — remote dashboard for user status, emergency alerts, and activity logs (separate repository).
6. **Backend & Communication Layer** — API server for data exchange, real-time messaging, event storage.

## Core Features

**Navigation Assistance**
- Real-time obstacle detection
- Multi-sensor distance estimation
- Audio + vibration directional feedback
- Turn-by-turn cueing with off-route warnings
- Destination confirmation before routing — the chosen place is read back with its distance, and nothing starts until the user presses to confirm
- Candidate re-ranking, so "the nearest Jollibee" is decided locally by distance rather than by the geocoder's own relevance score
- Saved places — name the spot you are standing in, then "take me home" later, with no geocoder and no network
- Progress on demand: how much further there is to walk, measured along the route rather than as the crow flies

**Compass-assisted navigation** *(built, inert until the magnetometer is calibrated on the assembled unit — see `COMPASS_CALIBRATED` in `config.py`)*
- Turn-to-face guidance: before the first step, a motor pulses on the side to turn toward, faster as the user comes round
- Departure heading passed to the router, so a route does not open by telling the user to turn around
- Turn verification — the compass notices a missed turn in about five seconds, where position-based off-route detection takes fifteen to thirty

**Safety Monitoring**
- Fall detection using the MPU6050 IMU
- Abnormal-movement detection
- Emergency SOS trigger via physical button
- The wearer is told what the device knows: a detected fall and both battery tiers are spoken aloud, not only sent to guardians
- Critical announcements interrupt whatever is being said, including mid-synthesis

**Computer Vision Awareness**
- On-demand object detection (YOLOv8)
- OCR / text reading (Tesseract, English + Tagalog)
- Scene description via voice command

**Voice Interaction**
- Push-to-talk speech input (Whisper STT)
- LLM-based intent classification (Qwen 3 1.7B via Ollama), with a Mistral cloud fallback for questions no intent covers
- Natural-language responses (Piper TTS)
- Speech can be interrupted — the repeat button stops the wearable mid-sentence, which matters when OCR is reading a menu
- Spoken help, so a user who cannot read a manual can ask what the device does
- Speaker volume by voice, with a floor the user cannot go below

**Guardian System**
- Live monitoring dashboard
- Emergency notifications
- User activity and safety logs
- Battery + cellular signal telemetry

## Repository Scope & Collaborator Roles

This repository holds the **on-device runtime** — everything that runs on the Raspberry Pi 5 inside the wearable. The other pieces of the thesis live elsewhere.

| Role | Responsibility | Where the work lives |
|---|---|---|
| Software developer | Runtime code, sensor drivers, voice pipeline, intent handling, telemetry | **This repo** |
| Fabricator | Physical assembly, wiring, harness routing, enclosure | Physical build; wiring reference in [`docs/hardware.md`](docs/hardware.md) |
| Backend / dashboard developer | Guardian dashboard, alert routing, database | Separate repository |

**Note for the fabricator:** you don't need to write Python. The manual tests in this repo (see [Manual Verification Tests](#manual-verification-tests)) let you confirm each component is wired correctly without waiting for the software developer to write custom code.

## Hardware Components

- Raspberry Pi 5 (main processing unit)
- Waveshare UPS HAT (E) — battery + power management
- 2× DYP-A22 Ultrasonic Sensors — top and bottom obstacle sensing
- MPU6050 IMU — accelerometer + gyroscope (fall detection)
- QMC5883P magnetometer — 3-axis compass for heading (standalone; sold as a QMC5883L but answers at 0x2C, and the MPU9250 bought before it was a relabelled MPU6500 with no magnetometer at all)
- Raspberry Pi Camera Module — computer vision input
- SIM7600 module — cellular data + GPS
- 3× Vibration motors — front / left / right directional feedback
- Buzzer — audio alerts
- USB microphone + speaker — voice interaction
- Push-to-talk + SOS buttons + Repeat/stop button (replays the last response, or interrupts speech in progress)

## Wiring & Pin Alignment

**All wiring, pin numbers, I²C addresses, UART assignments, and per-component power notes live in [`docs/hardware.md`](docs/hardware.md).**

That file contains:

- Full 40-pin GPIO header diagram
- Per-component wiring for every sensor and actuator
- Which pins are 3.3 V-only (critical — 5 V will damage some sensors) — particularly the QMC5883P
- Current wiring status ("working / not yet connected") per component

**Please update `hardware.md` every time a wire changes.** It is the single source of truth for physical connections; if it disagrees with reality, reality is wrong and the doc gets fixed.

## Software Stack

- **Language:** Python 3.13
- **OS:** Raspberry Pi OS (Trixie / Debian 13) on device, macOS for development
- **Computer Vision:** Ultralytics YOLOv8 (medium, Open Images V7 weights), Tesseract OCR
- **Voice:** faster-whisper (STT), Piper (TTS), Ollama + Qwen 3 1.7B (NLU)
- **Hardware Interface:** GPIO (gpiozero), I²C, UART
- **Database:** handled by the backend repository

## External Services

Both services run **locally on the Raspberry Pi** — the wearable is offline-capable and does not depend on cloud maps.

- **GraphHopper** — offline pedestrian routing (port 8989). See [`docs/graphhopper.md`](docs/graphhopper.md).
- **Photon** — offline geocoding, place-name ↔ coordinates (port 2322). See [`docs/photon.md`](docs/photon.md).

## Codebase Overview

The runtime lives under `src/indepensense/`. Each folder is one domain, each ships its own driver, mock, and tests.

| Module | Purpose |
|---|---|
| `sensors/` | Sensor drivers: DYP-A22 ultrasonic, MPU6050 IMU, QMC5883P magnetometer, GPS via SIM7600 |
| `vision/` | Camera capture, YOLOv8 object detection, Tesseract OCR |
| `voice/` | Push-to-talk flow, Whisper STT, Piper TTS, speaker volume |
| `intents/` | LLM-based intent classification + per-intent handlers (navigation, vision, device status, emergency, language switching, help, saved places, volume), bilingual response catalogue, cloud LLM fallback |
| `navigation/` | GPS-to-route monitoring, off-route detection, turn-by-turn cueing, remaining-distance, compass turn verification, and turn-to-face orientation logic |
| `routing/` | GraphHopper + Photon HTTP clients, local candidate ranking, geo helpers (distance and bearing), and the user's own saved places |
| `feedback/` | Buzzer, vibration motors, PTT + SOS buttons |
| `safety/` | Fall detection via accelerometer thresholds |
| `power/` | Waveshare UPS HAT driver, low-battery alerts |
| `telemetry/` | Buffered heartbeat + alert sender to the backend, guardian contact cache, SMS fan-out on alerts |
| `messaging/` | Outbound SMS via ModemManager (`mmcli`) — the fallback notification path when data is unavailable |
| `tools/` | Utility scripts (e.g., live system-performance monitor) |
| `app.py` | Main synchronous polling loop that wires everything together |
| `app_mock.py` | Development-only subclass of `App` with every device mocked — runs the full runtime on a Mac. Never deployed |
| `config.py` | All tunable parameters (thresholds, pins, addresses, model paths) |
| `language.py` | Active language as runtime state, persisted across reboots |
| `net.py` | Shared connectivity probe |

### Runtime state

Written under `var/`, which is gitignored. None of it is configuration —
it is what the device remembers between runs, and deleting any of it is
safe (the wearable falls back to the `config.py` default).

| File | Holds | Delete it and… |
|---|---|---|
| `var/language` | active language | starts in `DEFAULT_LANGUAGE` again |
| `var/volume` | speaker volume | starts at `VOLUME_DEFAULT_PERCENT` |
| `var/places.json` | the user's saved places | "take me home" stops working until re-saved |
| `var/guardians.json` | cached guardian numbers | emergency SMS has no recipients until the next successful fetch |
| `var/low_battery_alerted` | 15% alert latch | guardians may get one duplicate low-battery alert |
| `var/critical_battery_alerted` | 5% warning latch | the wearer may hear one duplicate critical warning |

The two latches exist because the service restarts on failure: without
them, a Pi crash-looping on a dying battery would re-alert every boot,
texting every guardian each time.

**Design conventions** worth knowing before touching code (see also `CLAUDE.md`):

- **One synchronous main loop plus a fixed, named set of background threads** — voice, announcer, heartbeat, telemetry retry, GPS cache, and short-lived per-event haptic workers. The rule is *never block the main loop*, not *never use threads*; adding a new long-lived one is a structural change. No asyncio.
- **Hardware abstraction** — every sensor exposes a `Protocol` interface + a real driver + a mock, so the full system runs on macOS for development.
- **Drivers own protocol knowledge** — parsing, checksums, unit conversion live in the driver, never in callers or tests.
- **Tests nested per module** — `<module>/tests/unit/` for pytest (no hardware), `<module>/tests/manual/` for scripts that need real hardware.

## Getting Started

### On any machine (development)

```bash
pip install -e .
pip install -r requirements.txt
```

The system runs on macOS using the mock drivers — no hardware required for development.

### Additionally on the Raspberry Pi

```bash
pip install -r requirements-pi.txt
```

External services (Ollama, GraphHopper, Photon) are installed and configured via systemd — see the linked docs.

### Running

- **All unit tests:** `pytest`
- **Full wearable:** `python -m indepensense.app`
- **Live performance monitor** (in a separate SSH session): `python -m indepensense.tools.system_performance --csv`

## Manual Verification Tests

After wiring a component (or after any hardware change), run its test to confirm it works. All tests run from the repo root with `python -m ...`. These are the same commands the software developer uses to debug — no new scripts needed.

### Sensors

| Component | Command | What it does |
|---|---|---|
| DYP-A22 top only | `python -m indepensense.sensors.tests.manual.single_dyp_test` | Prints live distance in cm |
| DYP-A22 top + bottom | `python -m indepensense.sensors.tests.manual.dual_dyp_test` | Prints both distances side by side |
| MPU6050 IMU | `python -m indepensense.sensors.tests.manual.single_mpu6050_test` | Prints accel + gyro readings |
| QMC5883P magnetometer | `python -m indepensense.sensors.tests.manual.single_magnetometer_test` | Prints calibrated field, magnitude, and heading |
| Magnetometer calibration | `python -m indepensense.sensors.tests.manual.magnetometer_calibrate` | 30 s sweep producing hard-iron offsets + soft-iron scales |
| Magnetometer config probe | `python -m indepensense.sensors.tests.manual.magnetometer_range_probe` | Diagnostic: tries five write strategies to find one that makes both QMC5883P control registers stick, and reports which sensitivity is real |
| GPS (SIM7600) | `python -m indepensense.sensors.tests.manual.single_gps_test` | Prints NMEA fixes as they arrive |
| GPS site survey | `python -m indepensense.sensors.tests.manual.gps_survey --label kitchen` | Samples one spot for 2 min, appends to `gps_survey.csv`, reports fix rate, HDOP, positional scatter in metres, and flags a frozen (stale) fix |

### Feedback

| Component | Command |
|---|---|
| Buzzer | `python -m indepensense.feedback.tests.manual.buzzer_test` |
| Vibration motors (front / left / right) | `python -m indepensense.feedback.tests.manual.vibration_test` |
| Push-to-talk / SOS buttons | `python -m indepensense.feedback.tests.manual.button_test` |

### Vision

| Component | Command |
|---|---|
| Camera capture only | `python -m indepensense.vision.tests.manual.capture_test` |
| One-shot YOLO detection | `python -m indepensense.vision.tests.manual.detect_test` |
| Continuous detection (terminal, no GUI) | `python -m indepensense.vision.tests.manual.continuous_detect_test` |
| Live camera + bounding boxes (GUI) | `python -m indepensense.vision.tests.manual.live_detect_test` |
| Record short video clip | `python -m indepensense.vision.tests.manual.record_test` |

### Voice

| Component | Command |
|---|---|
| STT — microphone → text | `python -m indepensense.voice.tests.manual.stt_test` |
| TTS — text → speaker | `python -m indepensense.voice.tests.manual.tts_test` |
| Full echo — mic → text → speech | `python -m indepensense.voice.tests.manual.echo_test` |

### Power

| Component | Command |
|---|---|
| UPS HAT — voltage, current, percent | `python -m indepensense.power.tests.manual.single_ups_test` |
| UPS HAT — fuel-gauge trace to CSV | `python -m indepensense.power.tests.manual.single_ups_test --csv --interval 10` |

### Safety

| Purpose | Command |
|---|---|
| Live fall detection (drop the wearable safely) | `python -m indepensense.safety.tests.manual.live_fall_test` |

### Telemetry

| Purpose | Command |
|---|---|
| Send one alert to the backend | `python -m indepensense.telemetry.tests.manual.send_alert_test` |
| Send one heartbeat to the backend | `python -m indepensense.telemetry.tests.manual.send_heartbeat_test` |

### Messaging (SMS)

| Component | Command |
|---|---|
| Send one real SMS | `python -m indepensense.messaging.tests.manual.send_sms_test --number +639171234567` |
| Preview the emergency SMS wording | `python -m indepensense.messaging.tests.manual.send_sms_test --number +639171234567 --emergency-preview` |

Both send a real message and cost money. Requires ModemManager running and
a SIM whose plan permits SMS — a data-only plan fails at the send step.

### Routing & Intents (require GraphHopper, Photon, and Ollama running)

| Purpose | Command |
|---|---|
| GraphHopper + Photon end-to-end lookup | `python -m indepensense.routing.tests.manual.end_to_end_test` |
| Voice → intent → handler end-to-end | `python -m indepensense.intents.tests.manual.end_to_end_test` — add `--keyboard` when the PTT/SOS buttons aren't wired. A navigation command takes **three** presses: start, stop, then confirm the destination |
| LLM intent-classification probe (66 test prompts, scored per language group) | `python -m indepensense.intents.tests.manual.llm_probe` |
| Cloud LLM probe — real Mistral calls, latency and answer quality | `python -m indepensense.intents.tests.manual.cloud_probe` |

### System Profiling

| Purpose | Command |
|---|---|
| Live CPU / memory / temperature | `python -m indepensense.tools.system_performance` |
| Same, with CSV output for later analysis | `python -m indepensense.tools.system_performance --csv` — writes a timestamped file to `data/performance/` |

## First-Boot Verification Checklist

After the wearable is assembled, run these steps **in order**. If a step fails, stop and check `docs/hardware.md` for that component's wiring before continuing.

1. **Power on the Pi** and confirm it's on the network:
   ```bash
   ip a
   ```
2. **Confirm I²C devices:**
   ```bash
   i2cdetect -y 1
   ```
   Expected: `0x2D` (UPS HAT), `0x68` (MPU6050), `0x2C` (QMC5883P magnetometer). If the compass shows at `0x0D` instead it is a QMC5883L, a different chip — see [`docs/hardware.md`](docs/hardware.md).
3. **Confirm serial devices:**
   ```bash
   ls /dev/ttyUSB* /dev/ttyAMA*
   ```
   Expected: entries for the SIM7600 (GPS + cellular) and the ultrasonic UARTs.
4. **Confirm services are running:**
   ```bash
   systemctl status ollama graphhopper photon indepensense
   ```
5. **Run each manual test above**, one component at a time. Do not skip failing components.
6. **Calibrate the compass.** It is wired and read but nothing acts on it:
   `COMPASS_CALIBRATED` in `config.py` is `False`, so turn-to-face
   guidance, the departure heading and turn verification all stay off.
   Working heading is not optional for those three — an uncalibrated
   magnetometer does not fail visibly, it reports a plausible bearing that
   may be mirrored, and that sends the user the wrong way.
   ```bash
   # a. Fix MAG_FORWARD_AXIS / MAG_LEFT_AXIS for the real mount — the
   #    defaults assume a board lying flat, and the vest mount is upright.
   #    Procedure in docs/hardware.md.
   python -m indepensense.sensors.tests.manual.single_magnetometer_test

   # b. Sweep, then paste the printed offsets and scales into config.py
   python -m indepensense.sensors.tests.manual.magnetometer_calibrate

   # c. Check all four cardinals against a phone compass, then set
   #    COMPASS_CALIBRATED = True
   ```
7. **Set the speaker volume** and confirm it sticks across a restart. The
   floor is 20% and the buzzer is driven straight from GPIO, so it is not
   affected by this:
   ```bash
   wpctl set-volume @DEFAULT_AUDIO_SINK@ 80%
   ```
8. **Only after every component passes**, run the full wearable:
   ```bash
   python -m indepensense.app
   ```

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| `i2cdetect` doesn't show a device | SDA/SCL swapped, wrong I²C bus (we use bus 1, not 0), or the device isn't powered |
| DYP-A22 returns 0 or fluctuates wildly | Wired to 5 V instead of **3.3 V** (may already be damaged); wrong UART; loose ground |
| MPU6050 returns all zeros mid-test | Loose wire (very common after drop tests) — reseat SDA, SCL, VCC, GND |
| Camera not detected | Ribbon cable inserted backwards, or camera not enabled in `raspi-config` |
| No audio output | USB audio device isn't the default sink — check `aplay -l` and adjust the ALSA default |
| Whisper / Piper / Ollama slow to start | First boot loads models into RAM (~30–60 s). Subsequent starts are fast. |
| PTT button raises `PinInvalidState` | Do not set `active_state=True` when `pull_up=False` — the pull sets the polarity already |
| YOLO very slow | Expected during `continuous_detect_test`. In production, YOLO only runs on-demand per voice command |
| Voice commands don't classify correctly | Check `ollama list` — the Qwen model may not be loaded; the warmup service takes ~1–2 min on cold boot |
| Turn-to-face never runs; no heading anywhere | `COMPASS_CALIBRATED` is `False` in `config.py`. Expected until the calibration step above is done — `latest_heading()` shows the raw reading meanwhile |
| Heading looks plausible but guidance sends the user the wrong way | A sign is inverted in `MAG_FORWARD_AXIS` / `MAG_LEFT_AXIS`, which mirrors the compass. Re-check against a phone at all four cardinals, not just one |
| "Louder" changes nothing | `wpctl` missing, or PipeWire is routing through a different node than `@DEFAULT_AUDIO_SINK@` (common over Bluetooth). `wpctl status` shows the real default |
| Navigation never starts, always says "cancelled" | The destination confirmation timed out. It wants a **PTT press** within `DESTINATION_CONFIRM_TIMEOUT_S` after the place is read back |
| The device talks over itself | Should be impossible — every main-loop utterance goes through the announcer, which is single-threaded. If it happens, something is calling `play()` directly |
| Saved places vanish after a reboot | `var/places.json` unwritable, or the process runs as a user without write access to `var/` |

## Voice Commands

Every intent the wearable recognises, with a phrasing that reaches it. The
classifier is an LLM, not a keyword matcher, so these are examples rather
than magic words — the full rules and the Tagalog equivalents live in
[`prompts/nlu_system.md`](prompts/nlu_system.md).

| Intent | Say something like | Notes |
|---|---|---|
| `navigation.start` | "Take me to Jollibee" · "Take me home" | Reads the destination back and waits for a confirming press |
| `navigation.stop` | "Cancel navigation" | |
| `navigation.repeat` | "Say that again" | Or press the repeat button |
| `navigation.location` | "Where am I" | Answers with a place name |
| `navigation.progress` | "How much further" | Answers with distance along the route |
| `place.save` | "Save this place as home" | Stores where you are standing, under your own label |
| `place.delete` | "Forget the place saved as home" | |
| `vision.describe` | "What's around me" | Camera + YOLO |
| `vision.read` | "Read this" | Camera + OCR. Press repeat to stop it mid-read |
| `device.status` | "How much battery do I have" | Also GPS lock and cellular signal |
| `system.time` | "What time is it" | |
| `system.language` | "Switch to English" · "Lumipat sa Ingles" | Confirms in the language switched *to* |
| `system.volume` | "Louder" · "Set the volume to 60" | Floor of 20%; the buzzer is unaffected |
| `system.help` | "What can you do" | |
| `emergency.trigger` | "Help" · "Tulong" | Also the emergency button. A bare cry for help is always an emergency, never a request for the help intent |
| *(anything else)* | — | Forwarded to the cloud LLM when online, otherwise "I didn't catch that" |

**Buttons.** Push-to-talk (left) starts and stops recording, and doubles as
the confirm press. Emergency fires an alert immediately. Repeat replays the
last response — or, while the wearable is talking, stops it.

## System Workflow

- Sensors continuously collect environmental data at the polling-loop rate.
- The camera captures on demand; YOLO / OCR only run when triggered by a voice intent.
- The sensor-fusion layer combines ultrasonic, IMU, magnetometer, GPS, and vision outputs.
- The navigation module decides risk levels and directional guidance.
- The feedback system triggers vibration or audio output.
- Telemetry is buffered and sent to the backend for guardian monitoring.
- Alerts (fall, SOS, low battery) fire immediately on detection — to the
  guardian over both HTTP and SMS, and to the wearer as speech.
- **The main loop never blocks.** It detects and decides; speech goes to the
  announcer thread and haptic patterns to short-lived worker threads, so
  fall and obstacle detection keep running while the device is talking.

## Documentation Index

| Doc | Contents |
|---|---|
| [`docs/hardware.md`](docs/hardware.md) | Full wiring, pin, I²C-address, and enclosure-layout reference |
| [`docs/voice.md`](docs/voice.md) | Voice-pipeline architecture (STT → intent → TTS) |
| [`docs/graphhopper.md`](docs/graphhopper.md) | GraphHopper install, map data, systemd service |
| [`docs/photon.md`](docs/photon.md) | Photon install, index data, systemd service |
| [`docs/sim7600.md`](docs/sim7600.md) | SIM7600 module setup — cellular data and GPS |
| [`docs/deferred.md`](docs/deferred.md) | Work consciously parked, and why — the source for Future Work |
| [`CLAUDE.md`](CLAUDE.md) | Working agreement and architecture decisions in force |
