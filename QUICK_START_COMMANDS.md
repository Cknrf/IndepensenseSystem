# IndepenSense — Quick Start Commands for Non-Technical Users

**Run all commands from the project root directory** (the folder containing this file)

## Getting Started

### Install dependencies (do this once)
```bash
pip install -r requirements-pi.txt
```

### Run the main application
```bash
python -m indepensense.app
```

---

## Testing Individual Components

### Sensors & Inputs

**Test ultrasonic distance sensors:**
```bash
python -m indepensense.sensors.tests.manual.dual_dyp_test
```
Shows distance readings from both sensors (top and bottom).

**Test motion sensor (fall detection):**
```bash
python -m indepensense.sensors.tests.manual.single_mpu6050_test
```
Shows acceleration and rotation data.

**Test compass:**
```bash
python -m indepensense.sensors.tests.manual.single_magnetometer_test
```
Shows heading direction and magnetic field readings.

**Test GPS:**
```bash
python -m indepensense.sensors.tests.manual.single_gps_test
```
Shows GPS location fixes. **Stop the app first** (it uses the same serial port).

### Feedback & Buttons

**Test buzzer:**
```bash
python -m indepensense.feedback.tests.manual.buzzer_test
```

**Test vibration motors:**
```bash
python -m indepensense.feedback.tests.manual.vibration_test
```

**Test buttons (PTT, SOS, Repeat):**
```bash
python -m indepensense.feedback.tests.manual.button_test
```

### Vision & Camera

**Test camera:**
```bash
python -m indepensense.vision.tests.manual.capture_test
```

**Test object recognition (YOLO):**
```bash
python -m indepensense.vision.tests.manual.live_detect_test
```
Shows camera feed with objects highlighted in a window.

**Test text recognition (OCR):**
```bash
python -m indepensense.vision.tests.manual.ocr_test
```

### Voice & Speech

**Test microphone (speech-to-text):**
```bash
python -m indepensense.voice.tests.manual.stt_test
```
Speak into the microphone, it shows what it heard.

**Test speaker (text-to-speech):**
```bash
python -m indepensense.voice.tests.manual.tts_test
```

**Test full voice loop (mic → text → speech):**
```bash
python -m indepensense.voice.tests.manual.echo_test
```
Speak, and it repeats what you said.

**Test all audio cues:**
```bash
python -m indepensense.voice.tests.manual.cue_test
```

### Power & Battery

**Check battery status:**
```bash
python -m indepensense.power.tests.manual.single_ups_test
```

**Log battery over time to a file:**
```bash
python -m indepensense.power.tests.manual.single_ups_test --csv --interval 10
```

### Safety & Fall Detection

**Test fall detection live:**
```bash
python -m indepensense.safety.tests.manual.live_fall_test
```

**Test walking vs. still detection:**
```bash
python -m indepensense.safety.tests.manual.live_walking_test
```

### Voice Commands & Intent Recognition

**Test full voice command pipeline:**
```bash
python -m indepensense.intents.tests.manual.end_to_end_test
```

**Test navigation routing:**
```bash
python -m indepensense.routing.tests.manual.end_to_end_test
```

---

## Testing & Verification

### Unit Tests (verify code logic on Mac/laptop)
```bash
.venv/bin/python -m pytest src/indepensense/
```

### Run tests for one module
```bash
.venv/bin/python -m pytest src/indepensense/sensors/tests/unit/
```

---

## Common Troubleshooting

**"Module not found" error:**
- Make sure you're in the project root directory
- Make sure you ran `pip install -r requirements-pi.txt`

**"Port already in use" or "Permission denied":**
- Stop the main app first: `Ctrl+C`
- Wait a few seconds before running another test

**Sensor not responding:**
- Check the wiring in `docs/hardware.md`
- Make sure power is connected to the Raspberry Pi

**No audio or microphone not working:**
- Check that the USB headset is connected
- Run `python -m indepensense.voice.tests.manual.cue_test` to test the speaker

---

## Navigation Commands

**Test why a destination wasn't found:**
```bash
python -m indepensense.routing.tests.manual.geocode_probe "Jollibee" --from 13.937387,121.118698 --nearest
```

**Test if a misheard voice command would still work:**
```bash
python -m indepensense.routing.tests.manual.transcript_probe
```

---

## Important Notes

- Always start with **component tests** (sensors, voice, etc.) before running the full app
- If something breaks, check `docs/hardware.md` for wiring
- Most tests print useful debug info — read the output carefully
- Tests marked **(requires X running)** need GraphHopper, Photon, or Ollama started first

---

## For More Info

- **Hardware wiring:** `docs/hardware.md`
- **Architecture notes:** `CLAUDE.md`
- **Full test list:** `README.md` (search for "Manual Verification Tests")
