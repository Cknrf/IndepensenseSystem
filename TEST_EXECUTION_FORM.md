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
| BOOT-002 | Wait 5 seconds | Fall detection active, obstacle warnings active | | ☐ PASS ☐ FAIL |  |
| BOOT-003 | Wait full boot (~200s) | All models loaded, voice commands ready | | ☐ PASS ☐ FAIL | Total boot time: ___ s |
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

### 2.1 Push-to-Talk Response

| TRIAL | ACTION | EXPECTED | ACTUAL | LATENCY | STATUS | NOTES |
|-------|--------|----------|--------|---------|--------|-------|
| PTT-LAT-001 | Press PTT button | Chime plays | | ≤150 ms | ☐ PASS ☐ FAIL |  |
| PTT-LAT-002 | Press PTT during speech | Speech cuts, chime plays | | ≤150 ms | ☐ PASS ☐ FAIL |  |
| PTT-LAT-003 | Release PTT | Recording stops, processing starts | | <200 ms | ☐ PASS ☐ FAIL |  |
| PTT-LAT-004 | Rapid PTT presses (5 in 2s) | Each chime plays with consistent latency | | ≤150 ms each | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 4 passed

---

## 3. SPEECH-TO-TEXT (STT) - ENGLISH

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
| STT-EN-008 | "Help" (mumbled) | Recognizable as intent-carrying words | | ☐ Yes ☐ Partial | ☐ PASS ☐ FAIL |  |
| STT-EN-009 | Background noise (traffic ~60dB) + normal speech | Transcribed despite noise | | ☐ Yes ☐ Partial ☐ No | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 4 passed

### 3.3 Edge Cases

| TRIAL | CONDITION | EXPECTED | ACTUAL | STATUS | NOTES |
|-------|-----------|----------|--------|--------|-------|
| STT-EN-010 | Empty input (silence, no speech) | "I didn't catch that" announced | | ☐ PASS ☐ FAIL |  |
| STT-EN-011 | Very long utterance (30+ seconds) | Continues to record, no overflow | | ☐ PASS ☐ FAIL |  |
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

**Objective:** Test every English intent is correctly recognized.

### 5.1 Navigation Intents

| TRIAL | INTENT | EXAMPLE PHRASE | EXPECTED RESULT | ACTUAL RESULT | CORRECT? | STATUS | NOTES |
|-------|--------|---|---|---|---|---|---|
| NLU-EN-001 | navigation.start | "Take me to McDonald's" | Route starts, destination read back, waits for confirm (PTT press) | | ☐ Yes ☐ No | ☐ PASS ☐ FAIL | Time to destination confirmation: ___ s |
| NLU-EN-002 | navigation.start (variation) | "Navigate to the nearest Jollibee" | Route starts | | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |
| NLU-EN-003 | navigation.start (saved place) | "Take me home" | Route starts immediately (no geocoding, no confirmation) | | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |
| NLU-EN-004 | navigation.stop | "Cancel navigation" | Active route cancels, "cancelled" announced | | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |
| NLU-EN-005 | navigation.location | "Where am I" | Current location announced | | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |
| NLU-EN-006 | navigation.progress | "How much further" | Distance to destination announced | | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 6 passed

### 5.2 Place Management Intents

| TRIAL | INTENT | EXAMPLE PHRASE | EXPECTED RESULT | ACTUAL RESULT | CORRECT? | STATUS | NOTES |
|-------|--------|---|---|---|---|---|---|
| NLU-EN-007 | place.save | "Save this place as home" | Place saved with name, "saved home" announced | | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |
| NLU-EN-008 | place.save (variant) | "I'm at work, save it" | Place saved | | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |
| NLU-EN-009 | place.locate | "What is the exact location of my home" | Coordinates + distance from current position announced | | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |
| NLU-EN-010 | place.locate (public place) | "Where is Jollibee" | Address announced (geocoded) + distance | | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |
| NLU-EN-011 | place.list | "What places have I saved" | List of saved places announced | | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |
| NLU-EN-012 | place.delete | "Forget the place saved as home" | Confirmation, "forgot home" announced | | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |

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
| NLU-EN-017 | device.status | "How much battery do I have" | Battery %, GPS lock, cellular signal strength announced | | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |
| NLU-EN-018 | system.time | "What time is it" | Current time announced | | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |
| NLU-EN-019 | system.help | "What can you do" | Help message spoken | | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 3 passed

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
| NLU-EN-024 | emergency.trigger | "Help" | Buzzer + motors fire, alert sent to backend + SMS | | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |
| NLU-EN-025 | system.shutdown | "Shut down" | Confirmation prompt, waits for PTT press | | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |
| NLU-EN-026 | unknown (cloud LLM) | "How does photosynthesis work" | Escalates to cloud LLM, receives answer | | ☐ Yes ☐ No | ☐ PASS ☐ FAIL | Latency: ___ s |

