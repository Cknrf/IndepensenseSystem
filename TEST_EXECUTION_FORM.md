# IndepenSense - Test Execution Form

**Date:** ________________  
**Tester:** ________________  
**Environment:** RPi 5, Full Hardware Stack  
**Services Running:** GraphHopper ☐ Photon ☐ Ollama ☐ Cellular ☐ GPS ☐

---

## 1. SPEECH-TO-TEXT (STT) - ENGLISH

**Objective:** Validate Whisper transcription accuracy across different speech patterns.

**Test Setup:** User speaks into microphone; device records and transcribes. Tester compares actual transcript against what was spoken.

| TRIAL | PHRASE SPOKEN | EXPECTED TRANSCRIPT | ACTUAL TRANSCRIPT | MATCH? | STATUS | NOTES |
|-------|---------------|-------------------|-------------------|--------|--------|-------|
| STT-EN-001 | "Take me to Jollibee" |  |  | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |
| STT-EN-002 | "Where am I" |  |  | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |
| STT-EN-003 | "Turn right in 50 meters" |  |  | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |
| STT-EN-004 | "What time is it" |  |  | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |
| STT-EN-005 | "How much battery" |  |  | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |
| STT-EN-006 | "Cancel navigation" |  |  | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |
| STT-EN-007 | "Save this place as home" |  |  | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |
| STT-EN-008 | "Read this" |  |  | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |
| STT-EN-009 | "Help" |  |  | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |
| STT-EN-010 | "Louder" (single word) |  |  | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 10 passed  
**Notes:**

---

## 2. SPEECH-TO-TEXT (STT) - TAGALOG

**Objective:** Validate Whisper transcription in Tagalog.

| TRIAL | PHRASE SPOKEN (TAGALOG) | EXPECTED TRANSCRIPT | ACTUAL TRANSCRIPT | MATCH? | STATUS | NOTES |
|-------|-------------------------|-------------------|-------------------|--------|--------|-------|
| STT-TL-001 | "Dalhin mo ako sa Jollibee" |  |  | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |
| STT-TL-002 | "Nasaan ako" |  |  | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |
| STT-TL-003 | "Lumipat sa English" |  |  | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |
| STT-TL-004 | "Ano ang oras" |  |  | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |
| STT-TL-005 | "I-save ang lugar na ito bilang bahay" |  |  | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 5 passed

---

## 3. INTENT CLASSIFICATION - NLU (English)

**Objective:** Test that each voice intent is correctly classified.

**Instructions:** Press PTT, speak the phrase, release. Device should execute the intent. Log which intent fired.

| TRIAL | INTENT | EXAMPLE PHRASE | EXPECTED RESULT | ACTUAL RESULT | CORRECT? | STATUS | NOTES |
|-------|--------|---|---|---|---|---|---|
| NLU-EN-001 | navigation.start | "Take me to McDonald's" | Route starts, destination read back, waits for confirm | | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |
| NLU-EN-002 | navigation.start (alt) | "Navigate to the nearest Jollibee" | Route starts, destination read back | | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |
| NLU-EN-003 | navigation.stop | "Cancel navigation" | Active route cancels, "cancelled" announced | | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |
| NLU-EN-004 | navigation.location | "Where am I" | Current location announced | | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |
| NLU-EN-005 | navigation.progress | "How much further" | Distance to destination announced | | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |
| NLU-EN-006 | place.save | "Save this place as home" | Device confirms save, "saved home" announced | | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |
| NLU-EN-007 | place.locate | "What is the exact location of my home" | Coordinates + distance announced | | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |
| NLU-EN-008 | place.list | "What places have I saved" | List of saved places announced | | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |
| NLU-EN-009 | place.delete | "Forget the place saved as home" | Confirmation, "forgot home" announced | | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |
| NLU-EN-010 | vision.describe | "What's around me" | Camera captures, objects described, or ultrasonic fallback | | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |
| NLU-EN-011 | vision.read | "Read this" | OCR runs, text read aloud | | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |
| NLU-EN-012 | device.status | "How much battery do I have" | Battery %, GPS, cellular signal announced | | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |
| NLU-EN-013 | system.time | "What time is it" | Current time announced | | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |
| NLU-EN-014 | system.volume | "Louder" | Volume increases, new level announced | | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |
| NLU-EN-015 | system.volume (alt) | "Set volume to 60 percent" | Volume set to 60%, confirmed | | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |
| NLU-EN-016 | system.language | "Switch to Tagalog" | Language switches, confirmation in Tagalog | | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |
| NLU-EN-017 | system.help | "What can you do" | Help message spoken | | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |
| NLU-EN-018 | system.shutdown | "Shut down" | Confirmation prompt, waits for PTT press | | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |
| NLU-EN-019 | emergency.trigger | "Help" | Buzzer + motors fire, alert sent to backend | | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |
| NLU-EN-020 | unknown (cloud fallback) | "How does photosynthesis work" | Escalates to cloud LLM, receives answer | | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 20 passed

