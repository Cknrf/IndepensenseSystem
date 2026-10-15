# IndepenSense — Program Flowcharts

How the wearable runtime (`src/indepensense/app.py`) behaves, from power-on to shutdown.

## How to read these

The program is **not one linear sequence**. A 100 Hz sensor loop runs continuously while button presses, the voice pipeline and several background workers run beside it (see the concurrency model at the top of `app.py`). A single flowchart cannot show that without either hiding the concurrency or becoming unreadable. The charts are therefore **levelled**: one main program that calls sub-processes, which in turn call their own.

The charts are linked by the **predefined process** symbol (ISO 5807), drawn as a box with double vertical edges, `[[ ]]`. It means "run the process defined in the chart with this name, then continue from here". Three rules make every link unambiguous:

1. **The calling box carries the sub-chart's number and name**, e.g. `2.1 Fall detection` inside chart 2.
2. **The sub-chart's first symbol is a terminator with the same number and name.** It does not start with a generic "Start".
3. **The sub-chart ends in `Return`**, which hands control back to the box that called it. Only the main program (chart 0) has a true `End`.
4. **Every chart has a single entry and a single exit.** All paths converge on one exit terminator. A failure leads to its own step first, then joins that exit, rather than ending on a terminator of its own.

The whole program therefore has exactly one **Start** (power on) and one **End**, both in chart 0. The terminators in the sub-charts are not starts and ends: they mark where control enters the sub-process and where it returns to its caller.

The numbering is decimal by level, so a chart's number names its caller: **2.1** is called from **2**, and **3.2.1** from **3.2**. Two charts are shared and called from several places, so they sit at level 1 rather than under one parent. **4 Emergency alert** is started by the button, a fall, or a voice command. **6 Speech output** is used by everything that speaks.

Every chart is titled with its number and feature, and each section names the function in the code that implements it.

| Symbol | Meaning |
|---|---|
| Rounded ends | Terminator: the program's start/end, a sub-chart's entry, or `Return` |
| Rectangle | Process step |
| Diamond | Decision |
| Parallelogram | Input / output: sensor read, tone, button wait, network |
| Double-edged rectangle | Predefined process: call the chart with this number |
| Dotted arrow | Starts a separate thread, or calls a shared chart |

Thresholds shown are the current `config.py` values.

---

## Call hierarchy

Which chart calls which. Solid arrows run from a parent to its own sub-charts. Dotted arrows are calls into a shared chart, or the start of a new thread.

```mermaid
---
title: IndepenSense call hierarchy
---
flowchart TD
    M["0 Main program"]
    M --> C1[["1 Startup"]]
    C1 -.->|"new thread"| C11[["1.1 Voice-stack loader"]]
    M --> C2[["2 Main loop"]]
    C2 --> C21[["2.1 Fall detection"]]
    C2 --> C22[["2.2 Obstacle feedback"]]
    C2 --> C23[["2.3 Battery check"]]
    C2 --> C24[["2.4 Route monitoring"]]
    M --> C3[["3 Voice command"]]
    C3 --> C31[["3.1 Intent parsing"]]
    C3 --> C32[["3.2 Intent execution"]]
    C32 --> C321[["3.2.1 Start navigation"]]
    C3 --> C33[["3.3 Turn-to-face"]]
    M --> C4[["4 Emergency alert"]]
    C4 --> C41[["4.1 Alert delivery"]]
    M --> C5[["5 Repeat / stop"]]
    C21 -.-> C4
    C32 -.-> C4
    C23 -.-> C41
    C6[["6 Speech output<br/>(shared: called by every chart that speaks)"]]
```