**Summary:** ___ / 3 passed

---

## 6. INTENT CLASSIFICATION - NLU (TAGALOG)

### 6.1 Core Tagalog Intents

| TRIAL | INTENT | EXAMPLE PHRASE (TAGALOG) | EXPECTED RESULT | ACTUAL RESULT | CORRECT? | STATUS | NOTES |
|-------|--------|---|---|---|---|---|---|
| NLU-TL-001 | navigation.start | "Dalhin mo ako sa Jollibee" | Route starts, destination in Tagalog | | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |
| NLU-TL-002 | navigation.stop | "Kanselahin ang navigation" | Route cancels | | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |
| NLU-TL-003 | navigation.location | "Nasaan ako" | Current location announced in Tagalog | | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |
| NLU-TL-004 | device.status | "Magkano ang baterya" | Battery announced in Tagalog | | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |
| NLU-TL-005 | place.save | "I-save ang lugar na ito bilang bahay" | Place saved with Tagalog name | | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |
| NLU-TL-006 | system.language | "Lumipat sa English" | Switches to English, confirmation in English | | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |
| NLU-TL-007 | system.volume | "Mas malakas" (louder) | Volume increases | | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |
| NLU-TL-008 | emergency.trigger | "Tulong" | Buzzer + motors fire, alert sent | | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 8 passed

---

## 7. BUTTON FUNCTIONALITY

### 7.1 Push-to-Talk (PTT) Button

| TRIAL | ACTION | EXPECTED BEHAVIOR | ACTUAL BEHAVIOR | STATUS | NOTES |
|-------|--------|---|---|---|---|
| BTN-PTT-001 | Press PTT | Chime plays within 150 ms | | ☐ PASS ☐ FAIL | Actual latency: ___ ms |
| BTN-PTT-002 | Press + hold PTT, speak | Microphone records | | ☐ PASS ☐ FAIL |  |
| BTN-PTT-003 | Release PTT | Processing starts, "working blip" if >1.5s latency | | ☐ PASS ☐ FAIL |  |
| BTN-PTT-004 | Press PTT during speech | Speech cuts, chime plays, recording starts | | ☐ PASS ☐ FAIL |  |
| BTN-PTT-005 | Rapid PTT (5 presses in 2s) | Each press handled independently, chimes play | | ☐ PASS ☐ FAIL |  |
| BTN-PTT-006 | Hold PTT for 30+ seconds | Recording continues, no overflow error | | ☐ PASS ☐ FAIL |  |
| BTN-PTT-007 | PTT during fall detection | Fall alert fires, PTT interrupted | | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 7 passed

### 7.2 Emergency (SOS) Button

| TRIAL | ACTION | EXPECTED BEHAVIOR | ACTUAL BEHAVIOR | STATUS | NOTES |
|-------|--------|---|---|---|---|
| BTN-SOS-001 | Press SOS button | Buzzer sounds immediately (loud, distinctive) | | ☐ PASS ☐ FAIL | Time to sound: ___ ms |
| BTN-SOS-002 | SOS pressed | All three motors pulse together (danger pattern) | | ☐ PASS ☐ FAIL |  |
| BTN-SOS-003 | SOS pressed | "Emergency alert" announced to user | | ☐ PASS ☐ FAIL |  |
| BTN-SOS-004 | SOS pressed (online) | Backend receives alert via HTTP POST | | ☐ PASS ☐ FAIL | Check backend logs |
| BTN-SOS-005 | SOS pressed (online) | SMS sent to guardian contact | | ☐ PASS ☐ FAIL | Check phone |
| BTN-SOS-006 | SOS pressed, double-press within 10s | Buzzer sounds both times, but only ONE alert logged | | ☐ PASS ☐ FAIL | Backend should show 1 event |
| BTN-SOS-007 | SOS pressed during PTT | PTT cancels, SOS alert fires immediately | | ☐ PASS ☐ FAIL |  |
| BTN-SOS-008 | SOS pressed (offline, no network) | Buzzer fires locally, alert queued for retry | | ☐ PASS ☐ FAIL | Check logs for retry logic |
| BTN-SOS-009 | SOS pressed during navigation | Navigation cancels, alert takes priority | | ☐ PASS ☐ FAIL |  |
| BTN-SOS-010 | Hold SOS for 10+ seconds | Alert fires once, holding doesn't re-trigger | | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 10 passed