---

## 4. INTENT CLASSIFICATION - NLU (Tagalog)

**Objective:** Test Tagalog intents.

| TRIAL | INTENT | EXAMPLE PHRASE (TAGALOG) | EXPECTED RESULT | ACTUAL RESULT | CORRECT? | STATUS | NOTES |
|-------|--------|---|---|---|---|---|---|
| NLU-TL-001 | navigation.start | "Dalhin mo ako sa Jollibee" | Route starts, destination read back | | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |
| NLU-TL-002 | navigation.stop | "Kanselahin ang navigation" | Route cancels | | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |
| NLU-TL-003 | navigation.location | "Nasaan ako" | Current location announced in Tagalog | | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |
| NLU-TL-004 | place.save | "I-save ang lugar na ito bilang bahay" | Place saved with Tagalog name | | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |
| NLU-TL-005 | system.language | "Lumipat sa English" | Switches to English, confirmation in English | | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |
| NLU-TL-006 | emergency.trigger | "Tulong" | Buzzer + motors fire, alert sent | | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 6 passed

---

## 5. BUTTON FUNCTIONALITY

**Objective:** Validate all three buttons work correctly and respond immediately.

### 5.1 Push-to-Talk (PTT) Button

| TRIAL | ACTION | EXPECTED BEHAVIOR | ACTUAL BEHAVIOR | STATUS | NOTES |
|-------|--------|---|---|---|---|
| BTN-PTT-001 | Press PTT | Chime plays within 150 ms | | ☐ PASS ☐ FAIL |  |
| BTN-PTT-002 | Press + hold PTT | Microphone records, indicator shows | | ☐ PASS ☐ FAIL |  |
| BTN-PTT-003 | Release PTT after speaking | Processing starts, "working blip" plays if >1.5s | | ☐ PASS ☐ FAIL |  |
| BTN-PTT-004 | Press PTT during device speech | Speech cuts, chime plays, recording starts | | ☐ PASS ☐ FAIL |  |
| BTN-PTT-005 | Rapid PTT presses (5 in 2s) | Each chime plays, no errors | | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 5 passed

### 5.2 Emergency (SOS) Button

| TRIAL | ACTION | EXPECTED BEHAVIOR | ACTUAL BEHAVIOR | STATUS | NOTES |
|-------|--------|---|---|---|---|
| BTN-SOS-001 | Press SOS button | Buzzer sounds immediately (loud) | | ☐ PASS ☐ FAIL |  |
| BTN-SOS-002 | SOS pressed | All three motors pulse together (danger pattern) | | ☐ PASS ☐ FAIL |  |
| BTN-SOS-003 | SOS pressed | "Emergency alert" announced | | ☐ PASS ☐ FAIL |  |
| BTN-SOS-004 | SOS pressed | Backend receives alert via HTTP | | ☐ PASS ☐ FAIL | Check backend logs |
| BTN-SOS-005 | SOS pressed | SMS sent to guardian(s) | | ☐ PASS ☐ FAIL | Check phone |
| BTN-SOS-006 | SOS double-press within 10s | Buzzer sounds twice, but only ONE alert sent | | ☐ PASS ☐ FAIL | Check backend, should see 1 event |
| BTN-SOS-007 | SOS pressed during PTT | PTT cancels, SOS alert fires immediately | | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 7 passed