| Chart | Implemented in | Called by | Calls |
|---|---|---|---|
| [0 Main program](#0-main-program) | `app.py`: `run_app()` | — | 1, 2, 3, 4, 5 |
| [1 Startup](#1-startup) | `app.py`: `App.start()` | 0 | 1.1 (new thread) |
| [1.1 Voice-stack loader](#11-voice-stack-loader) | `app.py`: `App._load_voice_stack()` | 1 | 6 |
| [2 Main loop](#2-main-loop) | `app.py`: `App.run()` | 0 | 2.1, 2.2, 2.3, 2.4 |
| [2.1 Fall detection](#21-fall-detection) | `safety/fall_detector.py`: `ThresholdFallDetector.process()` | 2 | 4 |
| [2.2 Obstacle feedback](#22-obstacle-feedback) | `app.py`: `App._check_obstacle_sensor()`, `App._tick_obstacle_rhythm()` | 2 | — |
| [2.3 Battery check](#23-battery-check) | `app.py`: `App._check_battery_and_alert()` | 2 | 4.1, 6 |
| [2.4 Route monitoring](#24-route-monitoring) | `app.py`: `App._check_navigation()` → `navigation/monitor.py`: `NavigationMonitor.check()` | 2 | 6 |
| [3 Voice command](#3-voice-command) | `app.py`: `App._on_ptt_press()` → `App._voice_pipeline()` | 0 | 3.1, 3.2, 3.3, 6 |
| [3.1 Intent parsing](#31-intent-parsing) | `intents/tiered.py`: `TieredIntentParser.parse()` | 3 | — |
| [3.2 Intent execution](#32-intent-execution) | `intents/executor.py`: `IntentExecutor.execute()` | 3 | 3.2.1, 4 |
| [3.2.1 Start navigation](#321-start-navigation) | `intents/executor.py`: `IntentExecutor._handle_navigation_start()` | 3.2 | 6 |
| [3.3 Turn-to-face](#33-turn-to-face) | `app.py`: `App._orient_towards_route()` | 3 | 6 |
| [4 Emergency alert](#4-emergency-alert) | `app.py`: `App._on_emergency_press()`, `App._on_fall_detected()`; `intents/executor.py`: `IntentExecutor._handle_emergency_trigger()` | 0, 2.1, 3.2 | 4.1, 6 |
| [4.1 Alert delivery](#41-alert-delivery) | `telemetry/sms_alerts.py`: `SMSAlertNotifier.send_alert()` | 4, 2.3 | — |
| [5 Repeat / stop](#5-repeat--stop) | `app.py`: `App._on_repeat_press()` | 0 | 6 |
| [6 Speech output](#6-speech-output) | `app.py`: `App._announce()` → `Announcer`, `App._play_clip()`, `App._clip_for_text()` | 1.1, 2.3, 2.4, 3, 3.2.1, 3.3, 4, 5 | — |

---

## 0 Main program

**Implemented in:** `app.py`: `run_app()`, which calls `App.start()` and then `App.run()`.

The whole program on one page. After startup, the main loop and the button handlers run at the same time. The buttons are gpiozero callbacks, so a press never waits for the loop.

```mermaid
---
title: 0 Main program
---
flowchart TD
    A(["Start: power on"]) --> B["systemd starts indepensense.service"]
    B --> C[["1 Startup"]]
    C --> D{"Startup succeeded?"}
    D -->|"no: IMU missing"| E["Exit code non-zero<br/>(systemd restarts the service in 5 s)"]
    D -->|"yes"| F["Background workers already running:<br/>GPS cache 1 Hz · heartbeat every 30 s ·<br/>telemetry retry · speech announcer"]

    F --> G[["2 Main loop"]]
    F --> P[/"Wait for a button press"/]

    P --> Q{"Which button?"}
    Q -->|"Push-to-talk"| R[["3 Voice command"]]
    Q -->|"Emergency"| S[["4 Emergency alert<br/>(source: button)"]]
    Q -->|"Repeat"| T[["5 Repeat / stop"]]
    R --> P
    S --> P
    T --> P
    P -.->|"on shutdown:<br/>buttons are closed"| Y

    G --> X["Main loop returned: shutdown requested<br/>(SIGTERM, a voice command, or a flat battery)"]
    X --> Y["Drain telemetry queue, stop threads,<br/>motors off, close every device"]
    Y --> Z(["End"])
    E --> Z
```

---

## 1 Startup

**Implemented in:** `app.py`: `App.start()`.

Opens only what fall detection, obstacle warnings and the emergency alert need, then returns. The models take about 200 s to load from the SD card and none of the safety features needs them, so they load on a separate thread (1.1) while the main loop is already running.

```mermaid
---
title: 1 Startup
---
flowchart TD
    A(["1 Startup"]) --> B[/"Play 'starting' clip<br/>(if rendered on a previous boot)"/]
    B --> C["Open IMU (MPU6050)"]
    C --> C1{"IMU opened?"}
    C1 -->|"no"| C2["Startup failed"]
    C2 --> R
    C1 -->|"yes"| D["Create fall detector and walking detector"]
    D --> E["Start GPS cache thread · open volume ·<br/>start announcer (no voice yet)"]
    E --> F["Connect cloud answerer, GraphHopper, Photon;<br/>load saved places"]
    F --> G{"Device credential valid?"}
    G -->|"yes"| G1["Backend telemetry client"]
    G -->|"no"| G2["Null client (SMS only)"]
    G1 --> H
    G2 --> H["Buffered telemetry + guardian list + SMS sender<br/>→ one alert path"]
    H --> I["Build intent executor"]
    I --> J["Open buttons, buzzer, 3 motors, 2 ultrasonics,<br/>UPS HAT, compass (each optional)"]
    J --> K["Start heartbeat sender"]
    K --> L["Start the voice-stack thread"]
    L -.->|"runs in parallel"| L1[["1.1 Voice-stack loader"]]
    L --> R(["Return"])
```

### 1.1 Voice-stack loader

**Implemented in:** `app.py`: `App._load_voice_stack()` → `App._load_voice_stack_once()` → `App._warm_up_nlu()`.

Runs on its own thread. If the models cannot be loaded, the device stays up in safety-only mode instead of crashing. A crash would trigger a systemd restart loop, which would take fall detection down with it.

```mermaid
---
title: 1.1 Voice-stack loader
---
flowchart TD
    A(["1.1 Voice-stack loader"]) --> B["Load Whisper speech-to-text"]
    B --> C["Load TTS voices; attach them to the announcer"]
    C --> D["Build intent parser<br/>(embedding model + LLM clients)"]
    D --> E["Open camera, YOLO, OCR (each optional)"]
    E --> F["Render boot clips; sweep clip and recording caches"]
    F --> G{"Loaded without error?"}
    G -->|"no"| H{"Attempts left?<br/>(3 in total)"}
    H -->|"yes"| B
    H -->|"no"| I["Report READY (degraded) to systemd"]
    I --> I1[["6 Speech output:<br/>'voice commands unavailable'"]]
    I1 --> J["Safety-only mode"]
    G -->|"yes"| K["Report READY to systemd<br/>(GraphHopper and Photon start after this)"]
    K --> L["Warm up the local LLM"]
    L --> M[["6 Speech output:<br/>greeting and battery level"]]
    M --> M1["Voice commands ready"]
    J --> N(["Return (thread ends)"])
    M1 --> N
```

---

## 2 Main loop

**Implemented in:** `app.py`: `App.run()`.

Runs 100 times a second until shutdown. Nothing here may block: any speech goes to the announcer queue (6), and motor pulses run on their own short-lived threads.

```mermaid
---
title: 2 Main loop
---
flowchart TD
    A(["2 Main loop"]) --> B{"Shutdown requested?"}
    B -->|"yes"| Z(["Return"])
    B -->|"no"| C[/"Read IMU"/]
    C --> D[["2.1 Fall detection"]]
    D --> E["Update walking / still classifier"]
    E --> F[/"Read TOP and BOTTOM ultrasonic sensors"/]
    F --> G[["2.2 Obstacle feedback"]]
    G --> H[["2.3 Battery check"]]
    H --> I{"Navigating, and 1 s<br/>since the last check?"}
    I -->|"yes"| J[["2.4 Route monitoring"]]
    I -->|"no"| K
    J --> K[/"Read compass (every 0.5 s)"/]
    K --> L["Wait 10 ms"]
    L --> B
```

### 2.1 Fall detection

**Implemented in:** `safety/fall_detector.py`: `ThresholdFallDetector.process()`; a confirmed fall is handled by `app.py`: `App._on_fall_detected()`.

A state machine that takes one IMU sample per tick. A fall is confirmed by either of two routes: **free-fall then impact**, or a **hard impact followed by a large change in posture**. The second route catches falls that have no clean free-fall phase.

```mermaid
---
title: 2.1 Fall detection
---
flowchart TD
    A(["2.1 Fall detection"]) --> B["Compute acceleration magnitude;<br/>add to the 2 s posture buffer"]
    B --> C{"Current state?"}

    C -->|"Idle"| D{"Below 0.5 g<br/>for at least 0.1 s?"}
    D -->|"yes"| D1["→ Post-free-fall"]
    D -->|"no"| D2{"Above 3.0 g?"}
    D2 -->|"yes"| D3["→ Post-impact (posture route)"]
    D2 -->|"no"| R

    C -->|"Post-free-fall"| E{"Above 2.0 g<br/>within 0.5 s?"}
    E -->|"yes"| E1["→ Post-impact (free-fall route)"]
    E -->|"window expired"| E2["→ Idle"]
    E -->|"still waiting"| R

    C -->|"Post-impact"| F{"Still for 2 s?<br/>(std dev below 0.15 g)"}
    F -->|"not yet"| F1{"10 s since impact?"}
    F1 -->|"yes"| E2
    F1 -->|"no"| R
    F -->|"yes"| G{"Came by the<br/>free-fall route?"}
    G -->|"yes"| H["Fall confirmed"]
    G -->|"no"| G1{"Body tilted at least 50°<br/>from before the impact?"}
    G1 -->|"yes"| H
    G1 -->|"no: sat down hard"| E2

    H --> I[["4 Emergency alert<br/>(source: fall)"]]
    D1 --> R
    D3 --> R
    E1 --> R
    E2 --> R
    I --> R(["Return"])
```

### 2.2 Obstacle feedback

**Implemented in:** `app.py`: `App._check_obstacle_sensor()` (once per sensor), then `App._tick_obstacle_rhythm()`, which uses `_obstacle_feedback()`.

Feedback is haptic only; the buzzer is reserved for emergencies. The three motors share one handle and feel like a single vibrator, so distance is expressed as **pulse rate and strength**, never as direction.

```mermaid
---
title: 2.2 Obstacle feedback
---
flowchart TD
    A(["2.2 Obstacle feedback"]) --> B{"New frame from either sensor?<br/>(each emits about 10 Hz)"}
    B -->|"no"| C
    B -->|"yes"| B1["Cache distance + time;<br/>add to recent readings;<br/>update tier with hysteresis (logged)"]
    B1 --> C{"Is the user walking?"}
    C -->|"no: standing still"| X["Stop rhythm"]
    C -->|"yes"| D{"Closest fresh obstacle<br/>within 200 cm?"}
    D -->|"no"| X
    D -->|"yes"| E["Median of recent readings →<br/>pulse rate 8–40 Hz, strength 50–100%"]
    E --> F{"Next pulse due?"}
    F -->|"no"| Z
    F -->|"yes"| G[/"Pulse all three motors<br/>(own thread; skipped if a haptic is already playing)"/]
    G --> Z(["Return"])
    X --> Z
```

### 2.3 Battery check

**Implemented in:** `app.py`: `App._check_battery_and_alert()`; the power-off tier hands over to `App._begin_low_battery_shutdown()`.

There are three tiers, each with its own latch, so a level hovering at a threshold does not repeat the warning. The low and critical latches are saved to disk, so a reboot does not re-warn about the same discharge.

```mermaid
---
title: 2.3 Battery check
---
flowchart TD
    A(["2.3 Battery check"]) --> A1{"10 s since the last check?"}
    A1 -->|"no"| Z(["Return"])
    A1 -->|"yes"| B[/"Read UPS HAT: percentage,<br/>cell voltages, charging state"/]

    B --> C{"30% or less, discharging,<br/>not yet warned?"}
    C -->|"yes"| C1[["4.1 Alert delivery<br/>(LOW_BATTERY)"]]
    C1 --> C2[["6 Speech output: 'battery low'"]]
    C -->|"no"| D
    C2 --> D{"20% or less, or a cell below 3.15 V,<br/>not yet warned?"}
    D -->|"yes"| D1[["6 Speech output:<br/>critical warning (interrupts)"]]
    D -->|"no"| E
    D1 --> E{"5% or less, or a cell below 3.15 V?"}
    E -->|"no"| Z
    E -->|"yes"| F[["6 Speech output: 'shutting down'"]]
    F --> G[["4.1 Alert delivery<br/>(LOW_BATTERY)"]]
    G --> H["Wait up to 20 s for the sentence; sync disk;<br/>power off → SIGTERM ends chart 2"]
    H --> Z
```

### 2.4 Route monitoring

**Implemented in:** `app.py`: `App._check_navigation()` → `navigation/monitor.py`: `NavigationMonitor.check()`; cues are spoken by `App._fire_navigation_cue()`.

Polled about once a second while a route is active. There is **no automatic reroute**: leaving the route produces a spoken warning only.

```mermaid
---
title: 2.4 Route monitoring
---
flowchart TD
    A(["2.4 Route monitoring"]) --> K[/"Latest GPS fix"/]
    K --> L{"Within 15 m of destination?"}
    L -->|"yes"| L1["End navigation"]
    L1 --> L2[["6 Speech output: 'you have arrived'"]]
    L2 --> Z(["Return"])
    L -->|"no"| M{"More than 30 m off route<br/>for 15 s?"}
    M -->|"yes"| M1["Cue: off-route warning"]
    M -->|"no"| N{"Compass says the turn<br/>was missed?"}
    N -->|"yes"| N1["Cue: repeat the instruction"]
    N -->|"no"| O{"Distance to next turn?"}
    O -->|"≤ 100 m"| O1["Cue: 'In N metres, turn …'"]
    O -->|"≤ 20 m"| O2["Cue: 'Turn left / right now'"]
    O -->|"farther"| Z
    M1 --> P
    N1 --> P
    O1 --> P
    O2 --> P{"Voice command in progress?"}
    P -->|"yes"| P1["Defer: offer the cue again<br/>on the next poll"]
    P -->|"no"| P2[["6 Speech output: the cue"]]
    P1 --> Z
    P2 --> Z
```

---

## 3 Voice command

**Implemented in:** `app.py`: `App._on_ptt_press()` (the checks), then `App._voice_pipeline()` on the voice thread.

Started by a push-to-talk press and run on its own thread. Pressing **Emergency** or **Repeat** at any point abandons the command: every stage checks a shared cancel flag and returns.

```mermaid
---
title: 3 Voice command
---
flowchart TD
    A(["3 Voice command"]) --> B{"Voice stack failed to load?"}
    B -->|"yes"| B1[["6 Speech output:<br/>'voice commands unavailable'"]] --> Z
    B -->|"no"| C{"Still loading, or a<br/>command already running?"}
    C -->|"yes"| C1[/"Busy tone"/] --> Z
    C -->|"no"| D[/"Rising chime + vibration"/]
    D --> E[/"Record until push-to-talk<br/>is pressed again (max 30 s)"/]
    E --> F{"Cancelled?"}
    F -->|"yes"| Z
    F -->|"no"| F1{"Shorter than 0.2 s?"}
    F1 -->|"yes"| N1[["6 Speech output: 'nothing heard'"]] --> Z
    F1 -->|"no"| G[/"Falling chime; soft waiting blips start"/]
    G --> H{"Language?"}
    H -->|"English"| H1["Local Whisper (tiny)"]
    H -->|"Tagalog"| H2["Cloud Whisper;<br/>local Whisper (small) if it fails"]
    H1 --> I
    H2 --> I{"Transcript empty?"}
    I -->|"yes"| N1
    I -->|"no"| J[["3.1 Intent parsing"]]
    J --> K[["3.2 Intent execution"]]
    K --> K1[["6 Speech output: the reply<br/>(already spoken for an emergency)"]]
    K1 --> L{"Shutdown confirmed?"}
    L -->|"yes"| L1["Power off → SIGTERM ends chart 2"] --> Z
    L -->|"no"| M{"Navigation just started?"}
    M -->|"yes"| M1[["3.3 Turn-to-face"]]
    M -->|"no"| Z
    M1 --> Z(["Return: ready for the next command"])
```

### 3.1 Intent parsing

**Implemented in:** `intents/tiered.py`: `TieredIntentParser.parse()` (embedding tier), then `intents/fallback.py`: `FallbackIntentParser.parse()` (cloud, then local).

Three tiers, and a command only reaches the tiers it needs. The first tier answers about half of all commands on the device in about 30 ms. The embedding match never answers an intent with a free-text slot, such as a destination, because it cannot extract the slot.

```mermaid
---
title: 3.1 Intent parsing
---
flowchart TD
    A(["3.1 Intent parsing"]) --> B["Embedding match against<br/>the labelled example bank"]
    B --> C{"Confident match?<br/>(score ≥ 0.86, margin ≥ 0.02,<br/>intent has no free-text slot)"}
    C -->|"yes"| Z
    C -->|"no"| D{"Network route and<br/>cloud not in backoff?"}
    D -->|"yes"| E["Cloud LLM (Mistral) classifies"]
    E --> F{"Cloud call failed?"}
    F -->|"no"| Z
    F -->|"yes"| G
    D -->|"no"| G["Local LLM (Ollama, Qwen 3 1.7B) classifies"]
    G --> Z(["Return: intent + parameters"])
```

### 3.2 Intent execution

**Implemented in:** `intents/executor.py`: `IntentExecutor.execute()`, which dispatches to one `_handle_<intent>()` method per intent.

```mermaid
---
title: 3.2 Intent execution
---
flowchart LR
    A(["3.2 Intent execution"]) --> I{"Intent family?"}
    I -->|"navigation.start"| N0[["3.2.1 Start navigation"]]
    I -->|"other navigation.*"| N1["Stop, progress,<br/>or 'where am I'"]
    I -->|"emergency.trigger"| N2[["4 Emergency alert<br/>(source: voice)"]]
    I -->|"guardian.status_ok"| N3["Tell guardians 'I am OK'"]
    I -->|"vision.describe"| N4["Camera → YOLO object detection<br/>(falls back to ultrasonic distance)"]
    I -->|"vision.read"| N5["Camera → Tesseract OCR"]
    I -->|"place.*"| N6["Save / list / delete / locate<br/>a saved place"]
    I -->|"system.*, device.status"| N7["Time, help, language, volume,<br/>battery / GPS / signal,<br/>shutdown (asks to confirm)"]
    I -->|"unknown"| U{"Parse failed?"}
    U -->|"yes"| U1["'Sorry, I didn't catch that'"]
    U -->|"no"| U2{"Online?"}
    U2 -->|"yes"| U3["Ask the cloud answerer<br/>(general question)"]
    U2 -->|"no"| U4["'I need an internet connection'"]

    N0 --> R
    N1 --> R
    N2 --> R
    N3 --> R
    N4 --> R
    N5 --> R
    N6 --> R
    N7 --> R
    U1 --> R
    U3 --> R
    U4 --> R(["Return: reply text,<br/>kept for the Repeat button"])
```

### 3.2.1 Start navigation

**Implemented in:** `intents/executor.py`: `IntentExecutor._handle_navigation_start()`; the yes/no question is `app.py`: `App._confirm_destination()`.

Runs inside intent execution, on the voice thread. Once a route is set, chart 2.4 follows it from the main loop.

```mermaid
---
title: 3.2.1 Start navigation
---
flowchart TD
    A(["3.2.1 Start navigation"]) --> B{"GPS fix?"}
    B -->|"no"| X
    B -->|"yes"| C{"A saved place?"}
    C -->|"yes"| H
    C -->|"no"| D["Search Photon near the user"]
    D --> E{"Any results?"}
    E -->|"no"| X
    E -->|"yes"| F["Rank by name match, then distance"]
    F --> G[["6 Speech output: 'Go to X?'"]]
    G --> G0[/"Wait for a button:<br/>push-to-talk = yes · Repeat = no · 4 s silence = no"/]
    G0 --> G1{"Confirmed?"}
    G1 -->|"no"| X
    G1 -->|"yes"| H["GraphHopper walking route"]
    H --> H1{"Route found?"}
    H1 -->|"no"| X["Reply saying why<br/>(no GPS · not found · cancelled · no route)"]
    H1 -->|"yes"| I["Hand the route to the monitor<br/>(chart 2.4 now follows it)"]
    I --> I1["Reply: 'Navigating to X,<br/>distance, first instruction'"]
    X --> Z(["Return"])
    I1 --> Z
```

### 3.3 Turn-to-face

**Implemented in:** `app.py`: `App._orient_towards_route()`, using `navigation/orientation.py`: `OrientationGuide.cue()`.

Turns the user towards the start of the route before they take a step. It is inactive until the compass has been calibrated on the assembled unit.

```mermaid
---
title: 3.3 Turn-to-face
---
flowchart TD
    A(["3.3 Turn-to-face"]) --> B{"Compass calibrated?"}
    B -->|"no"| Z
    B -->|"yes"| C["Bearing from the user to the first<br/>meaningful point of the route"]
    C --> D[/"Read compass heading"/]
    D --> E{"Facing the route?"}
    E -->|"yes"| E1[["6 Speech output: 'walk straight ahead'"]] --> Z
    E -->|"no"| F[["6 Speech output:<br/>'face left / right / around'"]]
    F --> G{"Push-to-talk, cancel,<br/>or 20 s elapsed?"}
    G -->|"no"| D
    G -->|"yes"| Z(["Return"])
```

---

## 4 Emergency alert

**Implemented in:** one entry point per source, all ending in the same alert path:

- button: `app.py`: `App._on_emergency_press()`
- fall: `app.py`: `App._on_fall_detected()`
- voice: `intents/executor.py`: `IntentExecutor._handle_emergency_trigger()`

The spoken outcome is `app.py`: `App._on_alert_delivery()`.

There are three ways in, and all of them use the same delivery path. The buzzer sounds only here: it is the one output a bystander can perceive, so it carries a single meaning.

```mermaid
---
title: 4 Emergency alert
---
flowchart TD
    A(["4 Emergency alert (source)"]) --> S{"Source?"}

    S -->|"button"| B1["Cancel any voice command"]
    B1 --> C1[/"Buzzer + vibration (on every press)"/]
    C1 --> D1{"Alert already sent<br/>in the last 10 s?"}
    D1 -->|"yes"| D2[["6 Speech output:<br/>'already sent' (once per window)"]] --> Z
    D1 -->|"no"| E

    S -->|"fall"| C2[/"Buzzer + vibration"/]
    C2 --> C3[["6 Speech output:<br/>'fall detected' (interrupts)"]]
    C3 --> E

    S -->|"voice"| E

    E["Build alert: type, time,<br/>GPS fix up to 5 min old (else 0, 0)"]
    E --> F[["6 Speech output:<br/>'sending your alert' (interrupts)"]]
    F --> G[["4.1 Alert delivery"]]
    G --> I{"Who was reached?"}
    I -->|"backend and SMS"| J[["6 Speech output:<br/>'alert sent to your guardian'"]]
    I -->|"one channel failed"| K[["6 Speech output:<br/>which channel failed (interrupts)"]]
    I -->|"nobody"| L["Re-arm the button immediately"]
    L --> L1[["6 Speech output:<br/>'alert could not be sent' (interrupts)"]]
    J --> Z(["Return"])
    K --> Z
    L1 --> Z
```

### 4.1 Alert delivery

**Implemented in:** `telemetry/sms_alerts.py`: `SMSAlertNotifier.send_alert()`, wrapping `telemetry/buffered.py`: `BufferedTelemetryClient.send_alert()`.

Used by every guardian alert: emergency, fall and low battery. The caller does not wait on the network, because both legs run on worker threads. The outcome is reported back within about 30 s. Only emergency and fall alerts have their outcome spoken.

```mermaid
---
title: 4.1 Alert delivery
---
flowchart TD
    A(["4.1 Alert delivery"]) --> B["Queue alert for the backend<br/>(saved to disk, survives a reboot)"]
    A --> C["Start SMS fan-out to every guardian"]
    B --> B1["POST to the guardian dashboard;<br/>retry until delivered"]
    C --> C1{"Modem and guardian<br/>numbers available?"}
    C1 -->|"no"| C3
    C1 -->|"yes"| C2["Send via the modem (mmcli);<br/>retry each number"]
    C2 --> C3["SMS result"]
    B1 --> D["Combine: backend reached? + SMS result<br/>(waits up to 30 s)"]
    C3 --> D
    D --> E["Unreached numbers keep retrying<br/>in the background for up to 5 min"]
    E --> Z(["Return: delivery outcome"])
```

---

## 5 Repeat / stop

**Implemented in:** `app.py`: `App._on_repeat_press()`.

One button with two companion meanings, both about the last thing the device said.

```mermaid
---
title: 5 Repeat / stop
---
flowchart TD
    A(["5 Repeat / stop"]) --> B{"Speaking right now?"}
    B -->|"yes"| B1["Stop playback; clear the speech queue"]
    B -->|"no"| C
    B1 --> C{"Voice command in progress?"}
    C -->|"yes"| C1["Cancel the command"]
    C -->|"no"| D
    C1 --> D{"Stopped or cancelled anything?"}
    D -->|"yes"| D1[/"Stop tone"/] --> Z
    D -->|"no"| E[/"Vibration acknowledgement"/]
    E --> F[["6 Speech output:<br/>replay the last response"]]
    F --> Z(["Return"])
```

---

## 6 Speech output

**Implemented in:** `app.py`: `App._announce()` → `Announcer` (main loop and background threads); `App._play_clip()` and `App._clip_for_text()` (voice thread); file naming and lookup in `voice/clips.py`.

Shared by every chart that speaks. Speech raised on the main loop or a background thread goes through the **announcer** queue, so the loop never waits on audio. The voice thread plays its own speech directly.

```mermaid
---
title: 6 Speech output
---
flowchart TD
    A(["6 Speech output (text)"]) --> B{"Called from the main loop<br/>or a background thread?"}
    B -->|"yes"| C{"Critical?<br/>(fall, emergency, battery)"}
    C -->|"yes"| C1["Cut off current speech;<br/>drop pending non-critical items"]
    C -->|"no"| C2["Wait in the announcer queue"]
    C1 --> D
    C2 --> D
    B -->|"no: voice thread"| D

    D["Look up a clip named by a hash of<br/>voice + language + text<br/>(permanent messages first, then the cache)"]
    D --> E{"Clip found?"}
    E -->|"yes"| J
    E -->|"no"| F{"Language?"}
    F -->|"English"| G["Synthesise locally (Piper)"]
    F -->|"Tagalog"| H["Cloud TTS"]
    H --> H1{"Failed?"}
    H1 -->|"yes"| H2["Synthesise locally (MMS)"]
    H1 -->|"no"| I
    G --> I
    H2 --> I["Save the clip under the voice that made it:<br/>fixed message → permanent · templated → swept cache"]
    I --> J[/"Play through the speaker"/]
    J --> Z(["Return"])
```