### 7.3 Repeat / Stop Button

| TRIAL | ACTION | EXPECTED BEHAVIOR | ACTUAL BEHAVIOR | STATUS | NOTES |
|-------|--------|---|---|---|---|
| BTN-REP-001 | Press after device speaks | Last response replays | | ☐ PASS ☐ FAIL |  |
| BTN-REP-002 | Press during device speech | Speech cuts, "stop cue" tone plays | | ☐ PASS ☐ FAIL |  |
| BTN-REP-003 | Press before any response | "Nothing to repeat" announced | | ☐ PASS ☐ FAIL |  |
| BTN-REP-004 | Press at "confirm destination" prompt | Counts as "no" / reject | | ☐ PASS ☐ FAIL |  |
| BTN-REP-005 | Rapid repeat presses | Each handled independently | | ☐ PASS ☐ FAIL |  |
| BTN-REP-006 | Press during OCR reading | Text reading stops | | ☐ PASS ☐ FAIL |  |
| BTN-REP-007 | Press during obstacle warning | Obstacle pattern resumes after stop cue | | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 7 passed

---

## 8. SENSOR CALIBRATION & ACCURACY

### 8.1 Ultrasonic Sensors (Distance Measurement)

**Setup:** Place obstacles at known distances using tape measure.

#### Top Sensor (Head Height)

| TRIAL | DISTANCE | EXPECTED | ACTUAL | DEVIATION | STATUS | NOTES |
|-------|----------|----------|--------|-----------|--------|-------|
| SENSOR-US-TOP-001 | 20 cm | 20±5 cm | | | ☐ PASS ☐ FAIL |  |
| SENSOR-US-TOP-002 | 30 cm | 30±5 cm | | | ☐ PASS ☐ FAIL |  |
| SENSOR-US-TOP-003 | 50 cm | 50±5 cm | | | ☐ PASS ☐ FAIL |  |
| SENSOR-US-TOP-004 | 75 cm | 75±5 cm | | | ☐ PASS ☐ FAIL |  |
| SENSOR-US-TOP-005 | 100 cm | 100±5 cm | | | ☐ PASS ☐ FAIL |  |
| SENSOR-US-TOP-006 | 150 cm | 150±5 cm | | | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 6 passed

#### Bottom Sensor (Shin Level)

| TRIAL | DISTANCE | EXPECTED | ACTUAL | DEVIATION | STATUS | NOTES |
|-------|----------|----------|--------|-----------|--------|-------|
| SENSOR-US-BOT-001 | 15 cm | 15±5 cm | | | ☐ PASS ☐ FAIL |  |
| SENSOR-US-BOT-002 | 25 cm | 25±5 cm | | | ☐ PASS ☐ FAIL |  |
| SENSOR-US-BOT-003 | 40 cm | 40±5 cm | | | ☐ PASS ☐ FAIL |  |
| SENSOR-US-BOT-004 | 60 cm | 60±5 cm | | | ☐ PASS ☐ FAIL |  |
| SENSOR-US-BOT-005 | 80 cm | 80±5 cm | | | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 5 passed

### 8.2 IMU (Accelerometer & Gyroscope)

| TRIAL | ACTION | EXPECTED | ACTUAL | STATUS | NOTES |
|-------|--------|----------|--------|--------|-------|
| SENSOR-IMU-001 | Device stationary, level | Accel readings: ~0,0,1g (gravity on Z) | | ☐ PASS ☐ FAIL | X: ___ Y: ___ Z: ___ |
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
| SENSOR-MAG-005 | Compare with phone compass | Headings match ±15° (not perfectly calibrated) | | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 5 passed

---

## 9. OBSTACLE DETECTION & HAPTIC FEEDBACK

### 9.1 Obstacle Detection Tiers (Top Sensor)

**Setup:** Place obstacle and move through distance zones.

