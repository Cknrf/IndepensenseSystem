# IndepenSense - Comprehensive Test Execution Form

**Date:** ________________  
**Tester:** ________________  
**Environment:** RPi 5, Full Hardware Stack  
**Services Running:** GraphHopper ☐ Photon ☐ Ollama ☐ Cellular ☐ GPS ☐  
**Network Available:** ☐ Yes ☐ No  
**Models Loaded:** ☐ Whisper ☐ Ollama ☐ YOLO ☐ Tesseract

---

## 1. STARTUP & INITIALIZATION

### 1.1 Cold Boot Sequence

| TRIAL | ACTION | EXPECTED | ACTUAL | STATUS | NOTES |
|-------|--------|----------|--------|--------|-------|
| BOOT-001 | Power on device | Boot announcement plays BEFORE models load | | ☐ PASS ☐ FAIL | Time to first sound: ___ s |
| BOOT-002 | Wait ~10 seconds | Journal shows `Safety features up in N s`; fall detection, obstacle haptics and SOS button work | | ☐ PASS ☐ FAIL |  |
| BOOT-003 | Wait full boot (about two minutes, as the device announces) | "IndepenSense is now fully ready…" greeting, then battery level; voice commands ready | | ☐ PASS ☐ FAIL | Journal `IndepenSense fully ready in N s`: ___ s |
| BOOT-004 | Press PTT at 10s (during loading) | Busy cue plays, command rejected | | ☐ PASS ☐ FAIL |  |
| BOOT-005 | Device fully booted | No errors in journal, all systems initialized | | ☐ PASS ☐ FAIL | Check `sudo journalctl -u indepensense -n 50` |

**Summary:** ___ / 5 passed

### 1.2 Warm Reboot

| TRIAL | ACTION | EXPECTED | ACTUAL | STATUS | NOTES |
|-------|--------|----------|--------|--------|-------|
| BOOT-006 | Reboot after normal operation | Device boots, all state preserved (language, volume, saved places) | | ☐ PASS ☐ FAIL |  |
| BOOT-007 | Check language setting | Language same as before reboot | | ☐ PASS ☐ FAIL | If set to Tagalog, should still be Tagalog |
| BOOT-008 | Check volume setting | Volume persists | | ☐ PASS ☐ FAIL |  |
| BOOT-009 | Check saved places | All saved places still exist | | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 4 passed

---

## 2. MICROPHONE & PTT LATENCY

**Note:** PTT is the right button and works click-to-start, click-to-stop (not hold-to-talk). Recording also stops on its own at 30 s. A PTT press never cuts speech — only the left button does.

### 2.1 Push-to-Talk Response

| TRIAL | ACTION | EXPECTED | ACTUAL | LATENCY | STATUS | NOTES |
|-------|--------|----------|--------|---------|--------|-------|
| PTT-LAT-001 | Press PTT (right button) once | All-motor pulse immediately (0.15 s), then a 0.12 s rising chime; recording starts | | Pulse ≤150 ms, chime ~150-300 ms | ☐ PASS ☐ FAIL |  |
| PTT-LAT-002 | Press PTT while the device is speaking | Speech is NOT cut. During a voice answer: busy cue (two low buzzes). Otherwise the chime plays once speech ends. Only the left button stops speech | | — | ☐ PASS ☐ FAIL |  |
| PTT-LAT-003 | Press PTT a second time | Recording stops: all-motor pulse + falling chime, processing starts (releasing the button does nothing) | | <200 ms | ☐ PASS ☐ FAIL |  |
| PTT-LAT-004 | Rapid PTT presses (5 in 2s) | Press 1 rising chime; press 2 stops recording (falling chime, or "I didn't hear anything. Please say that again." if ≤0.2 s); presses 3-5 busy cue | | ≤150 ms each | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 4 passed

---

## 3. SPEECH-TO-TEXT (STT) - ENGLISH

**Precondition:** the device starts in Tagalog (`DEFAULT_LANGUAGE = "tl"`) and Whisper follows the active language. Say "Switch to English" first. For transcription-only checks, `python -m indepensense.voice.tests.manual.stt_test` transcribes a WAV without executing any command.

**Objective:** Validate Whisper transcription accuracy.

### 3.1 Clear Speech

| TRIAL | PHRASE SPOKEN | EXPECTED TRANSCRIPT | ACTUAL TRANSCRIPT | MATCH? | STATUS | NOTES |
|-------|---------------|-------------------|-------------------|--------|--------|-------|
| STT-EN-001 | "Take me to Jollibee" |  |  | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |
| STT-EN-002 | "Where am I" |  |  | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |
| STT-EN-003 | "Turn right in 50 meters" |  |  | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |
| STT-EN-004 | "What time is it" |  |  | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |
| STT-EN-005 | "How much battery" |  |  | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 5 passed

### 3.2 Accented/Challenging Speech

| TRIAL | PHRASE SPOKEN (CONDITION) | EXPECTED | ACTUAL | MATCH? | STATUS | NOTES |
|-------|---|---|---|---|---|---|
| STT-EN-006 | "Take me to Jollibee" (Filipino accent) | Transcribed correctly or recognizable | | ☐ Yes ☐ Partial ☐ No | ☐ PASS ☐ FAIL |  |
| STT-EN-007 | "Cancel navigation" (quiet voice) | Transcribed | | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |
| STT-EN-008 | "Help" (mumbled) — use `stt_test` on a recording, NOT the live device (live "Help" sends a real guardian alert + SMS) | Recognizable as intent-carrying words | | ☐ Yes ☐ Partial | ☐ PASS ☐ FAIL |  |
| STT-EN-009 | Background noise (traffic ~60dB) + normal speech | Transcribed despite noise | | ☐ Yes ☐ Partial ☐ No | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 4 passed

### 3.3 Edge Cases

| TRIAL | CONDITION | EXPECTED | ACTUAL | STATUS | NOTES |
|-------|-----------|----------|--------|--------|-------|
| STT-EN-010 | Empty input (silence, no speech) | "I didn't hear anything. Please say that again." announced | | ☐ PASS ☐ FAIL |  |
| STT-EN-011 | Very long utterance (30+ seconds) | Recording auto-stops at 30 s (journal: `auto-stopped at 30s cap`); the captured 30 s is transcribed, no overflow | | ☐ PASS ☐ FAIL |  |
| STT-EN-012 | Repeating same phrase 5 times | Each transcription consistent or similar | | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 3 passed

---

## 4. SPEECH-TO-TEXT (STT) - TAGALOG

### 4.1 Clear Tagalog Speech

| TRIAL | PHRASE SPOKEN (TAGALOG) | EXPECTED TRANSCRIPT | ACTUAL TRANSCRIPT | MATCH? | STATUS | NOTES |
|-------|-------------------------|-------------------|-------------------|--------|--------|-------|
| STT-TL-001 | "Dalhin mo ako sa Jollibee" |  |  | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |
| STT-TL-002 | "Nasaan ako" |  |  | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |
| STT-TL-003 | "Lumipat sa English" |  |  | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |
| STT-TL-004 | "Ano ang oras" |  |  | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |
| STT-TL-005 | "I-save ang lugar na ito bilang bahay" |  |  | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 5 passed

### 4.2 Code-Switching (Taglish)