### 5.3 Repeat / Stop Button

| TRIAL | ACTION | EXPECTED BEHAVIOR | ACTUAL BEHAVIOR | STATUS | NOTES |
|-------|--------|---|---|---|---|
| BTN-REP-001 | Press after device speaks | Last response replays | | ☐ PASS ☐ FAIL |  |
| BTN-REP-002 | Press during device speech | Speech cuts, "stop cue" tone plays | | ☐ PASS ☐ FAIL |  |
| BTN-REP-003 | Press before any response | "Nothing to repeat" announced | | ☐ PASS ☐ FAIL |  |
| BTN-REP-004 | Press at confirmation prompt | Counts as "no" / reject | | ☐ PASS ☐ FAIL | During "confirm destination" |
| BTN-REP-005 | Rapid repeat presses | Each press handled independently | | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 5 passed

---

## 6. OBSTACLE DETECTION & HAPTIC FEEDBACK

**Objective:** Validate ultrasonic sensors detect obstacles and trigger correct vibration patterns.

**Setup:** Place obstacles at measured distances. Use a ruler or tape measure to confirm distance.

### 6.1 Top Sensor (Head Height)

| TRIAL | DISTANCE | EXPECTED | ACTUAL | DEVIATION | STATUS | NOTES |
|-------|----------|----------|--------|-----------|--------|-------|
| OBS-TOP-001 | 30 cm | Reading: 30±5 cm | | | ☐ PASS ☐ FAIL |  |
| OBS-TOP-002 | 50 cm | Reading: 50±5 cm | | | ☐ PASS ☐ FAIL |  |
| OBS-TOP-003 | 75 cm | Reading: 75±5 cm | | | ☐ PASS ☐ FAIL |  |
| OBS-TOP-004 | 100 cm | Reading: 100±5 cm | | | ☐ PASS ☐ FAIL |  |
| OBS-TOP-005 | 150 cm | Reading: 150±5 cm | | | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 5 passed

### 6.2 Haptic Feedback Tiers (Top Sensor)

| TRIAL | DISTANCE & DIRECTION | EXPECTED FEEDBACK | ACTUAL FEEDBACK | CORRECT? | STATUS | NOTES |
|-------|---|---|---|---|---|---|
| OBS-TIER-001 | 30 cm, front | All three motors pulse (danger) | | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |
| OBS-TIER-002 | 50 cm, left | Left motor vibrates (warning tier) | | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |
| OBS-TIER-003 | 75 cm, right | Right motor vibrates (warning tier) | | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |
| OBS-TIER-004 | 120 cm, front | Front motor light vibration (far tier) | | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |
| OBS-TIER-005 | Move obstacle away (exit zone) | Vibration stops, no repeat | | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |
| OBS-TIER-006 | Move obstacle back (re-enter) | Vibration fires again (hysteresis reset) | | ☐ Yes ☐ No | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 6 passed

### 6.3 Bottom Sensor (Shin Level)

| TRIAL | DISTANCE | EXPECTED | ACTUAL | DEVIATION | STATUS | NOTES |
|-------|----------|----------|--------|-----------|--------|-------|
| OBS-BOT-001 | 20 cm | Reading: 20±5 cm | | | ☐ PASS ☐ FAIL |  |
| OBS-BOT-002 | 40 cm | Reading: 40±5 cm, warning vibration | | | ☐ PASS ☐ FAIL |  |
| OBS-BOT-003 | 70 cm | Reading: 70±5 cm | | | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 3 passed

---

## 7. FALL DETECTION

**Objective:** Validate fall detection triggers alarm correctly.

| TRIAL | ACTION | EXPECTED | ACTUAL | STATUS | NOTES |
|-------|--------|----------|--------|--------|-------|
| FALL-001 | Drop wearable from 1m onto foam mat | Buzzer fires within 500ms | | ☐ PASS ☐ FAIL | Time from impact to buzzer: ___ ms |
| FALL-002 | Buzzer + motors fire together | All three motors pulse (danger) | | ☐ PASS ☐ FAIL |  |
| FALL-003 | Device announces "Fall detected" | Spoken aloud | | ☐ PASS ☐ FAIL |  |
| FALL-004 | Backend receives alert | HTTP POST logged | | ☐ PASS ☐ FAIL | Check backend |
| FALL-005 | SMS sent to guardian | Guardian receives SMS | | ☐ PASS ☐ FAIL |  |
| FALL-006 | Normal activity (jumping) | No false alert | | ☐ PASS ☐ FAIL |  |
| FALL-007 | Stair descent | No false alert | | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 7 passed