| TRIAL | DISTANCE & DIRECTION | EXPECTED TIER | EXPECTED FEEDBACK | ACTUAL FEEDBACK | STATUS | NOTES |
|-------|---|---|---|---|---|---|
| OBS-TIER-001 | 30 cm, center/front | Danger (<50cm) | All three motors pulse (200ms) | | ☐ PASS ☐ FAIL |  |
| OBS-TIER-002 | 50 cm, left | Warning (50-100cm) | Left motor vibrates (150ms) | | ☐ PASS ☐ FAIL |  |
| OBS-TIER-003 | 75 cm, right | Warning | Right motor vibrates | | ☐ PASS ☐ FAIL |  |
| OBS-TIER-004 | 100 cm, center | Far (100-150cm) | Front/center motor light pulse (300ms) | | ☐ PASS ☐ FAIL |  |
| OBS-TIER-005 | 150 cm, center | Far | Light pulse, slow rate | | ☐ PASS ☐ FAIL |  |
| OBS-TIER-006 | Move obstacle beyond 150cm | No feedback | Vibration stops | | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 6 passed

### 9.2 Hysteresis & Re-Alert Behavior

| TRIAL | ACTION | EXPECTED | ACTUAL | STATUS | NOTES |
|-------|--------|----------|--------|--------|-------|
| OBS-HYSTER-001 | Obstacle at 65 cm, hold 10s | Single fire on entry, no repeat | Fires once @ entry, silent for 10s | ☐ PASS ☐ FAIL |  |
| OBS-HYSTER-002 | Obstacle exits (move to 160cm) | Vibration stops, no repeat | Silent | ☐ PASS ☐ FAIL |  |
| OBS-HYSTER-003 | Re-enter danger zone | Alert fires again (hysteresis reset) | All motors fire @ re-entry | ☐ PASS ☐ FAIL |  |
| OBS-HYSTER-004 | Obstacle static, detect motion (walking) | Danger tier repeats every 3s | Alert at 0s, 3s, 6s pattern | ☐ PASS ☐ FAIL |  |
| OBS-HYSTER-005 | Obstacle static, no motion (standing) | Danger tier repeats every 15s | Alert at 0s, 15s pattern | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 5 passed

### 9.3 Dual-Sensor Coordination

| TRIAL | TOP SENSOR | BOTTOM SENSOR | EXPECTED | ACTUAL | STATUS | NOTES |
|-------|-----------|---------------|----------|--------|--------|-------|
| OBS-DUAL-001 | 40 cm (danger) | 35 cm (danger) | Danger pattern (all motors) | | ☐ PASS ☐ FAIL |  |
| OBS-DUAL-002 | 80 cm (warning) | 60 cm (warning) | Warning pattern (directional) | | ☐ PASS ☐ FAIL |  |
| OBS-DUAL-003 | 120 cm (far) | 40 cm (danger) | Worst-case wins (danger) | | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 3 passed

---

## 10. FALL DETECTION & EMERGENCY RESPONSE

### 10.1 Live Fall Detection

| TRIAL | ACTION | EXPECTED | ACTUAL | LATENCY | STATUS | NOTES |
|-------|--------|----------|--------|---------|--------|-------|
| FALL-001 | Drop device from 1m on foam mat | Buzzer fires | | <500 ms | ☐ PASS ☐ FAIL | Time from impact: ___ ms |
| FALL-002 | Drop device | All three motors pulse (danger) | | <500 ms | ☐ PASS ☐ FAIL |  |
| FALL-003 | Drop device | "Fall detected" announced | | <1000 ms | ☐ PASS ☐ FAIL |  |
| FALL-004 | Drop device (online) | Alert sent to backend via HTTP | | <2000 ms | ☐ PASS ☐ FAIL | Check backend |
| FALL-005 | Drop device (online) | SMS sent to guardian | | <5000 ms | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 5 passed

### 10.2 False Positive Prevention

| TRIAL | ACTION | EXPECTED | ACTUAL | STATUS | NOTES |
|-------|--------|----------|--------|--------|-------|
| FALL-FP-001 | Jump in place (normal activity) | No alert | No buzzer/motors | ☐ PASS ☐ FAIL |  |
| FALL-FP-002 | Rapid arm swinging | No alert | | ☐ PASS ☐ FAIL |  |
| FALL-FP-003 | Stair descent (8-10 steps) | No alert or single brief pulse only | | ☐ PASS ☐ FAIL |  |
| FALL-FP-004 | Sit down normally | No alert | | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 4 passed