| TRIAL | PHRASE SPOKEN | EXPECTED | ACTUAL | STATUS | NOTES |
|-------|---|---|---|---|---|
| STT-TL-006 | "Take me sa nearest Jollibee" (English + Tagalog) | Transcribed accurately | | ☐ PASS ☐ FAIL |  |
| STT-TL-007 | "Magbigay ako ng volume set to 70 percent" | Handled gracefully | | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 2 passed

---

## 5. INTENT CLASSIFICATION - NLU (ENGLISH)

**Objective:** Test the English intents. **Precondition:** switch to English first (the device starts in Tagalog). Run 5.2 (save home) before NLU-EN-003. `emergency.trigger` sends a REAL guardian alert and SMS.

### 5.1 Navigation Intents

| TRIAL | INTENT | EXAMPLE PHRASE | EXPECTED RESULT | ACTUAL RESULT | CORRECT? | STATUS | NOTES |
|-------|--------|---|---|---|---|---|---|
| NLU-EN-001 | navigation.start | "Take me to McDonald's" | "<place>, <distance> away. Press the right button to confirm, or the left button to cancel." Right press → "Navigating to … Total distance …" | | ☐ Yes ☐ No | ☐ PASS ☐ FAIL | Time to destination confirmation: ___ s |
| NLU-EN-002 | navigation.start (variation) | "Navigate to the nearest Jollibee" | Nearest Jollibee read back with distance; route starts only after right-button press | | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |
| NLU-EN-003 | navigation.start (saved place) | "Take me home" (run after NLU-EN-007 has saved home) | Route starts immediately (no geocoding, no confirmation) | | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |
| NLU-EN-004 | navigation.stop | "Cancel navigation" | Active route cancels, "cancelled" announced | | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |
| NLU-EN-005 | navigation.location | "Where am I" | Current location announced | | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |
| NLU-EN-006 | navigation.progress | "How much further" | Distance to destination announced | | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 6 passed

### 5.2 Place Management Intents

| TRIAL | INTENT | EXAMPLE PHRASE | EXPECTED RESULT | ACTUAL RESULT | CORRECT? | STATUS | NOTES |
|-------|--------|---|---|---|---|---|---|
| NLU-EN-007 | place.save | "Save this place as home" | With a GPS fix: "Saved this place as home." ("Updated home to this place." if it existed) | | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |
| NLU-EN-008 | place.save (variant) | "I'm at work, save it" | Place saved | | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |
| NLU-EN-009 | place.locate | "What is the exact location of my home" | "home is near <street/district/city>, about <distance> away." (needs home saved; coordinates only with no network) | | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |
| NLU-EN-010 | place.locate (public place) | "Where is Jollibee" | Not a saved place, so handed to the cloud: "Let me think about that", then the cloud answer; offline: "I need an internet connection…" | | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |
| NLU-EN-011 | place.list | "What places have I saved" | List of saved places announced | | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |
| NLU-EN-012 | place.delete | "Forget the place saved as home" | "Forgot the place saved as home." (immediate, no confirmation) | | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 6 passed

### 5.3 Vision Intents

| TRIAL | INTENT | EXAMPLE PHRASE | EXPECTED RESULT | ACTUAL RESULT | CORRECT? | STATUS | NOTES |
|-------|--------|---|---|---|---|---|---|
| NLU-EN-013 | vision.describe | "What's around me" | Camera captures, YOLO describes objects, or falls back to ultrasonic | | ☐ Yes ☐ No | ☐ PASS ☐ FAIL | Latency: ___ s |
| NLU-EN-014 | vision.describe (variation) | "Describe the scene" | Objects announced | | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |
| NLU-EN-015 | vision.read | "Read this" | OCR runs, text read aloud | | ☐ Yes ☐ No | ☐ PASS ☐ FAIL | Latency: ___ s |
| NLU-EN-016 | vision.read (interrupt) | "Read this", press repeat while reading | Text reading stops mid-word | | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 4 passed

### 5.4 Device Status Intents

| TRIAL | INTENT | EXAMPLE PHRASE | EXPECTED RESULT | ACTUAL RESULT | CORRECT? | STATUS | NOTES |
|-------|--------|---|---|---|---|---|---|
| NLU-EN-017 | device.status (battery) | "How much battery do I have" | "Battery is at N percent." (or "…and charging.") — one field per question | | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |
| NLU-EN-017a | device.status (gps) | "Is the GPS connected" | "GPS is locked with N satellites. Signal quality is good." (or "GPS has no fix at the moment.") | | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |
| NLU-EN-017b | device.status (signal) | "Check the signal" | "Cellular signal is [strong/medium/weak], at X percent, on [network]" | | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |
| NLU-EN-018 | system.time | "What time is it" | Current time announced | | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |
| NLU-EN-019 | system.help | "What can you do" | Help message spoken | | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 5 passed

### 5.5 Volume & Settings Intents

| TRIAL | INTENT | EXAMPLE PHRASE | EXPECTED RESULT | ACTUAL RESULT | CORRECT? | STATUS | NOTES |
|-------|--------|---|---|---|---|---|---|
| NLU-EN-020 | system.volume | "Louder" | Volume increases, new level announced | | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |
| NLU-EN-021 | system.volume (decrease) | "Quieter" | Volume decreases | | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |
| NLU-EN-022 | system.volume (explicit) | "Set volume to 60 percent" | Volume set to 60%, confirmed | | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |
| NLU-EN-023 | system.language | "Switch to Tagalog" | Language switches, confirmation in Tagalog | | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 4 passed

### 5.6 Emergency & System Intents

| TRIAL | INTENT | EXAMPLE PHRASE | EXPECTED RESULT | ACTUAL RESULT | CORRECT? | STATUS | NOTES |
|-------|--------|---|---|---|---|---|---|
| NLU-EN-024 | emergency.trigger | "Help" — sends a REAL guardian alert + SMS | "Sending your emergency alert.", alert to backend + SMS, then delivery report. No buzzer, no motors (those are SOS button and fall only) | | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |
| NLU-EN-025 | system.shutdown | "Shut down" | Confirmation prompt, waits for PTT press | | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |
| NLU-EN-026 | unknown (cloud LLM) | "How does photosynthesis work" | Escalates to cloud LLM, receives answer | | ☐ Yes ☐ No | ☐ PASS ☐ FAIL | Latency: ___ s |

**Summary:** ___ / 3 passed

---

## 6. INTENT CLASSIFICATION - NLU (TAGALOG)

### 6.1 Core Tagalog Intents

| TRIAL | INTENT | EXAMPLE PHRASE (TAGALOG) | EXPECTED RESULT | ACTUAL RESULT | CORRECT? | STATUS | NOTES |
|-------|--------|---|---|---|---|---|---|
| NLU-TL-001 | navigation.start | "Dalhin mo ako sa Jollibee" | Destination read back in Tagalog ("…, … ang layo. Pindutin ang kanang pindutan…"); route starts after right press. Place name is not translated | | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |
| NLU-TL-002 | navigation.stop | "Kanselahin ang navigation" | Route cancels | | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |
| NLU-TL-003 | navigation.location | "Nasaan ako" | Current location announced in Tagalog | | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |
| NLU-TL-004 | device.status | "Magkano ang baterya" | Battery announced in Tagalog | | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |
| NLU-TL-005 | place.save | "I-save ang lugar na ito bilang bahay" | Place saved with Tagalog name | | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |
| NLU-TL-006 | system.language | "Lumipat sa English" | Switches to English, confirmation in English | | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |
| NLU-TL-007 | system.volume | "Mas malakas" (louder) | Volume increases | | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |
| NLU-TL-008 | emergency.trigger | "Tulong" — sends a REAL guardian alert + SMS | "Ipinapadala ko na ang emergency alert mo.", alert sent. No buzzer, no motors | | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 8 passed

