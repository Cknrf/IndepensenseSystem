# IndepenSense — Block Diagrams

What the system is made of and how its parts connect. [`flowchart.md`](flowchart.md) shows *when* things happen. These diagrams show *what talks to what*.

## How to read these

The diagrams are **levelled**, like the flowcharts. Each one zooms into a block of the one above it:

| Level | Diagram | Shows |
|---|---|---|
| 0 | [System context](#0-system-context) | The wearable as one block, with the people and services it talks to |
| 1 | [Hardware](#1-hardware-block-diagram) | Every physical component, the bus it sits on, and how power reaches it |
| 2 | [Software](#2-software-functional-block-diagram) | The runtime's domains, grouped into input, processing and output |

Every diagram reads **left to right: input → processing → output**. Arrow labels name the interface: a bus, a protocol, or the data that crosses it.

| Arrow | Meaning |
|---|---|
| Solid | Data or control, every time the system runs |
| Thick | Power |
| Dotted | Optional path. Cloud services with a local fallback, or a fallback used only when the primary path fails |

Pins, addresses and ports match [`hardware.md`](hardware.md) and `config.py` as of this commit. `hardware.md` stays the single source of truth for wiring. If the two disagree, this file is the one that is wrong.

---

## 0 System context

The wearable is one block here. Everything outside it is a person or a service it depends on.

```mermaid
---
title: 0 · IndepenSense system context
---
flowchart LR
    U(["Wearer<br/>visually impaired"])
    G(["Guardian<br/>family or carer"])

    W["<b>IndepenSense wearable</b><br/>Raspberry Pi 5 on a cane<br/><i>runs fully offline</i>"]

    subgraph CLOUD["Internet (optional)"]
        direction TB
        BE["Backend API<br/>indepensense-api"]
        DB["Guardian dashboard<br/><i>separate repository</i>"]
        MI["Mistral API<br/>intent parsing, open questions"]
        GP["gpuer<br/>Tagalog STT + TTS"]
    end

    U -->|"voice, 3 buttons, motion, surroundings"| W
    W -->|"speech, vibration, buzzer"| U
    W -->|"heartbeat + alerts<br/>HTTPS over 4G"| BE
    BE --> DB --> G
    W -->|"emergency SMS<br/>cellular, no data needed"| G
    W -.->|"HTTPS, local fallback"| MI
    W -.->|"HTTPS, local fallback"| GP
```

**Why the cloud box is dotted.** Every remote stage has a local fallback, and routing and geocoding run on the Pi itself (GraphHopper, Photon). With no network the device still detects falls and obstacles, navigates and speaks. Only two things need the network: guardian telemetry, and the open-question answerer. Alerts also go by SMS, which needs cellular signal but no data bearer. See [`cloud-services.md`](cloud-services.md).

---

## 1 Hardware block diagram

The wearable from level 0, broken into physical components. The Pi sits in the middle, inputs are on the left, outputs on the right, and power is below.

```mermaid
---
title: 1 · IndepenSense hardware
---
flowchart LR
    subgraph IN["INPUT"]
        direction TB
        US1["DYP-A22 ultrasonic · TOP<br/>head-level obstacles"]
        US2["DYP-A22 ultrasonic · BOTTOM<br/>ground-level obstacles"]
        IMU["MPU6050 IMU<br/>accel + gyro"]
        MAG["QMC5883P magnetometer<br/>heading"]
        CAM["Pi Camera Module 3"]
        BTN["3 push buttons<br/>PTT · Repeat/Stop · Emergency"]
        MIC["Headset microphone"]
    end

    subgraph CPU["PROCESSING"]
        PI["<b>Raspberry Pi 5</b><br/>Raspberry Pi OS Trixie<br/>Python 3.13"]
    end

    subgraph OUT["OUTPUT"]
        direction TB
        DRV1["3× NPN transistor"] --> MOT["3 vibration motors<br/>in the cane handle"]
        DRV2["NPN transistor"] --> BUZ["Active buzzer<br/>emergency only"]
        SPK["Headset speaker<br/>open-ear"]
    end

    subgraph COMMS["COMMUNICATION + POSITION"]
        SIM["SIM7600G-H 4G dongle<br/>cellular data · SMS · GPS"]
    end

    subgraph PWR["POWER"]
        direction TB
        BAT["4× 21700 Li-ion<br/>4S1P, 14.4 V nominal"]
        UPS["Waveshare UPS HAT (E)<br/>charger + fuel gauge"]
        BAT ==> UPS
    end

    US1 -->|"UART0 · 115200"| PI
    US2 -->|"UART4 · 115200"| PI
    IMU -->|"I2C1 · 0x68 · 100 Hz"| PI
    MAG -->|"I2C4 · 0x2C"| PI
    CAM -->|"CSI ribbon · CAM0"| PI
    BTN -->|"GPIO 21 / 19 / 25"| PI
    MIC -->|"USB Audio"| PI

    PI -->|"GPIO 16 / 27 / 26"| DRV1
    PI -->|"GPIO 20"| DRV2
    PI -->|"USB Audio"| SPK

    PI <-->|"USB"| SIM
    SIM -.->|"GPS NMEA · 1 Hz"| PI

    UPS ==>|"5 V · pogo pins"| PI
    UPS -->|"I2C1 · 0x2D<br/>battery %, voltage"| PI
```

**Design decisions this diagram shows:**

- **Two I²C buses.** The compass has I2C4 to itself. On I2C1 its third set of pull-ups made the bus unreliable. See [`hardware.md` → Why its own bus](hardware.md#why-its-own-bus).
- **Transistors between the GPIO and every motor or buzzer.** Each motor draws 60–100 mA, well above what a GPIO pin can source.
- **Microphone and speaker are one USB device.** The Pi 5 has no 3.5 mm jack. A USB Audio Class headset is full duplex, which the Bluetooth earphones it replaced were not.
- **The 4G dongle is on USB, not a HAT.** The 40-pin header is fully used, and a HAT would cover it.
- **The UPS HAT uses no header pins.** It powers the Pi through pogo pins underneath and shares only I2C1.
- **The three motors are drawn as one output.** They are mounted in the same handle, so the wearer feels one vibrator with three intensity steps, not three directions.

---

## 2 Software functional block diagram

The Raspberry Pi block from level 1, broken into the runtime's domains (`src/indepensense/<domain>/`). Each block names its module. Drivers are drawn with their hardware. Everything else is application logic that depends only on a driver's `Protocol`, never on the driver itself.

```mermaid
---
title: 2 · IndepenSense software (runtime on the Pi)
---
flowchart LR
    subgraph IN["INPUT · drivers"]
        direction TB
        S_US["sensors/<br/>DYP-A22 ×2"]
        S_IMU["sensors/<br/>MPU6050"]
        S_MAG["sensors/<br/>QMC5883P"]
        S_GPS["sensors/<br/>GPS via SIM7600"]
        S_BTN["feedback/<br/>buttons"]
        S_CAM["vision/<br/>camera"]
        S_MIC["voice/<br/>push-to-talk recorder"]
        S_UPS["power/<br/>UPS HAT"]
    end

    subgraph CORE["PROCESSING · app.py"]
        direction TB
        LOOP["<b>Main loop · 100 Hz</b><br/>never blocks"]
        SAFE["safety/<br/>fall detector<br/>still / walking"]
        OBS["Obstacle tiers<br/>proximity rhythm"]
        NAV["navigation/<br/>route monitor, off-route,<br/>turn-to-face"]

        subgraph VOICE["Voice pipeline · voice thread"]
            direction TB
            STT["voice/<br/>STT router"]
            NLU["intents/<br/>tiered intent parser"]
            EXE["intents/<br/>executor + handlers"]
            STT --> NLU --> EXE
        end

        VIS["vision/<br/>YOLOv8 · Tesseract OCR"]
        RT["routing/<br/>GraphHopper + Photon clients<br/>saved places"]
        MSG["intents/messages.py<br/>bilingual responses"]
    end

    subgraph OUT["OUTPUT"]
        direction TB
        ANN["Announcer thread<br/>voice/ TTS router + clip store"]
        HAP["feedback/<br/>motors · buzzer<br/>haptic worker threads"]
        TEL["telemetry/<br/>heartbeat + alert sender"]
        SMS["messaging/<br/>SMS via mmcli"]
    end

    subgraph LOCAL["Local services on the Pi"]
        direction TB
        GH[("GraphHopper :8989<br/>offline routing")]
        PH[("Photon :2322<br/>offline geocoding")]
        OL[("Ollama :11434<br/>Qwen 3 1.7B")]
    end

    subgraph NETW["Internet (optional)"]
        direction TB
        C_STT[("gpuer · STT")]
        C_LLM[("Mistral")]
        C_TTS[("gpuer · TTS")]
        C_BE[("Backend API")]
    end

    S_IMU --> LOOP
    S_US --> LOOP
    S_UPS --> LOOP
    S_GPS -->|"cached fix"| LOOP
    S_MAG --> NAV
    LOOP --> SAFE
    LOOP --> OBS
    LOOP --> NAV

    S_BTN -->|"PTT press"| S_MIC --> STT
    S_BTN -->|"emergency"| TEL
    EXE --> VIS
    S_CAM --> VIS
    EXE --> RT
    RT --> GH
    RT --> PH
    EXE --> NAV

    STT -.->|"Tagalog"| C_STT
    NLU -.->|"escalated utterances"| C_LLM
    NLU -.->|"when cloud fails"| OL
    ANN -.->|"Tagalog, templated"| C_TTS

    OBS --> HAP
    SAFE -->|"fall"| HAP
    SAFE -->|"fall"| TEL
    NAV --> MSG
    EXE --> MSG
    MSG --> ANN
    TEL --> C_BE
    TEL --> SMS
```

**What this diagram shows:**

- **The main loop only reads and decides.** Speech goes to the announcer thread and haptic patterns to short-lived worker threads, so fall and obstacle detection never wait on output. This is the concurrency rule in the `app.py` module docstring.
- **Voice runs on its own thread.** A push-to-talk press starts it, so transcription and inference (seconds) never touch the 100 Hz loop.
- **Intent parsing is three-stage.** An on-device embedding matcher answers about 52% of utterances in about 30 ms. The rest go to Mistral, and Ollama is used only when the cloud fails.
- **Every spoken word passes through `messages.py`.** No user-facing text lives in the logic blocks. That is what keeps English and Tagalog in step.
- **Every dotted arrow to the internet has a local block beside it.** Ollama backs Mistral. Local Whisper and Piper/MMS (inside the STT and TTS routers) back gpuer. GraphHopper and Photon never needed the cloud at all.
- **An alert leaves by two paths.** HTTPS to the backend for the dashboard, and SMS for when there is signal but no data.
