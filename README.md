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

**Safety Monitoring**
- Fall detection using the MPU6050 IMU
- Abnormal-movement detection
- Emergency SOS trigger via physical button

**Computer Vision Awareness**
- On-demand object detection (YOLOv8)
- OCR / text reading (Tesseract, English + Tagalog)
- Scene description via voice command

**Voice Interaction**
- Push-to-talk speech input (Whisper STT)
- LLM-based intent classification (Qwen 3 1.7B via Ollama), with a cloud LLM fallback for questions no intent covers
- Natural-language responses (Piper TTS)

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
- QMC5883L magnetometer — 3-axis compass for heading (standalone; the MPU9250 bought for this turned out to be a relabelled MPU6500 with no magnetometer)
- Raspberry Pi Camera Module — computer vision input
- SIM7600 module — cellular data + GPS
- 3× Vibration motors — front / left / right directional feedback
- Buzzer — audio alerts
- USB microphone + speaker — voice interaction
- Push-to-talk + SOS buttons + Repeat (Last instruction) button

## Wiring & Pin Alignment

**All wiring, pin numbers, I²C addresses, UART assignments, and per-component power notes live in [`docs/hardware.md`](docs/hardware.md).**

That file contains:

- Full 40-pin GPIO header diagram
- Per-component wiring for every sensor and actuator
- Which pins are 3.3 V-only (critical — 5 V will damage some sensors) — particularly the QMC5883L
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
| `sensors/` | Sensor drivers: DYP-A22 ultrasonic, MPU6050 IMU, QMC5883L magnetometer, GPS via SIM7600 |
| `vision/` | Camera capture, YOLOv8 object detection, Tesseract OCR |
| `voice/` | Push-to-talk flow, Whisper STT, Piper TTS |
| `intents/` | LLM-based intent classification + per-intent handlers (navigation, vision, device status, emergency, language switching), bilingual response catalogue, cloud LLM fallback |
| `navigation/` | GPS-to-route monitoring, off-route detection, turn-by-turn cueing |
| `routing/` | GraphHopper + Photon HTTP clients (routing and geocoding) |
| `feedback/` | Buzzer, vibration motors, PTT + SOS buttons |
| `safety/` | Fall detection via accelerometer thresholds |
| `power/` | Waveshare UPS HAT driver, low-battery alerts |
| `telemetry/` | Buffered heartbeat + alert sender to the backend, guardian contact cache, SMS fan-out on alerts |
| `messaging/` | Outbound SMS via ModemManager (`mmcli`) — the fallback notification path when data is unavailable |
| `tools/` | Utility scripts (e.g., live system-performance monitor) |
| `app.py` | Main synchronous polling loop that wires everything together |
| `app_mock.py` | Development-only subclass of `App` with every device mocked — runs the full runtime on a Mac. Never deployed |
| `config.py` | All tunable parameters (thresholds, pins, addresses, model paths) |

**Design conventions** worth knowing before touching code (see also `CLAUDE.md`):

- **Single synchronous polling loop** — no threads / asyncio unless a measured latency problem appears.
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
- **Live performance monitor** (in a separate SSH session): `python -m indepensense.tools.system_performance --csv perf.csv`

## Manual Verification Tests

After wiring a component (or after any hardware change), run its test to confirm it works. All tests run from the repo root with `python -m ...`. These are the same commands the software developer uses to debug — no new scripts needed.

### Sensors

| Component | Command | What it does |
|---|---|---|
| DYP-A22 top only | `python -m indepensense.sensors.tests.manual.single_dyp_test` | Prints live distance in cm |
| DYP-A22 top + bottom | `python -m indepensense.sensors.tests.manual.dual_dyp_test` | Prints both distances side by side |
| MPU6050 IMU | `python -m indepensense.sensors.tests.manual.single_mpu6050_test` | Prints accel + gyro readings |
| QMC5883L magnetometer | `python -m indepensense.sensors.tests.manual.single_magnetometer_test` | Prints calibrated field, magnitude, and heading |
| Magnetometer calibration | `python -m indepensense.sensors.tests.manual.magnetometer_calibrate` | 30 s sweep producing hard-iron offsets + soft-iron scales |
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
| Voice → intent → handler end-to-end | `python -m indepensense.intents.tests.manual.end_to_end_test` |
| LLM intent-classification probe (49 test prompts) | `python -m indepensense.intents.tests.manual.llm_probe` |

### System Profiling

| Purpose | Command |
|---|---|
| Live CPU / memory / temperature | `python -m indepensense.tools.system_performance` |
| Same, with CSV output for later analysis | `python -m indepensense.tools.system_performance --csv perf.csv` |

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
   Expected: `0x2D` (UPS HAT), `0x68` (MPU6050), `0x0D` (QMC5883L magnetometer).
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
6. **Only after every component passes**, run the full wearable:
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

## System Workflow

- Sensors continuously collect environmental data at the polling-loop rate.
- The camera captures on demand; YOLO / OCR only run when triggered by a voice intent.
- The sensor-fusion layer combines ultrasonic, IMU, magnetometer, GPS, and vision outputs.
- The navigation module decides risk levels and directional guidance.
- The feedback system triggers vibration or audio output.
- Telemetry is buffered and sent to the backend for guardian monitoring.
- Alerts (fall, SOS, low battery) are triggered immediately on detection.

## Documentation Index

| Doc | Contents |
|---|---|
| [`docs/hardware.md`](docs/hardware.md) | Full wiring, pin, and I²C-address reference |
| [`docs/voice.md`](docs/voice.md) | Voice-pipeline architecture (STT → intent → TTS) |
| [`docs/graphhopper.md`](docs/graphhopper.md) | GraphHopper install, map data, systemd service |
| [`docs/photon.md`](docs/photon.md) | Photon install, index data, systemd service |
| [`docs/sim7600.md`](docs/sim7600.md) | SIM7600 module setup — cellular data and GPS |
| [`CLAUDE.md`](CLAUDE.md) | Working agreement and architecture decisions in force |