---

## 7. BUTTON FUNCTIONALITY

### 7.1 Push-to-Talk (PTT) Button

| TRIAL | ACTION | EXPECTED BEHAVIOR | ACTUAL BEHAVIOR | STATUS | NOTES |
|-------|--------|---|---|---|---|
| BTN-PTT-001 | Press PTT | All-motor pulse (0.15 s), then rising chime | | ☐ PASS ☐ FAIL | Actual latency: ___ ms |
| BTN-PTT-002 | Press PTT once and speak (no need to hold) | Microphone records until the next press or 30 s | | ☐ PASS ☐ FAIL |  |
| BTN-PTT-003 | Press PTT again | Processing starts; "working blip" after 1.5 s, then every 1.2 s | | ☐ PASS ☐ FAIL |  |
| BTN-PTT-004 | Press PTT during speech | Speech is NOT cut; busy cue during a voice answer, otherwise chime after speech ends | | ☐ PASS ☐ FAIL |  |
| BTN-PTT-005 | Rapid PTT (5 presses in 2s) | Press 1 starts, press 2 stops, later presses busy cue while processing | | ☐ PASS ☐ FAIL |  |
| BTN-PTT-006 | Press once and keep talking 30+ seconds | Recording auto-stops at 30 s, processing proceeds, no overflow error | | ☐ PASS ☐ FAIL |  |
| BTN-PTT-007 | PTT recording when a fall is detected | Buzzer + all motors, "I detected a fall. I am alerting your guardian.", alert sent. The PTT recording is NOT cancelled | | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 7 passed

### 7.2 Emergency (SOS) Button

| TRIAL | ACTION | EXPECTED BEHAVIOR | ACTUAL BEHAVIOR | STATUS | NOTES |
|-------|--------|---|---|---|---|
| BTN-SOS-001 | Press SOS (front) button | All-motor pulse, then buzzer within ~200 ms: 3 bursts of 3 beeps (0.1 s on / 0.06 s gap), 0.5 s between bursts | | ☐ PASS ☐ FAIL | Time to sound: ___ ms |
| BTN-SOS-002 | SOS pressed | All three motors pulse once together (0.2 s) | | ☐ PASS ☐ FAIL |  |
| BTN-SOS-003 | SOS pressed | "Sending your emergency alert.", then "Emergency alert sent to your guardian." (or a delivery-failure message) | | ☐ PASS ☐ FAIL |  |
| BTN-SOS-004 | SOS pressed (online) | Backend receives alert via HTTP POST | | ☐ PASS ☐ FAIL | Check backend logs |
| BTN-SOS-005 | SOS pressed (online) | SMS sent to guardian contact | | ☐ PASS ☐ FAIL | Check phone |
| BTN-SOS-006 | SOS pressed, double-press within 10s | Buzzer sounds both times, but only ONE alert logged | | ☐ PASS ☐ FAIL | Backend should show 1 event |
| BTN-SOS-007 | SOS pressed during PTT | PTT cancels, SOS alert fires immediately | | ☐ PASS ☐ FAIL |  |
| BTN-SOS-008 | SOS pressed (offline, no network) | Buzzer fires locally, alert queued for retry | | ☐ PASS ☐ FAIL | Check logs for retry logic |
| BTN-SOS-009 | SOS pressed during navigation | Alert fires; its announcement cuts any navigation cue; route stays active until "Cancel navigation" | | ☐ PASS ☐ FAIL |  |
| BTN-SOS-010 | Hold SOS for 10+ seconds | Alert fires once, holding doesn't re-trigger | | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 10 passed

### 7.3 Repeat / Stop Button

| TRIAL | ACTION | EXPECTED BEHAVIOR | ACTUAL BEHAVIOR | STATUS | NOTES |
|-------|--------|---|---|---|---|
| BTN-REP-001 | Press after device speaks | Last response replays | | ☐ PASS ☐ FAIL |  |
| BTN-REP-002 | Press during device speech | Speech cuts, "stop cue" tone plays | | ☐ PASS ☐ FAIL |  |
| BTN-REP-003 | Press before any response | All-motor ack pulse, then "There is nothing to repeat yet." | | ☐ PASS ☐ FAIL |  |
| BTN-REP-004 | Press at "confirm destination" prompt | Counts as "no" / reject | | ☐ PASS ☐ FAIL |  |
| BTN-REP-005 | Rapid repeat presses | Presses alternate: replay, then stop cue + silence, then replay… | | ☐ PASS ☐ FAIL |  |
| BTN-REP-006 | Press during OCR reading | Text reading stops | | ☐ PASS ☐ FAIL |  |
| BTN-REP-007 | Press during obstacle warning | Obstacle pattern unaffected (haptic only, nothing to stop); ack pulse after it finishes, last response replayed | | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 7 passed

---

## 8. SENSOR CALIBRATION & ACCURACY

### 8.1 Ultrasonic Sensors (Distance Measurement)

**Setup:** Place obstacles at known distances using tape measure.

#### Top Sensor (cane-mounted, high — head-level obstacles)

| TRIAL | DISTANCE | EXPECTED | ACTUAL | DEVIATION | STATUS | NOTES |
|-------|----------|----------|--------|-----------|--------|-------|
| SENSOR-US-TOP-001 | 20 cm | 20±5 cm | | | ☐ PASS ☐ FAIL |  |
| SENSOR-US-TOP-002 | 30 cm | 30±5 cm | | | ☐ PASS ☐ FAIL |  |
| SENSOR-US-TOP-003 | 50 cm | 50±5 cm | | | ☐ PASS ☐ FAIL |  |
| SENSOR-US-TOP-004 | 75 cm | 75±5 cm | | | ☐ PASS ☐ FAIL |  |
| SENSOR-US-TOP-005 | 100 cm | 100±5 cm | | | ☐ PASS ☐ FAIL |  |
| SENSOR-US-TOP-006 | 150 cm | 150±5 cm | | | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 6 passed

#### Bottom Sensor (cane-mounted, low — foot-level obstacles)

| TRIAL | DISTANCE | EXPECTED | ACTUAL | DEVIATION | STATUS | NOTES |
|-------|----------|----------|--------|-----------|--------|-------|
| SENSOR-US-BOT-001 | 15 cm | 15±5 cm | | | ☐ PASS ☐ FAIL |  |
| SENSOR-US-BOT-002 | 25 cm | 25±5 cm | | | ☐ PASS ☐ FAIL |  |
| SENSOR-US-BOT-003 | 40 cm | 40±5 cm | | | ☐ PASS ☐ FAIL |  |
| SENSOR-US-BOT-004 | 60 cm | 60±5 cm | | | ☐ PASS ☐ FAIL |  |
| SENSOR-US-BOT-005 | 80 cm | 80±5 cm (the sensor may report the ground at ~80 cm; aim it at the target, not the floor) | | | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 5 passed

### 8.2 IMU (Accelerometer & Gyroscope)

