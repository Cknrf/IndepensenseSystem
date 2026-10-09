# IndepenSense Holistic Test Plan

**Purpose:** Integration testing of the complete prototype to identify bugs, edge cases, and real-world failure modes. Tests are categorized by feature and include both happy-path scenarios and edge conditions.

**Test Environment:** Raspberry Pi 5 with full hardware stack (all sensors, motors, buttons, GPS/modem, camera). All external services running (GraphHopper, Photon, Ollama).

**Notation:**
- ✓ = Normal operation expected
- ⚠ = Graceful degradation expected
- ✗ = Failure scenario to catch
- [Requires X] = Specific hardware/service requirement

---

## 1. STARTUP & INITIALIZATION

### 1.1 Cold Boot
- [ ] **Power on with no prior state** ✓
  - Wait full boot sequence (models load)
  - Verify boot announcement plays before any models load
  - Fall detection active within 5 seconds
  - Obstacle warnings active within 5 seconds
  - Voice ready within ~200 seconds (log the actual time)
  - All sensors initialized without errors

- [ ] **Power on with corrupted var/ files** ✗
  - Corrupt `var/language`, `var/volume`, `var/places.json`
  - Device should start with defaults, not crash
  - Verify fallback to `DEFAULT_LANGUAGE`, `VOLUME_DEFAULT_PERCENT`

- [ ] **Power on with missing critical models** ✗
  - Rename `models/whisper/` or `models/nlu/` temporarily
  - Device should fail with clear error (not silent hang)
  - Check journal for model-not-found message

- [ ] **Power on with disk full** ✗
  - Fill SD card to >95% capacity
  - Device should boot and degrade gracefully
  - Verify it doesn't crash on telemetry writes or logging

- [ ] **Power on during network degradation** ⚠
  - Boot with no cellular signal, no WiFi
  - Obstacle detection, fall detection, offline routing all work
  - No timeout hangs in startup

### 1.2 Warm Reboot
- [ ] **Reboot preserves user state** ✓
  - Set language to Tagalog, volume to 70%, save a place
  - Reboot
  - Verify language, volume, and saved place persist

- [ ] **Reboot after crash** ✗
  - Trigger a process crash (e.g., unplug sensor mid-run)
  - systemd restarts service automatically
  - Boot sequence repeats cleanly, no orphaned threads

- [ ] **Multiple rapid reboots** ✗
  - Power cycle 5 times within 10 seconds
  - Check for database lock errors, corrupted files
  - Verify no thread leaks or hung processes

---

## 2. FALL DETECTION & SAFETY

### 2.1 Fall Detection Accuracy
- [ ] **Recorded fall scenarios** ✓
  - Run `fall_probe` against all recorded traces (fall_* and adl_*)
  - Verify sensitivity ≥ 95%, specificity ≥ 95%
  - Document any false positives or false negatives

- [ ] **Freefall detection** ✓
  - Drop wearable safely from 1 meter (controlled test)
  - Fall detected within 500 ms of impact
  - Both impact route and freefall route evaluated

- [ ] **Trip detection** ✓
  - Simulate trip (controlled fall while walking)
  - Device detects horizontal body + stillness
  - No false positive on normal walking

- [ ] **Stair descent** ⚠
  - Walk down 1 flight of stairs (8-10 steps)
  - May trigger false positive (stair descent looks like falling)
  - Verify it settles quickly, doesn't repeat-alert

- [ ] **False positive scenarios** ✗
  - Rapid arm swinging while standing
  - Jumping in place
  - Suddenly lying down on floor
  - All should NOT trigger fall alarm

### 2.2 Emergency Button
- [ ] **SOS button press** ✓
  - Press emergency button
  - Buzzer sounds immediately
  - All three motors pulse (danger pattern)
  - Alert sent to backend + SMS to guardians
  - Visual/audible confirmation to user

- [ ] **Double-press within 10s** ✓
  - Press SOS, release
  - Press SOS again within 10 seconds
  - Buzzer sounds (button felt), but NO duplicate alert sent
  - Log shows only one alert event

- [ ] **SOS during voice command** ✓
  - Press PTT to start navigation query
  - Mid-transcript, press SOS
  - Voice cancels, fall alarm plays, alert sent
  - Navigation never starts

- [ ] **SOS while announcer is speaking** ✓
  - Device speaks (e.g., "turn right in 50 meters")
  - Press SOS mid-sentence
  - Speech cuts immediately, alarm plays

- [ ] **SOS with no network** ⚠
  - Disconnect cellular and WiFi
  - Press SOS
  - Buzzer sounds, SMS queued for retry
  - No hang (no timeout waiting for HTTP)

### 2.3 Fall + Network Interaction
- [ ] **Fall detected, network online** ✓
  - Trigger fall detection
  - Alert POST to backend within 2 seconds
  - SMS sent within 5 seconds
  - User hears "Fall detected" spoken aloud

- [ ] **Fall detected, network down** ⚠
  - Disconnect network before fall
  - Trigger fall
  - Buzzer + motors fire immediately (not waiting for network)
  - Alert queued for retry
  - User still hears announcement

- [ ] **Fall, network recovers** ✓
  - Fall + network down
  - Network reconnects within 30 seconds
  - Alert retries and sends

---

## 3. OBSTACLE DETECTION & FEEDBACK

### 3.1 Ultrasonic Sensor Fusion
- [ ] **Static obstacle, top sensor detects** ✓
  - Place object 30 cm from top sensor
  - Within 100 ms, vibration feedback fires on danger tier
  - Distance accuracy ±5 cm