---

## 8. NAVIGATION FLOW

**Objective:** Test end-to-end navigation from destination entry to arrival.

### 8.1 Start Navigation

| TRIAL | ACTION | EXPECTED | ACTUAL | STATUS | NOTES |
|-------|--------|----------|--------|--------|-------|
| NAV-START-001 | Say "Take me to [landmark]" | Device asks for confirmation, reads back destination | | ☐ PASS ☐ FAIL |  |
| NAV-START-002 | Press PTT to confirm | Route starts, "heading [direction]" announced | | ☐ PASS ☐ FAIL |  |
| NAV-START-003 | Say "Take me home" (saved place) | Route starts immediately (no geocoding) | | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 3 passed

### 8.2 Turn-by-Turn Guidance

| TRIAL | ACTION | EXPECTED | ACTUAL | STATUS | NOTES |
|-------|--------|----------|--------|--------|-------|
| NAV-TURN-001 | Approach first turn | "Turn [left/right] in 50 meters" announced in advance | | ☐ PASS ☐ FAIL | Distance before turn: ___ m |
| NAV-TURN-002 | Complete turn | "Continue straight" announced, turn acknowledged | | ☐ PASS ☐ FAIL |  |
| NAV-TURN-003 | Reach destination | "You have arrived" announced | | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 3 passed

### 8.3 Off-Route Detection

| TRIAL | ACTION | EXPECTED | ACTUAL | STATUS | NOTES |
|-------|--------|----------|--------|--------|-------|
| NAV-OFFROUTE-001 | Miss a turn, walk straight | "You are off route" announced within 15–30s | | ☐ PASS ☐ FAIL | Time to alert: ___ s |
| NAV-OFFROUTE-002 | Backtrack 20m | Off-route alert fires | | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 2 passed

---

## 9. COMPUTER VISION

### 9.1 Object Detection (YOLO)

| TRIAL | SCENE | OBJECTS PRESENT | EXPECTED | ACTUAL | DETECTED? | STATUS | NOTES |
|-------|-------|---|---|---|---|---|---|
| YOLO-001 | Indoor hallway | Person + door | "Person and door" announced | | ☐ Yes ☐ Partial ☐ No | ☐ PASS ☐ FAIL |  |
| YOLO-002 | Outdoor street | Car + person + building | All three detected | | ☐ Yes ☐ Partial ☐ No | ☐ PASS ☐ FAIL |  |
| YOLO-003 | Dim lighting | Chair + table | Objects detected or ultrasonic fallback | | ☐ Yes ☐ Fallback ☐ No | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 3 passed

### 9.2 Optical Character Recognition (OCR)

| TRIAL | TEXT SAMPLE | LANGUAGE | EXPECTED | ACTUAL | ACCURACY | STATUS | NOTES |
|-------|---|---|---|---|---|---|---|
| OCR-001 | "Emergency Exit" (large print) | English | Perfect read | | ____% | ☐ PASS ☐ FAIL |  |
| OCR-002 | Menu text (small print) | English | Most words readable | | ____% | ☐ PASS ☐ FAIL |  |
| OCR-003 | Tagalog text (printed) | Tagalog | Readable (MMS quality may be lower) | | ____% | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 3 passed

---

## 10. BATTERY & POWER

| TRIAL | ACTION | EXPECTED | ACTUAL | STATUS | NOTES |
|-------|--------|----------|--------|--------|-------|
| PWR-001 | Say "How much battery" | Percentage announced | | ☐ PASS ☐ FAIL |  |
| PWR-002 | Drain to ~15% | Low-battery alert fires, "low battery" announced | | ☐ PASS ☐ FAIL |  |
| PWR-003 | Low-battery alert | SMS sent to guardian(s) | | ☐ PASS ☐ FAIL | Check phone |
| PWR-004 | Reboot after low-battery alert | Alert does NOT repeat (latch working) | | ☐ PASS ☐ FAIL |  |
| PWR-005 | Drain to ~5% | Critical warning fires, urgent announcement | | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 5 passed