| TRIAL | ACTION | EXPECTED | ACTUAL | STATUS | NOTES |
|-------|--------|----------|--------|--------|-------|
| SENSOR-IMU-001 | Device stationary | \|a\| ≈ 1.00 g as printed by `single_mpu6050_test` (any orientation); note which axis carries ~1 g | | ☐ PASS ☐ FAIL | X: ___ Y: ___ Z: ___ |
| SENSOR-IMU-002 | Device tilted 45° | Accel redistributes across axes | | ☐ PASS ☐ FAIL |  |
| SENSOR-IMU-003 | Shake device | Gyro readings detect rotation | | ☐ PASS ☐ FAIL |  |
| SENSOR-IMU-004 | No values read as zero/infinity | All readings finite and changing | | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 4 passed

### 8.3 Magnetometer (Compass)

| TRIAL | ACTION | EXPECTED | ACTUAL | STATUS | NOTES |
|-------|--------|----------|--------|--------|-------|
| SENSOR-MAG-001 | Device stationary | Heading stable (drift <±5°) | | ☐ PASS ☐ FAIL | Heading: ___ ° |
| SENSOR-MAG-002 | Rotate 90° left | Heading decreases by ~90° | | ☐ PASS ☐ FAIL |  |
| SENSOR-MAG-003 | Rotate 90° right | Heading increases by ~90° | | ☐ PASS ☐ FAIL |  |
| SENSOR-MAG-004 | Full 360° rotation | Heading returns to start ±10° | | ☐ PASS ☐ FAIL |  |
| SENSOR-MAG-005 | Compare with phone compass, vest held upright as worn | Headings match ±5° (calibrated; no tilt compensation, so tilt degrades it) | | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 5 passed

---

## 9. OBSTACLE DETECTION & HAPTIC FEEDBACK

### 9.1 Obstacle Detection Tiers

**Setup:** Wearer **stands still** for the whole section — while walking, the proximity rhythm (9.2) runs on top of these cues. Both sensors face forward, so obstacles only ever use the front motor or all three together; the left and right motors are for navigation. Start each trial with the obstacle beyond 2.5 m, then bring it in. Alerts fire when the obstacle gets *closer*: moving it away is silent, and a tier only re-arms after the obstacle backs off 15 cm past that tier's line.

| TRIAL | SENSOR & DISTANCE | EXPECTED TIER | EXPECTED FEEDBACK | ACTUAL FEEDBACK | STATUS | NOTES |
|-------|---|---|---|---|---|---|
| OBS-TIER-001 | TOP, bring to 150 cm | Far (<200 cm, TOP only) | One short front tick (0.1 s) | | ☐ PASS ☐ FAIL |  |
| OBS-TIER-002 | TOP, continue to 75 cm | Warning (<100 cm) | One long front pulse (0.5 s) | | ☐ PASS ☐ FAIL |  |
| OBS-TIER-003 | TOP, continue to 30 cm | Danger (<50 cm) | All three motors together (0.4 s) | | ☐ PASS ☐ FAIL |  |
| OBS-TIER-004 | TOP, hold at 30 cm for 20 s | Danger | One repeat at ~15 s, otherwise silent | | ☐ PASS ☐ FAIL |  |
| OBS-TIER-005 | TOP, move obstacle back beyond 215 cm | Clear | No feedback (receding is silent) | | ☐ PASS ☐ FAIL |  |
| OBS-TIER-006 | BOTTOM, bring to 75 cm | Warning (<100 cm, no far tier) | One front pulse (0.25 s) — noticeably shorter than OBS-TIER-002 | | ☐ PASS ☐ FAIL |  |
| OBS-TIER-007 | BOTTOM, continue to 30 cm | Danger (<50 cm) | All three motors together (0.4 s) | | ☐ PASS ☐ FAIL |  |
| OBS-TIER-008 | Any of the above | — | Buzzer never sounds (reserved for emergencies) | | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 8 passed

### 9.2 Hysteresis & Re-Alert Behavior

| TRIAL | ACTION | EXPECTED | ACTUAL | STATUS | NOTES |
|-------|--------|----------|--------|--------|-------|
| OBS-HYSTER-001 | Obstacle at 65 cm, hold 10s | Single fire on entry, no repeat | Fires once @ entry, silent for 10s | ☐ PASS ☐ FAIL |  |
| OBS-HYSTER-002 | Obstacle exits (move to 160cm) | Vibration stops, no repeat | Silent | ☐ PASS ☐ FAIL |  |
| OBS-HYSTER-003 | Re-enter danger zone | Alert fires again (hysteresis reset) | All motors fire @ re-entry | ☐ PASS ☐ FAIL |  |
| OBS-HYSTER-004 | Stand still facing a wall at 80 cm for 5 s, then walk towards it | Re-alert on setting off, then proximity rhythm | 0.5 s front pulse as you set off, then short front pulses ~1/s speeding to ~2/s by 50 cm | ☐ PASS ☐ FAIL |  |
| OBS-HYSTER-005 | Obstacle static, no motion (standing) | Danger tier repeats every 15s, no rhythm | Alert at 0s, 15s pattern | ☐ PASS ☐ FAIL |  |
| OBS-RHYTHM-001 | Walk slowly towards a wall from 120 cm (TOP sensor) | Rhythm starts below 100 cm, front motor only | Pulses get faster as you approach | ☐ PASS ☐ FAIL |  |
| OBS-RHYTHM-002 | Keep walking past 50 cm | Clear step up in rate, switches to all three motors | ~3/s at 50 cm rising to ~5/s at 30 cm | ☐ PASS ☐ FAIL |  |
| OBS-RHYTHM-003 | Closer than 30 cm | Near-continuous all-motor pulsing | ~8/s | ☐ PASS ☐ FAIL |  |
| OBS-RHYTHM-004 | Stop walking with the wall at 40 cm | Rhythm stops within ~2 s | Silent while standing | ☐ PASS ☐ FAIL |  |
| OBS-RHYTHM-005 | Walk with only the BOTTOM sensor seeing something at 60-90 cm (e.g. the ground) | No rhythm — BOTTOM joins only below 50 cm | Silent | ☐ PASS ☐ FAIL |  |
| OBS-RHYTHM-006 | Navigation turn cue while rhythm is running | Turn cue plays intact, rhythm resumes after | Two-pulse turn cue clearly felt | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 11 passed

### 9.3 Dual-Sensor Coordination

**Note:** the two sensors are independent — nothing merges them into a single "worst case" cue. Each sensor fires its own alert; a shared lock plays them one after the other. Stand still.

| TRIAL | TOP SENSOR | BOTTOM SENSOR | EXPECTED | ACTUAL | STATUS | NOTES |
|-------|-----------|---------------|----------|--------|--------|-------|
| OBS-DUAL-001 | 40 cm (danger) | 35 cm (danger) | Each sensor fires its own danger alert: all three motors 0.4 s, felt twice in a row. No buzzer | | ☐ PASS ☐ FAIL |  |
| OBS-DUAL-002 | 80 cm (warning) | 60 cm (warning) | Two front-motor pulses one after the other: long (0.5 s, TOP) and short (0.25 s, BOTTOM). Left/right motors silent | | ☐ PASS ☐ FAIL |  |
| OBS-DUAL-003 | 120 cm (far) | 40 cm (danger) | No merging: TOP far = 0.1 s front tick, BOTTOM danger = all three motors 0.4 s; both play, order by which crosses first | | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 3 passed