---

## 11. HAPTIC FEEDBACK (MOTORS & BUZZER)

### 11.1 Motor Patterns

| TRIAL | TRIGGER | EXPECTED PATTERN | ACTUAL PATTERN | STATUS | NOTES |
|-------|---------|---|---|---|---|
| HF-MOTOR-001 | Obstacle ahead (danger) | All three motors pulse 200ms | | ☐ PASS ☐ FAIL |  |
| HF-MOTOR-002 | Fall detected | All three motors pulse together | | ☐ PASS ☐ FAIL |  |
| HF-MOTOR-003 | Obstacle left (warning) | Left motor only vibrates | | ☐ PASS ☐ FAIL |  |
| HF-MOTOR-004 | Obstacle right (warning) | Right motor only vibrates | | ☐ PASS ☐ FAIL |  |
| HF-MOTOR-005 | Obstacle center (far) | Front motor light pulse | | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 5 passed

### 11.2 Buzzer

| TRIAL | TRIGGER | EXPECTED | ACTUAL | STATUS | NOTES |
|-------|---------|----------|--------|--------|-------|
| HF-BUZ-001 | SOS button pressed | Buzzer sounds loud/distinctive | | ☐ PASS ☐ FAIL |  |
| HF-BUZ-002 | Fall detected | Buzzer fires with same alert as SOS | | ☐ PASS ☐ FAIL |  |
| HF-BUZ-003 | Critical battery (5%) | Buzzer sounds (urgent) | | ☐ PASS ☐ FAIL |  |
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
| TTS-TL-001 | "Nagsalin kami sa Tagalog" | Understandable (lower quality than English) | | ☐ 5/5 ☐ 4/5 ☐ 3/5 | ☐ PASS ☐ FAIL |  |
| TTS-TL-002 | "Bawasan ang volume ng sampung porsyento" | Number rendered correctly | | ☐ 5/5 ☐ 4/5 | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 2 passed

### 12.3 Audio Playback & Cues

| TRIAL | CUE | EXPECTED | ACTUAL | STATUS | NOTES |
|-------|-----|----------|--------|--------|-------|
| TTS-CUE-001 | PTT chime | Rising tone, distinctive | | ☐ PASS ☐ FAIL |  |
| TTS-CUE-002 | Stop cue | Brief tone, distinct from chime | | ☐ PASS ☐ FAIL |  |
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
| VOL-006 | Buzzer at minimum volume | Buzzer still loud (unaffected by speaker volume) | | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 6 passed

---

## 14. NAVIGATION & ROUTING

### 14.1 Destination Selection & Confirmation

| TRIAL | ACTION | EXPECTED | ACTUAL | STATUS | NOTES |
|-------|--------|----------|--------|--------|-------|
| NAV-DEST-001 | Say "Take me to Jollibee" | Geocodes destination, reads back name + distance | | ☐ PASS ☐ FAIL | Time to confirmation prompt: ___ s |
| NAV-DEST-002 | Device waits for PTT press | User must press PTT within timeout (DESTINATION_CONFIRM_TIMEOUT_S) | | ☐ PASS ☐ FAIL | Timeout: ___ s |
| NAV-DEST-003 | Press PTT to confirm | Route starts, "heading [direction]" announced | | ☐ PASS ☐ FAIL |  |
| NAV-DEST-004 | Press repeat button (no) | Navigation cancels, device waits for next command | | ☐ PASS ☐ FAIL |  |
| NAV-DEST-005 | Do NOT press PTT (timeout) | Navigation cancels automatically | | ☐ PASS ☐ FAIL |  |
| NAV-DEST-006 | Say "Take me home" (saved) | Route starts immediately (no geocoding, no confirmation) | | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 6 passed

### 14.2 Turn-by-Turn Guidance

**Setup:** Walk a planned route (~500-1000m) and observe turn announcements.

| TRIAL | ACTION | EXPECTED | ACTUAL | STATUS | NOTES |
|-------|--------|----------|--------|--------|-------|
| NAV-TURN-001 | Approach turn 1 | "Turn [left/right] in X meters" announced in advance | | ☐ PASS ☐ FAIL | Distance before turn: ___ m |
| NAV-TURN-002 | Complete turn 1 | "Continue straight" / next instruction announced | | ☐ PASS ☐ FAIL |  |
| NAV-TURN-003 | Reach waypoint/destination | "You have arrived" announced | | ☐ PASS ☐ FAIL | Distance from true destination: ___ m |
| NAV-TURN-004 | Say "How much further" mid-route | Distance to destination announced | | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 4 passed