- [ ] **Static obstacle, bottom sensor detects** ✓
  - Place object 20 cm from bottom sensor (shin level)
  - Vibration fires, correct motor pattern
  - No buzzer (buzzer reserved for emergencies)

- [ ] **Obstacle enters warning tier** ✓
  - Obstacle at 100 cm (far tier)
  - Move closer to 70 cm (warning tier)
  - Vibration pattern changes, fires once on entry

- [ ] **Obstacle in hysteresis band** ✓
  - Place obstacle at 65 cm
  - Vibration fires once
  - Keep obstacle at 65 cm for 5 seconds
  - Pattern does NOT repeat (hysteresis working)

- [ ] **Obstacle exits, re-enters** ✓
  - Obstacle at 50 cm (danger, vibrating)
  - Move beyond 100 cm (exited all tiers)
  - Move back to 50 cm
  - Vibration fires again (hysteresis reset)

- [ ] **Multiple obstacles** ✗
  - Place two objects (top and bottom sensors simultaneously)
  - Verify danger tier pulses all three motors
  - Log shows both distances

- [ ] **Walking with head-level obstacle** ✓
  - Walk under low ceiling/awning (~200 cm high)
  - Verify no false alarm (head tier at 200 cm doesn't fire)
  - Move head up to touch ceiling
  - Verify head tier fires, stops when head clears

### 3.2 Vision-based Obstacle Detection
- [ ] **YOLO detects obstacle on demand** ✓
  - Say "What's around me"
  - Camera captures, YOLO runs
  - Recognizes common obstacles (person, chair, etc.)
  - Announces them

- [ ] **YOLO detects nothing, ultrasonic has target** ✓
  - Place obstacle out of camera view but in ultrasonic range
  - Say "What's around me"
  - YOLO returns empty
  - Falls back to ultrasonic distance: "something is X cm away"

- [ ] **YOLO and ultrasonic conflict** ✓
  - Place object in view AND ultrasonic range
  - YOLO detects something different
  - Verify no duplicate announcement (one or the other, not both)

### 3.3 Obstacle Feedback Patterns
- [ ] **Far tier only** ✓
  - Obstacle at 100–150 cm
  - Vibration is light pulse, one motor (direction of obstacle)

- [ ] **Warning tier** ✓
  - Obstacle at 50–100 cm
  - Vibration increases (faster pulse)

- [ ] **Danger tier** ✓
  - Obstacle at <50 cm
  - All three motors pulse together (most distinctive)
  - Pattern repeats every 3 seconds if walking, every 15 seconds if still

- [ ] **Motor directional feedback** ✓
  - Obstacle to the left → left motor vibrates
  - Obstacle to the right → right motor vibrates
  - Obstacle dead ahead → front motor vibrates

---

## 4. NAVIGATION & ROUTING

### 4.1 Destination Selection & Confirmation
- [ ] **Navigate to known place** ✓
  - Say "Take me to Jollibee"
  - Device geocodes via Photon, ranks candidates by distance
  - Reads back the chosen destination and distance
  - User has `DESTINATION_CONFIRM_TIMEOUT_S` to press PTT to confirm

- [ ] **Destination confirmation timeout** ✗
  - Say "Take me to Jollibee"
  - Do NOT press PTT within timeout window
  - Navigation cancels, announces "cancelled"
  - No route starts

- [ ] **Destination confirmation rejected** ✓
  - Say "Take me to Jollibee"
  - Press repeat button (no) instead of PTT
  - Navigation cancels
  - Device waits for next command

- [ ] **Saved place navigation** ✓
  - Save current location as "home"
  - Later, say "Take me home"
  - Route starts immediately (no geocoder, no confirmation prompt)

- [ ] **Ambiguous place name** ⚠
  - Say "Take me to McDonald's" (chain with multiple branches)
  - Photon returns multiple candidates
  - Device picks nearest by distance (not by Photon's relevance)
  - Reads back the chosen one

- [ ] **Nonexistent place** ✗
  - Say "Take me to XYZ12345ABC"
  - Photon returns no results
  - Device announces "I couldn't find that place"
  - No route starts

- [ ] **Navigation with no network** ⚠
  - Disconnect cellular
  - Say "Take me home" (saved place)
  - Route starts (no geocoding needed for saved places)
  - Try "Take me to Jollibee" (requires geocoding)
  - Announces "No network, can't geocode"

### 4.2 Active Navigation
- [ ] **Turn-by-turn guidance** ✓
  - Start navigation to a location ~500 m away
  - Follow turns as announced
  - Verify "turn left in 50 meters", "turn right", "you have arrived" sequence
  - Each announcement at appropriate distance/angle

- [ ] **Off-route detection** ✓
  - Start navigation
  - Deliberately walk off the planned route
  - Within 15–30 seconds, device announces "You are off route"
  - Option to recalculate or cancel

- [ ] **Turn verification (compass-based)** ✓ [COMPASS_CALIBRATED = True]
  - Start navigation, reach a turn
  - Deliberately miss the turn, walk straight
  - Compass detects within ~5 seconds that heading hasn't changed
  - "You haven't turned" alert plays before off-route timer fires

- [ ] **Turn-to-face guidance** ✓ [COMPASS_CALIBRATED = True]
  - Start navigation
  - Before first step, device should give turn-to-face cue
  - Motor on the turn side pulses, faster as user aligns
  - Pulse stops when facing correct direction

- [ ] **Navigation during obstacles** ✓
  - Active navigation, approaching obstacle
  - Obstacle alarm fires (haptic, no voice interruption)
  - Continue receiving turn-by-turn cues
  - Obstacle and navigation feedback don't interfere

- [ ] **Navigation cancel mid-route** ✓
  - Start navigation
  - Mid-route, say "Cancel navigation"
  - Route stops, no more turn announcements
  - Device waits for next command

- [ ] **Navigation with compass uncalibrated** ⚠
  - Set `COMPASS_CALIBRATED = False`
  - Start navigation
  - Turn-by-turn works (position-based)
  - Turn verification and turn-to-face do NOT run
  - No error; graceful degradation

### 4.3 Progress & Distance Queries
- [ ] **"How much further" mid-route** ✓
  - Start navigation
  - Say "How much further"
  - Device announces remaining distance along route (not as-the-crow-flies)

- [ ] **"How much further" before navigation** ✗
  - No active route
  - Say "How much further"
  - Announces "No active route" or similar

- [ ] **"Where am I" during navigation** ✓
  - Start navigation
  - Say "Where am I"
  - Announces current location (geocoded)

- [ ] **"Where am I" with no GPS fix** ⚠
  - Indoors, no GPS signal
  - Say "Where am I"
  - Announces "No GPS fix" or last known position

---

## 5. VOICE INTERACTION (PTT → STT → NLU → TTS)

### 5.1 Push-to-Talk Flow
- [ ] **Normal PTT press** ✓
  - Press PTT button
  - Chime plays immediately (low latency)
  - Recording starts
  - Speak clearly: "Take me to Jollibee"
  - Release button
  - Device processes and responds

- [ ] **PTT while device is speaking** ✓
  - Device announces something
  - Press PTT mid-speech
  - Speech cuts immediately
  - Chime plays, recording starts
  - User can interrupt and give new command

- [ ] **Very short PTT (< 300 ms)** ⚠
  - Press and release PTT very quickly
  - Transcript is likely empty
  - Device announces "I didn't catch that" (not silent)

- [ ] **Very long PTT (> 30 seconds)** ⚠
  - Press and hold PTT for 30+ seconds
  - Audio buffer handling should not overflow
  - Eventually times out or responds with error

- [ ] **PTT during startup (models not loaded)** ⚠
  - Power on, immediately press PTT (before models load)
  - Busy cue plays
  - Command is rejected, user is told to wait

- [ ] **Multiple PTT presses in succession** ✓
  - Press PTT, say "turn right"
  - Device responds
  - Immediately press PTT again, say "what's around me"
  - Verify no overlap, clean handoff

- [ ] **PTT in noisy environment** ⚠
  - Press PTT in background noise
  - Whisper STT processes it (may be low confidence)
  - Device handles garbled transcript gracefully

### 5.2 Speech-to-Text (Whisper)
- [ ] **Clear, English speech** ✓
  - Press PTT, say "Take me to Jollibee" clearly
  - Whisper transcribes accurately

- [ ] **Accented English** ✓
  - Press PTT, speak with accent (e.g., Filipino accent)
  - Verify transcription accuracy (Whisper trained on diverse accents)

- [ ] **Code-switching (Taglish)** ✓
  - Press PTT, say "Take me sa nearest Jollibee"
  - Whisper handles mixed English-Tagalog

- [ ] **Mumbling / unclear speech** ⚠
  - Press PTT, speak unclearly
  - Whisper may drop words or mishear
  - Intent classifier handles partial transcript

- [ ] **Whisper returns empty transcript** ⚠
  - Press PTT, play background music
  - Release without speaking
  - Device announces "I didn't catch that" (not silent)

- [ ] **Whisper confidence score** ⚠
  - Measure confidence scores across 20 utterances
  - Log confidence for later analysis (are some intents harder to recognize?)

### 5.3 Intent Classification (Embedding Fast Path vs. LLM)
- [ ] **Fast-path intent (embedding matcher succeeds)** ✓
  - Say "What time is it" (fast-path intent)
  - Device should answer within 1–2 seconds (no LLM needed)
  - Verify from logs that embedding fast path was used

- [ ] **LLM-required intent** ✓
  - Say "How does photosynthesis work" (open-span question)
  - Embedding fast path escalates to LLM
  - Device answers after 3–7 seconds

- [ ] **Ambiguous input (embedding contested)** ⚠
  - Craft an input that matches two different intents with high similarity
  - Classifier escalates to LLM to disambiguate
  - LLM picks the correct one

- [ ] **Below-threshold confidence** ✓
  - Intentionally say something unrelated: "blah blah blah"
  - Embedding confidence is low
  - Escalates to cloud LLM fallback (if online)
  - Cloud fallback returns "I don't understand" or tries to help

- [ ] **Intent parser fails** ✗
  - Corrupt or delete `config.NLU_PROMPT_PATH`
  - Device should fail at startup with clear error

### 5.4 Cloud LLM Fallback
- [ ] **Unknown intent, online** ✓
  - Ask something not in the intent bank: "Can you tell me about quantum physics?"
  - Device escalates to cloud LLM (Mistral)
  - Receives and speaks answer

- [ ] **Unknown intent, offline** ⚠
  - Disconnect network
  - Ask same question
  - Device announces "No network, I don't have that answer"

- [ ] **Cloud LLM timeout** ✗
  - Cloud endpoint slow or down
  - Request times out after N seconds
  - Device announces error (not silent hang)

- [ ] **Cloud LLM conversation memory** ✓
  - Ask "What's the tallest mountain?"
  - Receive answer
  - Follow up: "What about the second?"
  - Cloud fallback remembers context and answers

- [ ] **Conversation memory expires** ⚠
  - Ask a question
  - Wait 3+ minutes
  - Ask a follow-up
  - Memory has expired; follow-up treated as independent query

### 5.5 Text-to-Speech (Piper + MMS)
- [ ] **Piper (English) quality** ✓
  - Device speaks in English
  - Voice is natural, clear, at normal speed
  - No artifacts or glitches

- [ ] **MMS (Tagalog) quality** ✓
  - Switch to Tagalog
  - Device speaks in Tagalog
  - Voice is understandable (MMS quality is lower than Piper)

- [ ] **Number rendering in Tagalog** ✓
  - Say "What time is it" (response includes time: "Ito ay 3:45 PM")
  - In Tagalog, numbers should be spelled out ("tatlo", not "3")
  - Verify the number is audible and understood

- [ ] **Very long response** ⚠
  - Ask something that generates a very long response
  - TTS renders the full text (may take 10+ seconds)
  - PTT button can interrupt mid-speech

- [ ] **Special characters in TTS input** ✗
  - Intentionally pass unicode/emoji to TTS
  - Device should handle gracefully (skip or pronounce)

- [ ] **Battery-critical warning during speech** ✓
  - Start TTS playback
  - During playback, trigger critical battery alert (5%)
  - Alarm interrupts speech immediately
  - Critical message plays

### 5.6 Voice Command Edge Cases
- [ ] **Same command twice in a row** ✓
  - Say "Turn right"
  - Say "Turn right" again
  - Both should be processed independently

- [ ] **Rapid-fire commands** ✓
  - Press PTT, say "Where am I"
  - Release, press again within 2 seconds, say "How much battery"
  - Both commands should execute in sequence (not overlap)

- [ ] **Command during startup (models loading)** ⚠
  - Within first 30 seconds after power-on (while models load)
  - Press PTT
  - Busy cue plays, command rejected
  - User told to wait

---

## 6. COMPUTER VISION

### 6.1 Object Detection (YOLO)
- [ ] **"What's around me" with clear objects** ✓
  - Say "What's around me" with a person/chair/table in view
  - Device detects and announces them
  - Accuracy and latency logged

- [ ] **"What's around me" with multiple objects** ✓
  - Scene with 3–5 objects (person, chair, bag, etc.)
  - Device lists them (not overwhelming the user with too many)

- [ ] **Camera obstruction** ⚠
  - Cover camera lens with paper
  - Say "What's around me"
  - YOLO detects nothing
  - Falls back to ultrasonic: "Something is X cm away"

- [ ] **Very dim lighting** ⚠
  - Test in dark room with minimal light
  - YOLO may not detect anything clearly
  - Graceful fallback to ultrasonic

- [ ] **Glare / backlight** ⚠
  - Bright light behind objects (e.g., window backlight)
  - YOLO may struggle with detection
  - Device still announces something (unclear but not silent)

- [ ] **Camera not detected at startup** ✗
  - Unplug camera before boot
  - Device should fail cleanly with error message
  - No silent skip or hang

### 6.2 Optical Character Recognition (OCR)
- [ ] **"Read this" with clear printed text** ✓
  - Hold printed sign in front of camera
  - Say "Read this"
  - Tesseract OCR reads and speaks text accurately

- [ ] **Handwritten text** ⚠
  - Hold handwritten note in front
  - Say "Read this"
  - Tesseract may fail or misread
  - Device acknowledges but accuracy is low

- [ ] **"Read this" in Tagalog** ✓
  - Print Tagalog text
  - Say "Read this" while in Tagalog language mode
  - Tesseract + MMS TTS reads it in Tagalog

- [ ] **Mixed language text** ⚠
  - Text with both English and Tagalog
  - Current language mode determines what's read
  - Graceful degradation if mixed

- [ ] **Text too small or far** ⚠
  - Text at 3+ meters distance (too small in camera view)
  - Tesseract fails to recognize
  - Device announces "I couldn't read that"

- [ ] **Repeat button stops OCR mid-read** ✓
  - Say "Read this"
  - Tesseract processes, TTS starts speaking
  - Press repeat button (stop) while speaking
  - Speech cuts immediately
  - Device waits for next command

- [ ] **Continuous detection during OCR** ✓
  - While OCR is processing, obstacle is detected
  - Verify fall detection and obstacle alerts still work
  - No hang or deadlock

---

## 7. COMPASS & HEADING

### 7.1 Magnetometer Calibration
- [ ] **Calibration procedure** ✓
  - Run `magnetometer_calibrate` (6-face or swing)
  - Calibration completes without errors
  - Offsets and scales are reasonable (not infinite/NaN)

- [ ] **Calibration with interference** ⚠
  - Perform calibration near metal (e.g., fence)
  - Calibration completes but quality may be degraded
  - Diagnose output (too much hard-iron offset = interference)

- [ ] **Compass stability test** ✓
  - Run `magnetometer_stability`
  - Phase 1: stationary reading drifts < 1 μT
  - Phase 2: orientation return matches within tolerance

### 7.2 Turn-to-Face Guidance
- [ ] **Turn-to-face at route start** ✓ [COMPASS_CALIBRATED = True]
  - Start navigation
  - Compass gives turn-to-face cue (motor pulses)
  - Motor side and pulse speed change as user aligns
  - When aligned within ~20°, motor stops pulsing

- [ ] **Turn-to-face with user already facing correct direction** ✓
  - Start navigation, already facing the right way
  - Compass detects alignment
  - No or minimal motor feedback

- [ ] **Turn-to-face interrupted by obstacle** ✓
  - Turn-to-face active
  - Obstacle detected and vibrates (different motors)
  - Verify both feedbacks are distinguishable

### 7.3 Heading Under Motion
- [ ] **Heading accuracy during walking** ✓
  - Walk in a straight line (as straight as possible)
  - Check that heading stays stable (drift < ±10°)

- [ ] **Heading during turns** ✓
  - Walk, then turn 90° left
  - Heading should shift by ~90°
  - Compare against phone compass

- [ ] **Heading in magnetic interference** ⚠
  - Walk near a large metal object (car, building steel frame)
  - Heading may deviate
  - Device may lose calibration temporarily
  - Should recover when interference subsides

---

## 8. POWER & BATTERY

### 8.1 Battery State Reporting
- [ ] **Battery percentage accurate** ✓
  - Check reported battery % from device
  - Plug into PC and verify against fuel gauge logic
  - Should be reasonably accurate (within ±10%)

- [ ] **Battery state transitions** ✓
  - From full to low (~15%) and critical (~5%)
  - Verify low-battery alert fires at ~15%
  - Verify critical warning fires at ~5%

- [ ] **Battery stuck at 59% (known gauge issue)** ⚠
  - If UPS HAT reads ~59%, this is the flat-battery misreading
  - Device should use cross-check (voltage) to detect
  - Low-battery alerts should not fire falsely

### 8.2 Low-Battery Alerts
- [ ] **Low-battery alert at ~15%** ✓
  - Drain battery to ~15%
  - Alert fires (spoken, not silent)
  - Alert sent to backend + SMS

- [ ] **Low-battery latch** ✓
  - Alert fires once
  - Service restarts
  - Alert does NOT fire again (latch prevents duplicate)

- [ ] **Critical battery at ~5%** ✓
  - Drain to ~5%
  - Critical warning fires (urgent announcement)
  - All three motors pulse as warning

- [ ] **Low-battery alert with no network** ⚠
  - Disconnect network
  - Drain to ~15%
  - Alert fires locally (spoken)
  - SMS and HTTP alert queued for retry

### 8.3 Power Loss & Shutdown
- [ ] **Unexpected power loss** ✗
  - Device running
  - Unplug battery
  - No data corruption on resume (check var/ files)
  - systemd clean restart on next power-on

- [ ] **Graceful shutdown** ✓
  - Say "Shut down" (or "Patayin mo ang IndepenSense")
  - Device announces confirmation request
  - Press PTT within timeout to confirm
  - Device powers off cleanly

- [ ] **Shutdown cancel** ✓
  - Initiate shutdown
  - Do NOT press PTT to confirm
  - Device cancels, remains powered on

---

## 9. GPS & POSITIONING

### 9.1 GPS Fix Acquisition
- [ ] **GPS lock outdoors (clear sky)** ✓
  - Go outdoors with clear sky view
  - Device acquires fix within 30–60 seconds
  - Fix is accurate to ±10 meters

- [ ] **GPS lock with partial sky view** ⚠
  - Urban canyon with building obstruction
  - GPS may take longer or have higher error
  - Device still acquires fix (if at all)

- [ ] **GPS indoors** ✗
  - Go indoors (away from windows)
  - GPS does not acquire fix
  - Device announces "No GPS fix"
  - Graceful degradation (navigation unavailable, but device functional)

- [ ] **GPS auto-start after reboot** ✓ [GPS_AUTOSTART enabled]
  - Reboot device
  - GPS should start automatically (if `AT+CGPSAUTO=1` is set)
  - Fix acquired without manual intervention

### 9.2 GPS During Navigation
- [ ] **Fix lost during active navigation** ⚠
  - Navigation active (route started)
  - GPS signal lost (go indoors)
  - Route tracking stops, no more turn announcements
  - Device announces "Lost GPS signal"

- [ ] **Fix recovered during route** ✓
  - GPS lost, then regained
  - Route resumes (if still on track)
  - Turn announcements resume

---

## 10. CELLULAR CONNECTIVITY & TELEMETRY

### 10.1 Cellular Signal Strength
- [ ] **Strong signal (4G/5G)** ✓
  - Check signal strength report from device
  - Say "Device status"
  - Device announces "strong, at X percent, on 4G"

- [ ] **Weak signal** ⚠
  - Move to area with weak cellular signal
  - Say "Device status"
  - Device announces "weak, at X percent, on 2G/3G"

- [ ] **No signal** ⚠
  - Area with no cellular coverage
  - Device still functions (offline mode)
  - Network-dependent features degrade gracefully

### 10.2 Telemetry Heartbeat
- [ ] **Heartbeat sent regularly** ✓
  - Device online, no events
  - Heartbeat sent every N minutes (check config)
  - Backend receives and logs

- [ ] **Heartbeat with poor signal** ⚠
  - Weak cellular signal
  - Heartbeat retries with backoff
  - Eventually sent when signal recovers

- [ ] **Heartbeat offline, then syncs** ✓
  - Device offline for 30 minutes
  - Reconnect to network
  - Queued heartbeats sent (or most recent state only)

### 10.3 Alert Delivery (Emergency, Fall, Low Battery)
- [ ] **Alert reaches backend** ✓
  - Trigger alert (emergency button)
  - HTTP POST to backend succeeds
  - Guardian dashboard receives notification

- [ ] **Alert reaches SMS** ✓
  - Trigger alert
  - SMS sent to guardian contact
  - SMS arrives within 10 seconds

- [ ] **Alert offline, then sends** ✓
  - Trigger alert while offline
  - Go online
  - Alert retries and sends

- [ ] **Multiple alerts in quick succession** ✓
  - Trigger multiple alerts (SOS, fall detection)
  - Both queued and sent
  - No race condition or dropped alerts

---

## 11. SPEAKER & AUDIO PLAYBACK

### 11.1 Audio Output Quality
- [ ] **Speech playback volume** ✓
  - Device speaks at default volume
  - Clear, audible through open-ear headphones
  - No distortion

- [ ] **Cue sounds (chimes, blips)** ✓
  - PTT chime plays
  - Stop cue plays
  - Busy cue plays
  - All distinct and audible

- [ ] **Buzzer (emergency alert)** ✓
  - Trigger SOS or fall detection
  - Buzzer sounds (loud, unmissable)
  - Distinct from cues and speech

### 11.2 Volume Control
- [ ] **"Louder" increases volume** ✓
  - Say "Louder"
  - Device announces new volume
  - Next speech is louder

- [ ] **"Quieter" decreases volume** ✓
  - Say "Quieter"
  - Device announces new volume
  - Next speech is quieter

- [ ] **Volume floor (20%)** ✓
  - Say "Quieter" repeatedly
  - Volume stops at 20%, cannot go lower
  - Critical alerts (buzzer) unaffected by volume

- [ ] **Volume ceiling (100%)** ✓
  - Say "Louder" repeatedly
  - Volume stops at 100%, cannot go higher

- [ ] **Volume persistence** ✓
  - Set volume to 50%
  - Reboot device
  - Volume is still 50% (persisted in var/volume)

### 11.3 Concurrent Audio
- [ ] **Speech + obstacle vibration** ✓
  - Device speaks turn instruction
  - Obstacle detected simultaneously
  - Speech continues uninterrupted, vibration fires
  - No audio dropout or glitch

- [ ] **Speech + cue (interrupt)** ✓
  - Device speaks response
  - User presses PTT (interrupt)
  - Speech cuts, chime plays immediately
  - No lag

---

## 12. BUTTON INTERACTIONS

### 12.1 Push-to-Talk Button
- [ ] **Normal press-release** ✓
  - Press button
  - Chime plays (low latency, < 200 ms)
  - Microphone active, recording starts
  - Release button
  - Processing starts

- [ ] **Long hold** ⚠
  - Press and hold PTT for 10+ seconds
  - Recording continues
  - Eventually times out (graceful)

- [ ] **Rapid presses** ✓
  - Press rapidly (5 times in 2 seconds)
  - Each press handled independently
  - No races or dropped presses

### 12.2 Emergency Button
- [ ] **Single press** ✓
  - Press SOS button
  - Buzzer + motors fire immediately
  - Alert sent

- [ ] **Accidental press** ✓
  - Press SOS by accident
  - Alert fires (by design, false alarms still alert guardians)
  - User can say "Cancel emergency" to stop follow-up messages

- [ ] **Held down** ⚠
  - Hold SOS button continuously for 5+ seconds
  - Alert fires once, held button does not re-trigger

### 12.3 Repeat / Stop Button
- [ ] **Replay last response** ✓
  - Device speaks a response
  - Press repeat button
  - Last response replays

- [ ] **Interrupt speech** ✓
  - Device is speaking
  - Press repeat button
  - Speech stops immediately
  - Stop cue plays (brief tone)

- [ ] **Repeat before any response** ⚠
  - Device starts, no response yet
  - Press repeat
  - Device announces "nothing to repeat"

---

## 13. LANGUAGE SWITCHING

### 13.1 Language Switching
- [ ] **Switch English → Tagalog** ✓
  - Say "Lumipat sa Tagalog" (or "Switch to Tagalog")
  - Device announces "Nagsalin kami sa Tagalog" in Tagalog
  - All subsequent responses in Tagalog

- [ ] **Switch Tagalog → English** ✓
  - Device in Tagalog mode
  - Say "Lumipat sa English"
  - Device announces "We switched to English" in English
  - All subsequent responses in English

- [ ] **Language persistence** ✓
  - Switch to Tagalog
  - Reboot device
  - Device boots in Tagalog mode (persisted)

- [ ] **Language switch clears conversation memory** ✓
  - Ask a question in English, get context
  - Switch to Tagalog
  - Follow-up question in Tagalog
  - Cloud LLM memory cleared (ask a follow-up expecting context, doesn't have it)

- [ ] **Unsupported language** ✗
  - Try to switch to unsupported language (e.g., Spanish)
  - Device responds "I don't support that language"

---

## 14. SAVED PLACES

### 14.1 Save & Retrieve
- [ ] **Save current location** ✓
  - Say "Save this place as home"
  - Device confirms: "Saved home"
  - Place recorded with GPS coordinates

- [ ] **Navigate to saved place** ✓
  - Say "Take me home"
  - Route starts immediately (no geocoding, no confirmation prompt)
  - Navigation follows saved coordinates

- [ ] **List saved places** ✓
  - Save 3 places
  - Say "What places have I saved"
  - Device lists all (reads first 6, then "and N more")

- [ ] **Saved place with variant names** ✓
  - Save place as "home"
  - Say "Take me to my home"
  - Device recognizes it (possessives ignored)
  - Say "Take me to the home"
  - Device recognizes it (articles ignored)

- [ ] **Saved places limit** ⚠
  - Save 20 places (or system limit)
  - Verify no crash or silent failure
  - List shows all (or first N with "and M more")

### 14.2 Delete & Forget
- [ ] **Delete saved place** ✓
  - Say "Forget the place saved as home"
  - Device confirms: "Forgot home"
  - Place removed from var/places.json

- [ ] **Delete nonexistent place** ✗
  - Say "Forget the place saved as xyz"
  - Device announces "I don't have a place called xyz"

---

## 15. HELP & INFORMATION

### 15.1 System Help
- [ ] **"What can you do"** ✓
  - Say "What can you do" or "Help"
  - Device speaks a summary of capabilities
  - User can learn what to ask without reading manual

- [ ] **Device status** ✓
  - Say "How much battery do I have"
  - Device announces: battery %, GPS lock status, cellular signal
  - All information is current

- [ ] **"What time is it"** ✓
  - Say "What time is it"
  - Device announces current time
  - Time is accurate (NTP synced)

---

## 16. MULTIMODAL CONCURRENCY

### 16.1 Main Loop + Background Threads
- [ ] **Fall detection while speaking** ✓
  - Device speaking (TTS output)
  - Trigger fall detection
  - Fall alarm fires immediately (not blocked by TTS)
  - User hears alarm + interruption

- [ ] **Obstacle detection while PTT active** ✓
  - User holding PTT, speaking
  - Obstacle enters detection zone
  - Main loop detects obstacle, vibration fires
  - Speech continues (recording not interrupted)

- [ ] **Navigation update while voice processing** ✓
  - Navigation active, approaching turn
  - User presses PTT with new query
  - Route continues to update
  - New query processed in parallel
  - Response plays without interfering

- [ ] **GPS update while obstacle detection** ✓
  - Active navigation, main loop polling ultrasonic
  - GPS thread updates position periodically
  - No lock contention or missed updates

### 16.2 Telemetry + Network
- [ ] **Heartbeat sent while user navigating** ✓
  - Navigation active
  - Telemetry thread sends heartbeat in background
  - Navigation unaffected

- [ ] **Alert sent while PTT active** ✓
  - User speaking (PTT held)
  - Fall detected
  - Telemetry sends alert HTTP + SMS
  - User's speech continues to record

---

## 17. FAILURE MODES & RECOVERY

### 17.1 Hardware Failures
- [ ] **Sensor unplugged mid-operation** ✗
  - Unplug ultrasonic sensor while app running
  - Device should not crash
  - Graceful degradation (obstacle detection unavailable)
  - Log the error

- [ ] **Camera unplugged** ✗
  - Unplug camera
  - If user says "What's around me", device announces camera unavailable
  - No crash

- [ ] **Microphone unplugged** ✗
  - Unplug USB headset
  - Press PTT
  - Device announces mic unavailable (busy cue or error)
  - No crash

- [ ] **Motor/buzzer wired to wrong pin** ⚠
  - Feedback may fire on wrong output
  - Log should show GPIO errors
  - Device continues running (feedback degraded but not critical)

### 17.2 Network Failures
- [ ] **Network lost during bootstrap** ✗
  - Models loading, network goes down
  - Device should not hang
  - Models load from local disk, not network (by design)

- [ ] **Network flaky during telemetry** ⚠
  - Network keeps dropping/reconnecting
  - Telemetry retries with backoff
  - No timeout hangs, device responsive

- [ ] **Backend unreachable** ⚠
  - Alert triggered, backend offline
  - Alert queued for retry
  - Device announces status (not silent)

### 17.3 Model Loading Failures
- [ ] **Whisper model corrupt** ✗
  - Corrupt Whisper model files
  - Device fails at startup with clear error (not hang)
  - Error message names the tool and file

- [ ] **Ollama not running** ⚠
  - NLU fallback: embedding fast-path works (no Ollama needed)
  - Escalated queries fail gracefully
  - Log shows Ollama connection error

- [ ] **GraphHopper or Photon offline** ⚠
  - Try to navigate
  - Device announces "Service unavailable"
  - Navigation does not start

### 17.4 Crash & Restart
- [ ] **Service crashes, systemd restarts** ✓
  - Manually kill the indepensense process
  - systemd restarts it within a few seconds
  - Boot sequence runs again
  - Device functional

- [ ] **Orphaned threads after crash** ✗
  - Crash and restart
  - Check `ps aux | grep python`
  - No orphaned processes (systemd cleans up)

---

## 18. PERFORMANCE & LATENCY

### 18.1 Real-time Response Times
- [ ] **Fall detection latency** ✓
  - Drop wearable, detect impact
  - Time from impact to alert: < 500 ms
  - Measured via logs or camera

- [ ] **Obstacle detection latency** ✓
  - Place obstacle in range
  - Time from entry to vibration: < 100 ms
  - Verify for both ultrasonic sensors

- [ ] **PTT chime latency** ✓
  - Press PTT button
  - Chime should play within 100 ms
  - No perceptible delay

- [ ] **Voice pipeline latency** ✓
  - Press PTT, say "Turn right"
  - Time from release to spoken response: 3–7 seconds
  - Run `latency_bench --repeat 10 --csv`
  - Acceptable variance

### 18.2 CPU & Memory
- [ ] **CPU usage at idle** ✓
  - Device running, no user interaction
  - CPU usage should be low (< 20%)
  - Main loop not busy-waiting

- [ ] **CPU usage during obstacle detection** ✓
  - Continuous obstacle polling
  - CPU usage acceptable (< 50%)
  - Loop can still detect falls and respond to buttons

- [ ] **Memory leaks** ✗
  - Run device for 1 hour continuously
  - Monitor memory usage
  - Should not grow unbounded
  - Check for thread leaks

### 18.3 Thermal
- [ ] **Temperature under load** ✓
  - Run device for 30+ minutes (voice, navigation)
  - Monitor CPU temperature
  - Should stay below 80°C (thermal throttle point)

---

## 19. DATA INTEGRITY & PERSISTENCE

### 19.1 State Files
- [ ] **Saved places persist** ✓
  - Save place, reboot, verify it's still there
  - Check `var/places.json` is valid JSON

- [ ] **Volume setting persists** ✓
  - Set volume to 60%, reboot, verify it's 60%
  - Check `var/volume` file

- [ ] **Language setting persists** ✓
  - Switch to Tagalog, reboot, verify it boots in Tagalog
  - Check `var/language` file

- [ ] **Alert latches persist** ✓
  - Low-battery alert fires, log latched in `var/low_battery_alerted`
  - Reboot, alert does not re-fire
  - Verify latch file exists and is respected

### 19.2 Telemetry Data
- [ ] **Heartbeat buffer** ✓
  - Device offline for 1 hour
  - Go online
  - Telemetry syncs (most recent state, not all history)

- [ ] **Alert delivery reliability** ✓
  - Trigger alert offline
  - Go online within 30 minutes
  - Alert is sent (not lost)

---

## 20. EDGE CASES & STRESS TESTS

### 20.1 Environmental Extremes
- [ ] **Direct sunlight on camera** ⚠
  - YOLO detection in bright sunlight
  - May be washed out but should not crash

- [ ] **Very cold temperature** ⚠
  - Operate device in cold (0–5°C)
  - GPS, battery, motors should still work
  - Response times may be slower but not critical

- [ ] **High humidity** ⚠
  - Operate in humid environment (rain, fog)
  - Microphone and sensors should not malfunction
  - No condensation inside enclosure

### 20.2 Extreme User Input
- [ ] **Shouting into microphone** ⚠
  - Press PTT, shout
  - Whisper transcribes (may be loud or distorted)
  - Device handles without crashing

- [ ] **Foreign language input** ⚠
  - Speak language not in training (e.g., Mandarin)
  - Whisper attempts transcription
  - Classifier escalates or fails gracefully

- [ ] **Constant speech** ⚠
  - Say "What time is it" repeatedly (100 times)
  - Device should handle (may slow down)
  - No crash or memory explosion

### 20.3 Stress Tests
- [ ] **Long continuous navigation** ✓
  - Navigate for 2+ hours
  - Verify no GPS drift, no memory leaks
  - Device responsive

- [ ] **Repeated fall detection** ✗
  - Simulate fall 20 times (drop and catch)
  - Alert sent each time (or properly de-duped)
  - No false negatives, no stuck state

- [ ] **Repeated PTT presses** ✓
  - Press PTT 50 times with short queries
  - Each processed independently
  - No thread exhaustion, no queue overflow

---

## 21. FIRST-BOOT & DEPLOYMENT

### 21.1 Fresh Device Setup
- [ ] **Factory default state** ✓
  - New device, no var/ files
  - Boot up, all defaults applied
  - Device functional immediately

- [ ] **Language on first boot** ✓
  - Fresh device boots in `DEFAULT_LANGUAGE`
  - User can switch language immediately

- [ ] **Compass not calibrated on first boot** ✓
  - `COMPASS_CALIBRATED = False`
  - Turn-to-face and heading-based features disabled
  - No errors or crashes

### 21.2 Hardware Verification Checklist
- [ ] **All manual tests pass** ✓
  - Run all manual tests from README
  - DYP-A22 (top/bottom), MPU6050, QMC5883P, GPS, UPS, camera, voice
  - Each test confirms hardware working

- [ ] **Compass calibration** ✓
  - Run magnetometer calibration (swing or 6-face)
  - Calibration succeeds
  - Set `COMPASS_CALIBRATED = True`
  - Verify headings match phone compass at 4 cardinals

---

## Summary: Test Execution Roadmap

### Phase 1: Individual Feature Tests (Day 1–2)
- Run manual tests from README (sensors, feedback, vision, voice)
- Verify each component works in isolation

### Phase 2: Integration Tests (Day 2–3)
- Full boot-to-voice sequence
- Holistic navigation flow (start → route → destination)
- Obstacle detection during active navigation
- Fall detection + alert delivery (local + network)

### Phase 3: Stress & Edge Cases (Day 3–4)
- Long-duration navigation (1–2 hours)
- Repeated user interactions (PTT, buttons)
- Network degradation scenarios
- Concurrent operations (voice + obstacles + telemetry)

### Phase 4: Real-World Scenarios (Day 4–5)
- Outdoor walk with navigation
- Obstacle avoidance in realistic environments
- Multi-language testing
- Emergency scenarios (fall, SOS, low battery)

### Phase 5: Documentation & Bug Triage
- Log all findings
- Categorize: critical (blocks use), major (degrades feature), minor (cosmetic)
- Reproduce and fix, or defer to Future Work

---

**Legend:**
- ✓ = Expected to pass as designed
- ⚠ = Graceful degradation expected (not ideal, but acceptable)
- ✗ = Failure scenario (must handle without crash or data loss)
- [Requires X] = Specific hardware/service prerequisite