---

## 10. FALL DETECTION & EMERGENCY RESPONSE

### 10.1 Live Fall Detection

| TRIAL | ACTION | EXPECTED | ACTUAL | LATENCY | STATUS | NOTES |
|-------|--------|----------|--------|---------|--------|-------|
| FALL-001 | Drop device from 1m on foam mat, let it lie still | Buzzer: 3 bursts of 3 short beeps (a soft mat may keep impact under 2 g and not trigger) | | ≈2–3 s (includes 2 s stillness confirmation) | ☐ PASS ☐ FAIL | Time from impact: ___ ms |
| FALL-002 | Drop device | All three motors pulse together (0.2 s), with the buzzer | | ≈2–3 s | ☐ PASS ☐ FAIL |  |
| FALL-003 | Drop device | "I detected a fall. I am alerting your guardian." (interrupts any speech) | | ≈2–3 s | ☐ PASS ☐ FAIL |  |
| FALL-004 | Drop device (online) | Alert sent to backend via HTTP | | ≈2–4 s from impact | ☐ PASS ☐ FAIL | Check backend |
| FALL-005 | Drop device (online) | SMS sent to guardian | | <5000 ms | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 5 passed

### 10.2 False Positive Prevention

| TRIAL | ACTION | EXPECTED | ACTUAL | STATUS | NOTES |
|-------|--------|----------|--------|--------|-------|
| FALL-FP-001 | Jump in place (normal activity) | No alert | No buzzer/motors | ☐ PASS ☐ FAIL |  |
| FALL-FP-002 | Rapid arm swinging | No alert | | ☐ PASS ☐ FAIL |  |
| FALL-FP-003 | Stair descent (8-10 steps) | No alert (no buzzer, motors or speech) | | ☐ PASS ☐ FAIL |  |
| FALL-FP-004 | Sit down normally | No alert | | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 4 passed

---

## 11. HAPTIC FEEDBACK (MOTORS & BUZZER)

### 11.1 Motor Patterns

| TRIAL | TRIGGER | EXPECTED PATTERN | ACTUAL PATTERN | STATUS | NOTES |
|-------|---------|---|---|---|---|
| HF-MOTOR-001 | Obstacle ahead (danger), standing still | All three motors pulse together (0.4 s) | | ☐ PASS ☐ FAIL |  |
| HF-MOTOR-002 | Fall detected | All three motors pulse together | | ☐ PASS ☐ FAIL |  |
| HF-MOTOR-003 | Navigation: turn left within ~20 m | Left motor, 2 pulses of 0.2 s (0.1 s gap) — obstacles never use the side motors | | ☐ PASS ☐ FAIL |  |
| HF-MOTOR-004 | Navigation: missed turn | Turn-side motor, 3 pulses of 0.15 s | | ☐ PASS ☐ FAIL |  |
| HF-MOTOR-005 | TOP sensor, obstacle at 100–200 cm, standing | One short front tick (0.1 s) | | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 5 passed

### 11.2 Buzzer

| TRIAL | TRIGGER | EXPECTED | ACTUAL | STATUS | NOTES |
|-------|---------|----------|--------|--------|-------|
| HF-BUZ-001 | SOS button pressed | Buzzer sounds loud/distinctive | | ☐ PASS ☐ FAIL |  |
| HF-BUZ-002 | Fall detected | Buzzer fires with same alert as SOS | | ☐ PASS ☐ FAIL |  |
| HF-BUZ-003 | Critical battery (≤20%, discharging) | Buzzer SILENT; "Battery critically low at N percent. The device will shut down soon." (interrupts speech) | | ☐ PASS ☐ FAIL |  |
| HF-BUZ-004 | Obstacle warning | Buzzer is SILENT (by design) | | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 4 passed

---

## 12. AUDIO OUTPUT & TEXT-TO-SPEECH (TTS)

### 12.1 English TTS (Piper)

| TRIAL | TEXT | EXPECTED | ACTUAL | INTELLIGIBILITY | STATUS | NOTES |
|-------|------|----------|--------|---|---|---|
| TTS-EN-001 | "Turn right in 50 meters" | Natural voice, clear | | ☐ 5/5 ☐ 4/5 ☐ 3/5 | ☐ PASS ☐ FAIL |  |
| TTS-EN-002 | "Battery at 45 percent" | Number spoken naturally ("forty-five") | | ☐ 5/5 ☐ 4/5 | ☐ PASS ☐ FAIL |  |
| TTS-EN-003 | Long response (10+ sentences) | No dropouts, complete playback | | ☐ 5/5 ☐ 4/5 | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 3 passed

### 12.2 Tagalog TTS (MMS)

| TRIAL | TEXT (TAGALOG) | EXPECTED | ACTUAL | INTELLIGIBILITY | STATUS | NOTES |
|-------|---|---|---|---|---|---|
| TTS-TL-001 | "Tagalog na ang gagamitin ko ngayon." | Understandable (lower quality than English) | | ☐ 5/5 ☐ 4/5 ☐ 3/5 | ☐ PASS ☐ FAIL |  |
| TTS-TL-002 | In Tagalog mode say "set volume to 70" | Reply speaks the level as Tagalog number words, no dropped or garbled number | | ☐ 5/5 ☐ 4/5 | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 2 passed

### 12.3 Audio Playback & Cues

| TRIAL | CUE | EXPECTED | ACTUAL | STATUS | NOTES |
|-------|-----|----------|--------|--------|-------|
| TTS-CUE-001 | PTT chime | Rising tone, distinctive | | ☐ PASS ☐ FAIL |  |
| TTS-CUE-002 | Stop cue (left button during speech) | Two short falling tones (660 Hz then 440 Hz), distinct from the PTT chimes | | ☐ PASS ☐ FAIL |  |
| TTS-CUE-003 | Busy cue | Different tone (device not ready) | | ☐ PASS ☐ FAIL |  |
| TTS-CUE-004 | Working blip | Soft pulse while processing | | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 4 passed

---

## 13. VOLUME CONTROL

| TRIAL | ACTION | EXPECTED | ACTUAL | STATUS | NOTES |
|-------|--------|----------|--------|--------|-------|
| VOL-001 | Say "Louder" | Volume increases, new level announced | | ☐ PASS ☐ FAIL | Level before: ___ % after: ___ % |
| VOL-002 | Say "Quieter" | Volume decreases | | ☐ PASS ☐ FAIL |  |
| VOL-003 | Say "Set volume to 70" | Volume set to 70%, confirmed | | ☐ PASS ☐ FAIL |  |
| VOL-004 | Repeat "Quieter" to floor (20%) | Volume stops at 20%, cannot go lower | | ☐ PASS ☐ FAIL |  |
| VOL-005 | Reboot after setting volume | Volume persists | | ☐ PASS ☐ FAIL |  |
| VOL-006 | Buzzer at minimum volume (needs an SOS press — sends a REAL alert) | Buzzer still loud (unaffected by speaker volume) | | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 6 passed

---

## 14. NAVIGATION & ROUTING

### 14.1 Destination Selection & Confirmation