### 14.3 Off-Route Detection

| TRIAL | ACTION | EXPECTED | ACTUAL | TIME | STATUS | NOTES |
|-------|--------|----------|--------|------|--------|-------|
| NAV-OFF-001 | Miss a turn, walk straight | "You are off route" announced | | 15-30 s | ☐ PASS ☐ FAIL |  |
| NAV-OFF-002 | Backtrack 20-30 meters | Off-route alert fires | | <30 s | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 2 passed

### 14.4 Compass-Based Navigation (if COMPASS_CALIBRATED = True)

| TRIAL | ACTION | EXPECTED | ACTUAL | STATUS | NOTES |
|-------|--------|----------|--------|--------|-------|
| NAV-COMP-001 | Start route | Turn-to-face guidance: motor pulses on turn side | | ☐ PASS ☐ FAIL |  |
| NAV-COMP-002 | Align with destination heading | Motor pulse stops when facing correct direction | | ☐ PASS ☐ FAIL |  |
| NAV-COMP-003 | Miss a turn | Compass detects within ~5s that heading hasn't changed | | ☐ PASS ☐ FAIL | Time to detection: ___ s |

**Summary:** ___ / 3 passed

---

## 15. COMPUTER VISION

### 15.1 Object Detection (YOLO)

| TRIAL | SCENE | OBJECTS PRESENT | EXPECTED RESULT | ACTUAL RESULT | DETECTED? | STATUS | NOTES |
|-------|-------|---|---|---|---|---|---|
| YOLO-001 | Indoor hallway | Person + door | Announces both objects | | ☐ Yes ☐ Partial ☐ No | ☐ PASS ☐ FAIL |  |
| YOLO-002 | Outdoor street | Car + person + building | All three detected | | ☐ Yes ☐ Partial ☐ No | ☐ PASS ☐ FAIL |  |
| YOLO-003 | Dim lighting | Chair + table | Objects detected OR ultrasonic fallback | | ☐ Yes ☐ Fallback ☐ No | ☐ PASS ☐ FAIL | Fallback text: "something is X cm away" |
| YOLO-004 | Empty scene (nothing) | (none) | "I don't see anything recognizable" or ultrasonic fallback | | ☐ Correct | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 4 passed

### 15.2 Optical Character Recognition (OCR)

| TRIAL | TEXT SAMPLE | LANGUAGE | EXPECTED | ACTUAL | ACCURACY | STATUS | NOTES |
|-------|---|---|---|---|---|---|---|
| OCR-001 | "Emergency Exit" (large print, clear) | English | Perfect/near-perfect read | | ≥95% | ☐ PASS ☐ FAIL |  |
| OCR-002 | Menu text (small, standard print) | English | Most words readable | | ≥80% | ☐ PASS ☐ FAIL |  |
| OCR-003 | Tagalog printed text | Tagalog | Readable (TTS may sound robotic) | | ≥80% | ☐ PASS ☐ FAIL |  |
| OCR-004 | Handwritten text | English | Poor recognition expected | | <50% | ☐ PASS ☐ FAIL | Acceptable: graceful degradation |
| OCR-005 | Text at distance (2+ meters) | English | Unreadable (too small) | | 0% | ☐ PASS ☐ FAIL | Device announces "can't read" or silent |

**Summary:** ___ / 5 passed

---

## 16. BATTERY & POWER MANAGEMENT

### 16.1 Battery State Reporting

| TRIAL | ACTION | EXPECTED | ACTUAL | STATUS | NOTES |
|-------|--------|----------|--------|--------|-------|
| BAT-001 | Say "How much battery" | Battery % announced | | ☐ PASS ☐ FAIL | Reported: ___ % |
| BAT-002 | Check reported % vs. UPS HAT | Percentage accurate within ±10% | | ☐ PASS ☐ FAIL |  |
| BAT-003 | Device fully charged | Reports ~100% (or close if HAT has 59% bug) | | ☐ PASS ☐ FAIL | Reported: ___ % |
| BAT-004 | Device at 50% | Reports ~50% | | ☐ PASS ☐ FAIL | Reported: ___ % |

**Summary:** ___ / 4 passed

### 16.2 Low-Battery Alerts