---

## 11. GPS & POSITIONING

| TRIAL | CONDITION | EXPECTED | ACTUAL | STATUS | NOTES |
|-------|-----------|----------|--------|--------|-------|
| GPS-001 | Outdoors, clear sky | GPS fix within 60s | Time to fix: ___s | ☐ PASS ☐ FAIL |  |
| GPS-002 | Say "Where am I" | Current location announced (geocoded) | | ☐ PASS ☐ FAIL |  |
| GPS-003 | Indoors (window nearby) | GPS unavailable, graceful announcement | | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 3 passed

---

## 12. LANGUAGE SWITCHING

| TRIAL | ACTION | EXPECTED | ACTUAL | STATUS | NOTES |
|-------|--------|----------|--------|--------|-------|
| LANG-001 | Say "Switch to Tagalog" | Confirms in Tagalog: "Nagsalin kami sa Tagalog" | | ☐ PASS ☐ FAIL |  |
| LANG-002 | All subsequent responses | Spoken in Tagalog | | ☐ PASS ☐ FAIL |  |
| LANG-003 | Say "Lumipat sa English" | Confirms in English: "We switched to English" | | ☐ PASS ☐ FAIL |  |
| LANG-004 | Reboot device | Language persists (still Tagalog or English) | | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 4 passed

---

## 13. SAVED PLACES

| TRIAL | ACTION | EXPECTED | ACTUAL | STATUS | NOTES |
|-------|--------|----------|--------|--------|-------|
| PLACE-001 | Say "Save this place as home" | "Saved home" announced | | ☐ PASS ☐ FAIL |  |
| PLACE-002 | Say "Save this place as work" | "Saved work" announced | | ☐ PASS ☐ FAIL |  |
| PLACE-003 | Say "What places have I saved" | "Home, work, ..." announced | | ☐ PASS ☐ FAIL |  |
| PLACE-004 | Say "Take me home" | Route starts to saved home location | | ☐ PASS ☐ FAIL |  |
| PLACE-005 | Say "Forget the place saved as home" | "Forgot home" announced | | ☐ PASS ☐ FAIL |  |

**Summary:** ___ / 5 passed

---

## FINAL SUMMARY

| CATEGORY | PASSED | TOTAL | % |
|----------|--------|-------|---|
| STT English | ___ | 10 | ___% |
| STT Tagalog | ___ | 5 | ___% |
| NLU English | ___ | 20 | ___% |
| NLU Tagalog | ___ | 6 | ___% |
| Buttons (PTT) | ___ | 5 | ___% |
| Buttons (SOS) | ___ | 7 | ___% |
| Buttons (Repeat) | ___ | 5 | ___% |
| Obstacle Detection | ___ | 14 | ___% |
| Fall Detection | ___ | 7 | ___% |
| Navigation | ___ | 8 | ___% |
| Vision (YOLO) | ___ | 3 | ___% |
| Vision (OCR) | ___ | 3 | ___% |
| Battery & Power | ___ | 5 | ___% |
| GPS | ___ | 3 | ___% |
| Language | ___ | 4 | ___% |
| Saved Places | ___ | 5 | ___% |
| **TOTAL** | **___** | **120** | **___% ** |

---

## ISSUES & ANOMALIES FOUND

| ISSUE # | CATEGORY | DESCRIPTION | SEVERITY | NOTES |
|---------|----------|---|---|---|
| 1 |  |  | ☐ Critical ☐ Major ☐ Minor |  |
| 2 |  |  | ☐ Critical ☐ Major ☐ Minor |  |
| 3 |  |  | ☐ Critical ☐ Major ☐ Minor |  |

---

## TESTER SIGN-OFF

**Date Completed:** ________________

**Tester Name:** ________________  
**Signature:** ________________

**Reviewed By:** ________________  
**Signature:** ________________

---

**Notes / Recommendations:**