| TRIAL | ACTION | EXPECTED | ACTUAL | STATUS | NOTES |
|-------|--------|----------|--------|--------|-------|
| NAV-DEST-001 | Say "Take me to Jollibee" | Geocodes destination, reads back name + distance | | ☐ PASS ☐ FAIL | Time to confirmation prompt: ___ s |
| NAV-DEST-002 | Device waits for confirmation | Press the right (PTT) button within 4 s (DESTINATION_CONFIRM_TIMEOUT_S) | | ☐ PASS ☐ FAIL | Timeout: ___ s |
| NAV-DEST-003 | Press right button to confirm | "Navigating to [place]. Total distance [X]. In [Y] meters, [first turn]"; then turn-to-face motor pulses (14.4) | | ☐ PASS ☐ FAIL |  |
| NAV-DEST-004 | Press left (repeat) button | Cancels; "Cancelled. Please say where you want to go." | | ☐ PASS ☐ FAIL |  |
| NAV-DEST-005 | Do NOT press anything | After 4 s cancels; "Cancelled. Please say where you want to go." | | ☐ PASS ☐ FAIL |  |
| NAV-DEST-006 | Say "Take me home" (saved) | Route starts immediately (no geocoding, no confirmation) | | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 6 passed

### 14.2 Turn-by-Turn Guidance

**Setup:** Walk a planned route (~500-1000m) and observe turn announcements. Run in English: turn, off-route and arrival speech is English-only, so the Tagalog voice garbles it (`docs/deferred.md`).

| TRIAL | ACTION | EXPECTED | ACTUAL | STATUS | NOTES |
|-------|--------|----------|--------|--------|-------|
| NAV-TURN-001 | Approach turn 1 | "In [X] meters, [turn instruction]" announced once within ~100 m; turn-side motor pulses twice within ~20 m (announcement skipped if a voice command is active) | | ☐ PASS ☐ FAIL | Distance before turn: ___ m |
| NAV-TURN-002 | Complete turn 1 | No cue at the turn itself; the next instruction is announced within ~100 m of it | | ☐ PASS ☐ FAIL |  |
| NAV-TURN-003 | Reach destination | "You have arrived at [destination]." within 5 m, plus all-motor 0.4 s pulse | | ☐ PASS ☐ FAIL | Distance from true destination: ___ m |
| NAV-TURN-004 | Say "How much further" mid-route | Distance to destination announced | | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 4 passed

### 14.3 Off-Route Detection

| TRIAL | ACTION | EXPECTED | ACTUAL | TIME | STATUS | NOTES |
|-------|--------|----------|--------|------|--------|-------|
| NAV-OFF-001 | Miss a turn, walk straight | ~5 s after the corner: "It looks like you missed the turn…"; after >30 m off-route for 15 s: "You are off the planned route…" + all-motor pulse | | 5 s / 15-30 s | ☐ PASS ☐ FAIL |  |
| NAV-OFF-002 | Step more than 30 m sideways off the route | Off-route alert after 15 s (backtracking along the route does NOT trigger it) | | 15-30 s | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 2 passed

### 14.4 Compass-Based Navigation (COMPASS_CALIBRATED = True on this build)

| TRIAL | ACTION | EXPECTED | ACTUAL | STATUS | NOTES |
|-------|--------|----------|--------|--------|-------|
| NAV-COMP-001 | Start route | Turn-to-face guidance: motor pulses on turn side | | ☐ PASS ☐ FAIL |  |
| NAV-COMP-002 | Align with destination heading | Within 15°: all-motor pulse + "Walk straight ahead." (pulses every 0.8/0.4/0.2 s when >90°/>30°/<30° off; 20 s timeout: "Start walking, and I will guide you from there.") | | ☐ PASS ☐ FAIL |  |
| NAV-COMP-003 | Miss a left/right turn | ~5 s after the corner: "It looks like you missed the turn. The instruction was: …" + 3 pulses on turn-side motor | | ☐ PASS ☐ FAIL | Time to detection: ___ s |

**Summary:** ___ / 3 passed

---

## 15. COMPUTER VISION

### 15.1 Object Detection (YOLO)

| TRIAL | SCENE | OBJECTS PRESENT | EXPECTED RESULT | ACTUAL RESULT | DETECTED? | STATUS | NOTES |
|-------|-------|---|---|---|---|---|---|
| YOLO-001 | Indoor hallway | Person + door | Announces both objects | | ☐ Yes ☐ Partial ☐ No | ☐ PASS ☐ FAIL |  |
| YOLO-002 | Outdoor street | Car + person + building | All three detected | | ☐ Yes ☐ Partial ☐ No | ☐ PASS ☐ FAIL |  |
| YOLO-003 | Dim lighting | Chair + table | Objects named ("I see …"), or if none recognised and something is within 100 cm: "I can't identify what's in front of you, but something is about [N] centimetres away." | | ☐ Yes ☐ Fallback ☐ No | ☐ PASS ☐ FAIL |  |
| YOLO-004 | Empty scene (nothing) | (none) | "I don't see anything I recognize right now." or the ultrasonic fallback | | ☐ Correct | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 4 passed

### 15.2 Optical Character Recognition (OCR)

| TRIAL | TEXT SAMPLE | LANGUAGE | EXPECTED | ACTUAL | ACCURACY | STATUS | NOTES |
|-------|---|---|---|---|---|---|---|
| OCR-001 | "Emergency Exit" (large print, clear) | English | Perfect/near-perfect read | | ≥95% | ☐ PASS ☐ FAIL |  |
| OCR-002 | Menu text (small, standard print) | English | Most words readable | | ≥80% | ☐ PASS ☐ FAIL |  |
| OCR-003 | Tagalog printed text | Tagalog | Readable (TTS may sound robotic) | | ≥80% | ☐ PASS ☐ FAIL |  |
| OCR-004 | Handwritten text | English | Poor recognition expected | | <50% | ☐ PASS ☐ FAIL | Acceptable: graceful degradation |
| OCR-005 | Text at distance (2+ meters) | English | "I don't see any readable text." (or partial garbled text read aloud) | | 0% | ☐ PASS ☐ FAIL | Never silent |

**Summary:** ___ / 5 passed

---

## 16. BATTERY & POWER MANAGEMENT

### 16.1 Battery State Reporting

| TRIAL | ACTION | EXPECTED | ACTUAL | STATUS | NOTES |
|-------|--------|----------|--------|--------|-------|
| BAT-001 | Say "How much battery" | Battery % announced | | ☐ PASS ☐ FAIL | Reported: ___ % |
| BAT-002 | Check reported % vs. UPS HAT | Percentage accurate within ±10% | | ☐ PASS ☐ FAIL |  |
| BAT-003 | Device fully charged | Reports ~100% (or "…and charging" on the charger) | | ☐ PASS ☐ FAIL | Reported: ___ % |
| BAT-004 | HAT raw gauge at ~78% | Reports ~50% (device rescales raw 57-100% to 0-100%) | | ☐ PASS ☐ FAIL | Reported: ___ % |

**Summary:** ___ / 4 passed

### 16.2 Low-Battery Alerts