| TRIAL | ACTION | EXPECTED | ACTUAL | STATUS | NOTES |
|-------|--------|----------|--------|--------|-------|
| BAT-LOW-001 | Drain to ~15% | Low-battery alert fires (spoken) | | ☐ PASS ☐ FAIL | Triggered at: ___ % |
| BAT-LOW-002 | Alert fires | "Low battery" announced | | ☐ PASS ☐ FAIL |  |
| BAT-LOW-003 | Alert sent to backend | HTTP POST received | | ☐ PASS ☐ FAIL | Check backend logs |
| BAT-LOW-004 | Alert sent via SMS | Guardian receives SMS | | ☐ PASS ☐ FAIL | Check phone |
| BAT-LOW-005 | Reboot after alert | Alert does NOT repeat (latch working) | | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 5 passed

### 16.3 Critical Battery Alert

| TRIAL | ACTION | EXPECTED | ACTUAL | STATUS | NOTES |
|-------|--------|----------|--------|--------|-------|
| BAT-CRIT-001 | Drain to ~5% | Critical warning fires (urgent announcement) | | ☐ PASS ☐ FAIL | Triggered at: ___ % |
| BAT-CRIT-002 | Critical alert | All three motors pulse (warning) | | ☐ PASS ☐ FAIL |  |
| BAT-CRIT-003 | SMS sent | Guardian receives critical alert | | ☐ PASS ☐ FAIL |  |

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
| NET-001 | Say "Device status" (online) | "Strong/medium/weak at X%, on 4G/5G" announced | | ☐ PASS ☐ FAIL | Signal reported: ___ |
| NET-002 | Weak signal area | "Weak" announced | | ☐ PASS ☐ FAIL |  |
| NET-003 | No signal area | "No signal" or graceful handling | | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 3 passed

### 18.2 Alert Delivery (Emergency, Fall, Low-Battery)

| TRIAL | ACTION | EXPECTED | ACTUAL | STATUS | NOTES |
|-------|--------|----------|--------|--------|-------|
| ALERT-001 | Press SOS (online) | Alert reaches backend within 2s | | ☐ PASS ☐ FAIL | Check backend logs |
| ALERT-002 | SOS (online) | SMS sent within 5s | | ☐ PASS ☐ FAIL | Check phone |
| ALERT-003 | Alert (offline) | Alert queued for retry | | ☐ PASS ☐ FAIL | Check logs |
| ALERT-004 | Offline → online | Queued alert retries and sends | | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 4 passed

---

## 19. LANGUAGE & LOCALIZATION

### 19.1 Language Switching

| TRIAL | ACTION | EXPECTED | ACTUAL | STATUS | NOTES |
|-------|--------|----------|--------|--------|-------|
| LANG-001 | Say "Switch to Tagalog" | Confirmation in Tagalog: "Nagsalin kami sa Tagalog" | | ☐ PASS ☐ FAIL |  |
| LANG-002 | After switch | All subsequent responses in Tagalog | | ☐ PASS ☐ FAIL |  |
| LANG-003 | Say "Lumipat sa English" | Confirmation in English | | ☐ PASS ☐ FAIL |  |
| LANG-004 | After switch back | Responses in English | | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 4 passed

### 19.2 Language Persistence

| TRIAL | ACTION | EXPECTED | ACTUAL | STATUS | NOTES |
|-------|--------|----------|--------|--------|-------|
| LANG-PERS-001 | Switch to Tagalog, reboot | Device boots in Tagalog mode | | ☐ PASS ☐ FAIL |  |
| LANG-PERS-002 | Responses in Tagalog after reboot | All speech in Tagalog | | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 2 passed

---

## 20. SAVED PLACES

| TRIAL | ACTION | EXPECTED | ACTUAL | STATUS | NOTES |
|-------|--------|----------|--------|--------|-------|
| PLACE-001 | Say "Save this place as home" | "Saved home" announced | | ☐ PASS ☐ FAIL |  |
| PLACE-002 | Say "Save this place as work" | "Saved work" announced | | ☐ PASS ☐ FAIL |  |
| PLACE-003 | Say "What places have I saved" | Lists all saved places | | ☐ PASS ☐ FAIL | Listed: _______________ |
| PLACE-004 | Say "Take me home" | Route starts to saved home | | ☐ PASS ☐ FAIL |  |
| PLACE-005 | Say "Forget home" | "Forgot home" announced | | ☐ PASS ☐ FAIL |  |
| PLACE-006 | Reboot after saving | Saved places persist | | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 6 passed