| TRIAL | ACTION | EXPECTED | ACTUAL | STATUS | NOTES |
|-------|--------|----------|--------|--------|-------|
| BAT-LOW-001 | Drain to ~30% (unplugged) | Low-battery alert fires (spoken), checked every 10 s | | ☐ PASS ☐ FAIL | Triggered at: ___ % |
| BAT-LOW-002 | Alert fires | "Battery is low, N percent remaining. Please charge the device soon." | | ☐ PASS ☐ FAIL |  |
| BAT-LOW-003 | Alert sent to backend | HTTP POST received | | ☐ PASS ☐ FAIL | Check backend logs |
| BAT-LOW-004 | Alert sent via SMS | Guardian receives SMS | | ☐ PASS ☐ FAIL | Check phone |
| BAT-LOW-005 | Reboot after alert | Alert does NOT repeat (latch working) | | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 5 passed

### 16.3 Critical Battery Alert

| TRIAL | ACTION | EXPECTED | ACTUAL | STATUS | NOTES |
|-------|--------|----------|--------|--------|-------|
| BAT-CRIT-001 | Drain to ~20% (or any cell <3.15 V) | "Battery critically low at N percent. The device will shut down soon." interrupts any speech | | ☐ PASS ☐ FAIL | Triggered at: ___ % |
| BAT-CRIT-002 | Critical alert | No haptic, no buzzer — spoken warning only | | ☐ PASS ☐ FAIL |  |
| BAT-CRIT-003 | Critical alert | No SMS or backend alert (guardians were already told at 30%) | | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 3 passed

---

## 17. GPS & POSITIONING

### 17.1 GPS Acquisition

| TRIAL | CONDITION | EXPECTED | ACTUAL | TIME | STATUS | NOTES |
|-------|-----------|----------|--------|------|--------|-------|
| GPS-001 | Outdoors, clear sky | GPS fix acquired | | <60 s | ☐ PASS ☐ FAIL | Actual time: ___ s |
| GPS-002 | Fix acquired | Satellite count ≥8 | | — | ☐ PASS ☐ FAIL | Sats: ___ |
| GPS-003 | Fix acquired | HDOP <2 (good accuracy) | | — | ☐ PASS ☐ FAIL | HDOP: ___ |
| GPS-004 | Urban canyon (building obstruction) | Fix acquired (may take longer) | | <90 s | ☐ PASS ☐ FAIL | Actual time: ___ s |
| GPS-005 | Indoors, no clear sky | No fix or very weak | | >120 s | ☐ PASS ☐ FAIL | Expected: no fix |

**Summary:** ___ / 5 passed

### 17.2 Location Queries

| TRIAL | ACTION | EXPECTED | ACTUAL | STATUS | NOTES |
|-------|--------|----------|--------|--------|-------|
| GPS-LOC-001 | Say "Where am I" (with GPS fix) | Current location announced (geocoded) | | ☐ PASS ☐ FAIL |  |
| GPS-LOC-002 | Say "Where am I" (no GPS) | "No GPS fix" or last known position | | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 2 passed

---

## 18. CELLULAR CONNECTIVITY & TELEMETRY

### 18.1 Network Status

| TRIAL | ACTION | EXPECTED | ACTUAL | STATUS | NOTES |
|-------|--------|----------|--------|--------|-------|
| NET-001 | Say "Check the signal" (online) | "Cellular signal is [strong/medium/weak], at X percent, on [2G/3G/4G/5G]" (strong ≥60, medium ≥30) | | ☐ PASS ☐ FAIL | Signal reported: ___ |
| NET-002 | Weak signal area | "Weak" announced | | ☐ PASS ☐ FAIL |  |
| NET-003 | No signal area | "No signal" or graceful handling | | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 3 passed

### 18.2 Alert Delivery (Emergency, Fall, Low-Battery)

| TRIAL | ACTION | EXPECTED | ACTUAL | STATUS | NOTES |
|-------|--------|----------|--------|--------|-------|
| ALERT-001 | Press SOS (online) | Alert reaches backend within 2s | | ☐ PASS ☐ FAIL | Check backend logs |
| ALERT-002 | SOS (online) | SMS sent (modem allows up to 30 s) | | ☐ PASS ☐ FAIL | Check phone, time: ___ s |
| ALERT-003 | Alert (offline) | Backend alert queued, saved across reboot, retried every 10 s; SMS retried for up to 5 min; wearer told which channel failed | | ☐ PASS ☐ FAIL | Check logs |
| ALERT-004 | Offline → online | Backend alert delivered within ~10 s of reconnecting; SMS only if reconnected within 5 min | | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 4 passed

---

## 19. LANGUAGE & LOCALIZATION

### 19.1 Language Switching

| TRIAL | ACTION | EXPECTED | ACTUAL | STATUS | NOTES |
|-------|--------|----------|--------|--------|-------|
| LANG-001 | Switch to English first, then say "Switch to Tagalog" | "Tagalog na ang gagamitin ko ngayon." (device starts in Tagalog by default) | | ☐ PASS ☐ FAIL |  |
| LANG-002 | After switch | All subsequent responses in Tagalog | | ☐ PASS ☐ FAIL |  |
| LANG-003 | Say "Lumipat sa English" | Confirmation in English | | ☐ PASS ☐ FAIL |  |
| LANG-004 | After switch back | Responses in English | | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 4 passed

### 19.2 Language Persistence

| TRIAL | ACTION | EXPECTED | ACTUAL | STATUS | NOTES |
|-------|--------|----------|--------|--------|-------|
| LANG-PERS-001 | Switch to English, reboot | Greeting "IndepenSense is now fully ready. I am speaking English." (English is not the default, so this proves persistence) | | ☐ PASS ☐ FAIL |  |
| LANG-PERS-002 | Responses after reboot | All speech in English | | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 2 passed

---

## 20. SAVED PLACES

| TRIAL | ACTION | EXPECTED | ACTUAL | STATUS | NOTES |
|-------|--------|----------|--------|--------|-------|
| PLACE-001 | Say "Save this place as home" (GPS fix) | "Saved this place as home." ("Updated home to this place." if it existed; no fix: "I can't save this place without a GPS fix yet.") | | ☐ PASS ☐ FAIL |  |
| PLACE-002 | Say "Save this place as work" | "Saved this place as work." | | ☐ PASS ☐ FAIL |  |
| PLACE-003 | Say "What places have I saved" | "You have home and work saved." (up to 6 alphabetically, then "and N more") | | ☐ PASS ☐ FAIL | Listed: _______________ |
| PLACE-004 | Say "Take me home" | Route starts to saved home | | ☐ PASS ☐ FAIL |  |
| PLACE-005 | Say "Forget home" | "Forgot the place saved as home." | | ☐ PASS ☐ FAIL |  |
| PLACE-006 | Reboot after saving | Saved places persist | | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 6 passed

---

## 21. CONCURRENT OPERATIONS (THREAD SAFETY)

### 21.1 Fall Detection During Other Operations

| TRIAL | ACTION | EXPECTED | ACTUAL | STATUS | NOTES |
|-------|--------|----------|--------|--------|-------|
| THREAD-001 | Fall while device speaking | Fall alarm fires immediately (not blocked) | | ☐ PASS ☐ FAIL | Latency: ___ ms |
| THREAD-002 | Fall while PTT active | Buzzer + motor alarm fires; "I detected a fall. I am alerting your guardian." interrupts speech; the PTT cycle is NOT cancelled | | ☐ PASS ☐ FAIL |  |
| THREAD-003 | Fall during navigation | Fall alarm + announcement, cutting any queued turn cue; navigation stays active | | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 3 passed

### 21.2 Obstacle Detection During Voice

| TRIAL | ACTION | EXPECTED | ACTUAL | STATUS | NOTES |
|-------|--------|----------|--------|--------|-------|
| THREAD-004 | Device speaking, obstacle detected | Speech continues, vibration fires | | ☐ PASS ☐ FAIL |  |
| THREAD-005 | Navigation active, obstacle fired | Patterns play one after another without overlap; walking rhythm pulses may be skipped during a turn cue | | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 2 passed

---

## 22. EDGE CASES & STRESS TESTS

### 22.1 Rapid User Input

| TRIAL | ACTION | EXPECTED | ACTUAL | STATUS | NOTES |
|-------|--------|----------|--------|--------|-------|
| EDGE-RAPID-001 | Press PTT 10 times in 5 seconds | 1st starts recording, 2nd stops (too-short clip discarded), later presses busy cue while processing; no crash or stuck state | | ☐ PASS ☐ FAIL |  |
| EDGE-RAPID-002 | Repeat "Louder" 10 times | Volume increases to ceiling, then stops | | ☐ PASS ☐ FAIL |  |
| EDGE-RAPID-003 | Give same voice command 5 times in a row | Each processed independently | | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 3 passed

### 22.2 Long-Duration Tests

| TRIAL | ACTION | EXPECTED | ACTUAL | STATUS | NOTES |
|-------|--------|----------|--------|--------|-------|
| EDGE-LONG-001 | Navigation for 2+ hours | No memory leaks, responsive throughout | | ☐ PASS ☐ FAIL | Memory @ start: ___ MB, @ end: ___ MB |
| EDGE-LONG-002 | Continuous obstacle polling for 30 min | No lag, consistent detection | | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 2 passed

### 22.3 Network Loss/Recovery

| TRIAL | ACTION | EXPECTED | ACTUAL | STATUS | NOTES |
|-------|--------|----------|--------|--------|-------|
| EDGE-NET-001 | Alert triggered, network down | Alert queued, device responsive | | ☐ PASS ☐ FAIL | No hang/timeout |
| EDGE-NET-002 | Network recovers after 5 min | Backend alert delivered within ~10 s of recovery; guardian SMS not retried past 300 s | | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 2 passed

---

## 23. FIRST-BOOT HARDWARE VERIFICATION

**Objective:** Verify all hardware is wired and initialized correctly.

| COMPONENT | MANUAL TEST COMMAND | EXPECTED | ACTUAL | STATUS | NOTES |
|-----------|---|---|---|---|---|
| DYP-A22 Top | `python -m indepensense.sensors.tests.manual.dual_dyp_test` | `[TOP]` lines with plausible cm values | | ☐ PASS ☐ FAIL |  |
| DYP-A22 Bottom | `python -m indepensense.sensors.tests.manual.dual_dyp_test` | `[BOTTOM]` lines with plausible cm values; missing lines mean no echo (0 is never printed) | | ☐ PASS ☐ FAIL |  |
| MPU6050 IMU | `python -m indepensense.sensors.tests.manual.single_mpu6050_test` | At rest \|a\| ≈ 1.00 g; gyro ≈ 0 at rest, responds when moved | | ☐ PASS ☐ FAIL |  |
| QMC5883P Compass | `python -m indepensense.sensors.tests.manual.single_magnetometer_test` | Heading sweeps smoothly 0–360° when rotated; field magnitude roughly constant (25-65 μT) | | ☐ PASS ☐ FAIL |  |
| GPS (SIM7600) | `python -m indepensense.sensors.tests.manual.single_gps_test` | After `sudo systemctl stop indepensense`: NMEA fixes arriving | | ☐ PASS ☐ FAIL |  |
| UPS HAT | `python -m indepensense.power.tests.manual.single_ups_test` | Voltage, current, % readable | | ☐ PASS ☐ FAIL |  |
| Camera | `python -m indepensense.vision.tests.manual.capture_test` | 10 frames printed with shape (H, W, C) at the configured resolution; nothing saved | | ☐ PASS ☐ FAIL |  |
| Buzzer | `python -m indepensense.feedback.tests.manual.buzzer_test` | Sounds when triggered | | ☐ PASS ☐ FAIL |  |
| Motors (3×) | `python -m indepensense.feedback.tests.manual.vibration_test` | All three spin independently | | ☐ PASS ☐ FAIL |  |
| Buttons (3×) | `python -m indepensense.feedback.tests.manual.button_test` | Three runs: no argument (PTT, GPIO 23), `25` (emergency, front), `24` (repeat, left); each prints press/release | | ☐ PASS ☐ FAIL |  |
| Microphone | `python -m indepensense.voice.tests.manual.echo_test` | Records 25 s, prints the transcript, speaks it back | | ☐ PASS ☐ FAIL |  |
| Speaker | `python -m indepensense.voice.tests.manual.echo_test` | Transcript spoken back audibly (`tts_test` only writes a WAV) | | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 12 passed

---

## FINAL SUMMARY

| CATEGORY | PASSED | TOTAL | % |
|----------|--------|-------|---|
| Startup & Boot | ___ | 9 | __% |
| PTT Latency | ___ | 4 | __% |
| STT English | ___ | 12 | __% |
| STT Tagalog | ___ | 7 | __% |
| NLU English | ___ | 28 | __% |
| NLU Tagalog | ___ | 8 | __% |
| Buttons (PTT/SOS/Repeat) | ___ | 24 | __% |
| Sensor Accuracy | ___ | 20 | __% |
| Obstacle Detection | ___ | 22 | __% |
| Fall Detection | ___ | 9 | __% |
| Haptic Feedback | ___ | 9 | __% |
| Audio & TTS | ___ | 9 | __% |
| Volume Control | ___ | 6 | __% |
| Navigation | ___ | 15 | __% |
| Computer Vision (YOLO) | ___ | 4 | __% |
| Computer Vision (OCR) | ___ | 5 | __% |
| Battery & Power | ___ | 12 | __% |
| GPS & Positioning | ___ | 7 | __% |
| Cellular & Telemetry | ___ | 7 | __% |
| Language & Localization | ___ | 6 | __% |
| Saved Places | ___ | 6 | __% |
| Concurrent Operations | ___ | 5 | __% |
| Edge Cases | ___ | 7 | __% |
| First-Boot Hardware | ___ | 12 | __% |
| **TOTAL** | **___** | **253** | **___% ** |

---

## CRITICAL ISSUES FOUND

| ISSUE # | CATEGORY | SEVERITY | DESCRIPTION | NOTES | RESOLUTION |
|---------|----------|----------|---|---|---|
| 1 |  | ☐ CRITICAL ☐ MAJOR ☐ MINOR |  |  |  |
| 2 |  | ☐ CRITICAL ☐ MAJOR ☐ MINOR |  |  |  |
| 3 |  | ☐ CRITICAL ☐ MAJOR ☐ MINOR |  |  |  |
| 4 |  | ☐ CRITICAL ☐ MAJOR ☐ MINOR |  |  |  |
| 5 |  | ☐ CRITICAL ☐ MAJOR ☐ MINOR |  |  |  |

---

## TESTER SIGN-OFF

**Test Date:** ________________  
**Total Duration:** ________________  
**Tester Name:** ________________  
**Tester Signature:** ________________

**Reviewed By:** ________________  
**Reviewer Signature:** ________________  
**Date:** ________________

---

## RECOMMENDATIONS & NOTES FOR NEXT ITERATION