---

## 21. CONCURRENT OPERATIONS (THREAD SAFETY)

### 21.1 Fall Detection During Other Operations

| TRIAL | ACTION | EXPECTED | ACTUAL | STATUS | NOTES |
|-------|--------|----------|--------|--------|-------|
| THREAD-001 | Fall while device speaking | Fall alarm fires immediately (not blocked) | | ☐ PASS ☐ FAIL | Latency: ___ ms |
| THREAD-002 | Fall while PTT active | PTT cancels, fall alarm fires | | ☐ PASS ☐ FAIL |  |
| THREAD-003 | Fall during navigation | Navigation pauses, fall alert plays | | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 3 passed

### 21.2 Obstacle Detection During Voice

| TRIAL | ACTION | EXPECTED | ACTUAL | STATUS | NOTES |
|-------|--------|----------|--------|--------|-------|
| THREAD-004 | Device speaking, obstacle detected | Speech continues, vibration fires | | ☐ PASS ☐ FAIL |  |
| THREAD-005 | Navigation active, obstacle fired | Both feedbacks work (no conflict) | | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 2 passed

---

## 22. EDGE CASES & STRESS TESTS

### 22.1 Rapid User Input

| TRIAL | ACTION | EXPECTED | ACTUAL | STATUS | NOTES |
|-------|--------|----------|--------|--------|-------|
| EDGE-RAPID-001 | Press PTT 10 times in 5 seconds | Each handled independently | | ☐ PASS ☐ FAIL |  |
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
| EDGE-NET-002 | Network recovers after 5 min | Queued alert retries and sends | | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 2 passed

---

## 23. FIRST-BOOT HARDWARE VERIFICATION

**Objective:** Verify all hardware is wired and initialized correctly.

| COMPONENT | MANUAL TEST COMMAND | EXPECTED | ACTUAL | STATUS | NOTES |
|-----------|---|---|---|---|---|
| DYP-A22 Top | `dual_dyp_test` | Reads both sensors, valid distances | | ☐ PASS ☐ FAIL |  |
| DYP-A22 Bottom | `dual_dyp_test` | Reads both, no NaN or 0 | | ☐ PASS ☐ FAIL |  |
| MPU6050 IMU | `single_mpu6050_test` | Accel + gyro readings, no zeros | | ☐ PASS ☐ FAIL |  |
| QMC5883P Compass | `single_magnetometer_test` | Heading 0–360°, stable | | ☐ PASS ☐ FAIL |  |
| GPS (SIM7600) | `single_gps_test` | NMEA fixes arriving | | ☐ PASS ☐ FAIL |  |
| UPS HAT | `single_ups_test` | Voltage, current, % readable | | ☐ PASS ☐ FAIL |  |
| Camera | `capture_test` | Image captured, saved | | ☐ PASS ☐ FAIL |  |
| Buzzer | `buzzer_test` | Sounds when triggered | | ☐ PASS ☐ FAIL |  |
| Motors (3×) | `vibration_test` | All three spin independently | | ☐ PASS ☐ FAIL |  |
| Buttons (3×) | `button_test` | PTT, SOS, Repeat all respond | | ☐ PASS ☐ FAIL |  |
| Microphone | `stt_test` | Records and transcribes | | ☐ PASS ☐ FAIL |  |
| Speaker | `tts_test` | Audio plays out | | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 12 passed

---

## FINAL SUMMARY

| CATEGORY | PASSED | TOTAL | % |
|----------|--------|-------|---|
| Startup & Boot | ___ | 9 | __% |
| PTT Latency | ___ | 4 | __% |
| STT English | ___ | 12 | __% |
| STT Tagalog | ___ | 7 | __% |
| NLU English | ___ | 26 | __% |
| NLU Tagalog | ___ | 8 | __% |
| Buttons (PTT/SOS/Repeat) | ___ | 24 | __% |
| Sensor Accuracy | ___ | 20 | __% |
| Obstacle Detection | ___ | 14 | __% |
| Fall Detection | ___ | 9 | __% |
| Haptic Feedback | ___ | 9 | __% |
| Audio & TTS | ___ | 9 | __% |
| Volume Control | ___ | 6 | __% |
| Navigation | ___ | 13 | __% |
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
| **TOTAL** | **___** | **252** | **___% ** |

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

