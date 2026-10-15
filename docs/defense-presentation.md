# IndepenSense — Final Defense Slide Draft

Slide-by-slide content for the CpE Practice and Design 1 defense, built on the DLSL master (`template-dlsl.pdf`).

## How to use this draft

**The template is a single master page:** 1440 × 810 pt (16:9). It has a solid DLSL-green sidebar on the left (~110 pt wide) with the logo at the top and `www.dlsl.edu.ph` at the bottom, a light-grey canvas, and the "be near. go far." tagline at the bottom right. Every layout below assumes:

- **Content area** from x ≈ 150 pt to x ≈ 1390 pt and y ≈ 60 pt to y ≈ 700 pt. Keep the bottom-right ~250 × 90 pt clear for the tagline.
- **Title** at the top left of the canvas in DLSL green. **Body** in dark grey on the light canvas.
- **Accent fills** (box headers, table header rows, PASS/FAIL chips) in DLSL green. Use one contrasting colour only for FAILED, such as a muted red, so failures read as failures at a glance.
- "Left column" and "right column" mean the two halves of the canvas. On single-visual layouts (diagram, table), Field 1 is the visual and Field 2 is its callouts or caption.

**Two markers appear in the content:**

- **⚑ Current build.** The fact comes from the system as it runs today (`config.py`, `README.md`, `docs/`). The paper does not say it, or says something different. Cite it only after you update the manuscript, or present it as "post-manuscript refinement".
- **⚠ Paper conflict.** The manuscript disagrees with itself or with the build. Fix the paper before the defense, because the panel reads the manuscript alongside the slides.

---

## Read this first: what the panel will catch

These are inconsistencies in `G5_O4AB_IndepenSense.pdf` that the slides cannot paper over. Each one needs an erratum or a manuscript fix.

| # | Where | Conflict | Suggested fix |
|---|---|---|---|
| 1 | Title page | The paper's title is *"Development of an IoT-Based **Wearable Navigation and Safety Assistance System** with Computer Vision and Guardian Monitoring"*. The defense title is *"Design and Implementation of an IoT-Based **Smart Cane** … **Remote** Guardian Monitoring"*. | Use one title on both. The panel checks the slide title against the approved title. |
| 2 | Ch. 2 vs build | The paper says GPS comes from a **u-blox NEO-F10N**. The build reads GNSS from the **SIM7600G-H** (`sensors/gps.py`, NMEA `$GN` sentences). The BOM still lists the u-blox at ₱219. | State that the GNSS comes from the SIM7600G-H. Drop the u-blox, or mark it as an unused or backup part. |
| 3 | Ch. 2 | The vibration motor count varies: "**Four** vibration motors" (Methods), **1** (BOM and power table), and **3** in the build (GPIO 17/27/22). | Use **3 motors** everywhere. |
| 4 | Ch. 2 vs build | The paper says **YOLOv8n**. The build loads **YOLOv8m, Open Images V7 weights** (`yolov8m-oiv7.pt`, confidence 0.3). | Name the model the device actually runs. This also strengthens the quantization recommendation. |
| 5 | Ch. 2 vs build | The paper says images go to a **cloud LLM over the SIM7600 for scene description**. In the build, vision runs **entirely on the device** (YOLO plus Tesseract OCR). The cloud LLM (Mistral) does **intent classification and open questions**, not vision. | Rewrite the hybrid edge–cloud paragraphs to match. |
| 6 | Ch. 2 | The paper says the camera wakes "when a fall is detected". The build activates the camera **only on a voice intent**. | Remove the fall trigger. |
| 7 | Ch. 2 | "**GreenHopper**" should be **GraphHopper**. The paper also says "HTTPS/MQTT", but the build uses **HTTPS** to the backend plus **SMS**, with no MQTT. | Correct both. |
| 8 | Ch. 1 vs Ch. 2–3 | Scope says "indoor navigation was outside the scope", yet System Testing phase 1 lists "indoor navigation" and the on-site test was inside a mall. | Remove "indoor navigation" from phase 1. Justify the venue as a safety and accessibility choice (Slide 39 notes). |
| 9 | Table 5/6 | Ultrasonic "1 m detection → **100 meters**" | Should read **100 cm**. |
| 10 | Table 13 | MPU-008 (**FAILED**) and MPU-009 (**PASSED**) are the *same* test case. | Present them as two runs of one test: 1 of 2 long runs failed. This is "mixed reliability", as the deck states. |
| 11 | Table 14 vs 17 | SIM-008 "GPS Location Test: **accurate** location data — PASSED" contradicts TC-GPS-03 "deviated **> 10 m** — FAILED". Both use the same GNSS. | Reword SIM-008 to "module returns a GNSS fix" (pass) and leave accuracy to TC-GPS-03 (fail). |
| 12 | Table 17 | TC-GPS-06: the expected result was "reports *No Signal*", the actual was "reported no GPS signal", and it is marked **FAILED**. The behaviour met its expectation. | Either re-mark it PASSED (6/7, 85.71%) or rewrite the expected result to what actually failed. |
| 13 | Table 20 | TC-ONS-14 fall detection is **PASSED**, but its own note says accuracy was *not confirmed*. TC-ONS-15's note is a copy of TC-ONS-14's. | Re-mark TC-ONS-14 as "triggered in simulation, accuracy unconfirmed". Write a real note for TC-ONS-15. |
| 14 | Ch. 3 | Objective 4 (GPS route guidance) has **no results table**. Turn-by-turn guidance through GraphHopper is never tested in Chapter 3. | Add a navigation test, or soften the "all objectives achieved" claim for Objective 4. |
| 15 | Ch. 2–3 | The paper says "final runtime was verified … under idle, navigation, CV and emergency", but **no runtime figure appears** anywhere. | Add the measured runtime, or remove the sentence. The panel *will* ask how long it lasts. |
| 16 | Table 15 | The magnetometer was tested on **N, NE, E, SE, S** only. **W, SW and NW are untested**. TC-MAG-13 has a stray "5/55" typo. | Disclose the untested headings, or test them. |

---

## SECTION 1 — TITLE

### [SLIDE NUMBER & TITLE]: 1 — IndepenSense: IoT Smart Cane with Guardian Monitoring
**[TEMPLATE LAYOUT MAPPING]:** Title Slide. The full title is centred on the canvas, with the authors block below and an optional hero photo of the actual prototype (Fig. 25) at the right.

**[LEFT COLUMN / CONTENT FIELD 1]:**
- **IndepenSense: Design and Implementation of an IoT-Based Smart Cane with Computer Vision and Remote Guardian Monitoring** *(⚠ match to the approved manuscript title, item 1)*
- **De La Salle Lipa** · College of Information Technology and Engineering (**CITE**)
- **Computer Engineering Department**
- CpE Practice and Design 1 · **Group 5**

**[RIGHT COLUMN / CONTENT FIELD 2]:**
- **Lubay, Cian Eythan Jeremy**
- **Odi, Mearck Francis Voughn**
- **Rivera, Katelyn Denise**
- **October 2026**
- *Photo: assembled cane + reflective vest (Fig. 25, Actual Prototype)*

**[SPEAKER NOTES]:**
"Good morning, distinguished panel members. We are Group 5 of the Computer Engineering Department, and we present IndepenSense: the design and implementation of an IoT-based smart cane with computer vision and remote guardian monitoring. Our work addresses a concrete engineering problem: a conventional white cane tells its user only what it touches, and tells the user's family nothing at all. Over the next minutes we will show how we closed both gaps with a Raspberry Pi 5 edge platform, dual ultrasonic sensing, inertial fall detection and LTE telemetry. We will report our bench and field results as measured, including the tests that failed, because the failures define the boundary of what this prototype can claim."

---

## SECTION 2 — INTRODUCTION

### [SLIDE NUMBER & TITLE]: 2 — Visual Impairment: A Persistent Mobility Burden
**[TEMPLATE LAYOUT MAPPING]:** Two-Column Contrast. Global and national statistics on the left, the consequences for mobility on the right.

**[LEFT COLUMN / CONTENT FIELD 1]:**
- Vision is the primary sense for **spatial awareness and navigation**
- **Billions** worldwide live with some form of visual impairment (**WHO, 2026**)
- Philippines: **1.98% prevalence** of visual impairment and blindness (**2018 Philippine National Blindness Survey**)
- Leading causes: **cataract**, **uncorrected refractive error**, **glaucoma**, and many cases still undiagnosed (**Garcia et al., 2022**)

**[RIGHT COLUMN / CONTENT FIELD 2]:**
- **Mobility barriers**, hiring discrimination and limited resources (**Oberes et al., 2023**)
- Medical care **delayed or avoided** because of transport and the need for an escort (**Butalid et al., 2024**)
- **Higher accident and injury risk** in crowded, unfamiliar spaces (**Hoogsteen & Szpiro, 2023**)
- The impact goes beyond injury to **confidence, independence and psychological well-being**

**[SPEAKER NOTES]:**
"Vision carries most of the information a person uses to move through space. The World Health Organization reports that billions of people live with some form of visual impairment, and in the Philippines the 2018 National Blindness Survey places the prevalence at 1.98 percent, driven by cataract, refractive error and glaucoma. The literature is consistent that the cost goes beyond the medical. Visually impaired Filipinos face mobility barriers that affect employment, delay health care because travel requires an escort, and raise their exposure to accidents in unfamiliar, crowded environments. Every one of these outcomes traces back to a single deficit: limited awareness of the immediate surroundings. That deficit is the engineering target of this project."

---

### [SLIDE NUMBER & TITLE]: 3 — The Mobility Crisis in Lipa City
**[TEMPLATE LAYOUT MAPPING]:** 3-Box Process Flow, used as three side-by-side "challenge" boxes with a supporting interview quote strip beneath.

**[LEFT COLUMN / CONTENT FIELD 1]:**
- **Challenge 1: Identifying obstacles.** The cane detects only on **physical contact** and cannot say *what* the obstacle is
- **Challenge 2: Navigating unfamiliar spaces independently.** Confidence is high on familiar routes and drops sharply in new places, and many users **rely on another person**
- **Challenge 3: Frequent falls.** Users reported falls on **raised road surfaces and humps** and on unexpected changes underfoot

**[RIGHT COLUMN / CONTENT FIELD 2]:**
- **Source:** in-person **unstructured interviews**, with participants chosen by **purposive sampling**
- **Participants:** visually impaired adults **aged 31+** living in **Lipa City, Batangas**
- **Range of vision:** from residual light and shadow perception to **little or no vision**
- **Current aid:** mostly a **traditional cane or stick**
- **Their requests:** **different vibration or audio patterns per obstacle**

**[SPEAKER NOTES]:**
"To ground the design in local need rather than assumption, we interviewed visually impaired adults living in Lipa City, selected through purposive sampling. Three challenges came up repeatedly. First, identifying obstacles: a cane reports an obstacle only on contact, and never what it is. Second, unfamiliar spaces: participants were confident on routes they knew, but travel to new places usually meant depending on another person. Third, falls: participants described falls on raised road surfaces and humps, which are common on local pedestrian paths. These three findings map directly to three subsystems of IndepenSense: proximity sensing and vision, voice-guided navigation, and inertial fall detection with guardian alerting."

---

### [SLIDE NUMBER & TITLE]: 4 — Research Gap in Existing Smart Canes
**[TEMPLATE LAYOUT MAPPING]:** Data Table Matrix with three rows (Local, National, International) and two columns (What exists, What is missing). A one-line synthesis banner sits underneath.

**[LEFT COLUMN / CONTENT FIELD 1]:**
- **Local:** **ultrasonic + GPS tracking + basic alerts** on microcontrollers (**Aycardo et al., 2020**)
- **National:** microcontroller canes with **GSM SMS location** and sound feedback (**Merencilla et al., 2021; Delgado et al., 2024**)
- **International:** **YOLOv8n**, RGB-D, **LiDAR**, **ToF**, IoT tracking (**Mai et al., 2024; Mungdee et al., 2025; Shah et al., 2026**)

**[RIGHT COLUMN / CONTENT FIELD 2]:**
- Local gap: **no embedded intelligence**, no object identity
- National gap: **threshold-only sensing**, **reactive** emergency models, no continuous guardian view
- International gap: **high power draw, latency, cost, complexity**, plus **cognitive overload** from unprioritised feedback
- **Common gap:** studies improve **one subsystem at a time**, with little attention to **ergonomic weight distribution**

**[SPEAKER NOTES]:**
"Our review traces three tiers of prior work. Local studies prove the feasibility of ultrasonic sensing with GPS tracking but stop at distance thresholds. National work adds GSM-based SMS alerts, but the emergency model is reactive and offers guardians no continuous view. International systems add object detection, LiDAR and depth cameras, and pay for it in power, latency, cost and, critically, cognitive overload when every detection is announced. The gap we target is therefore integration. Most systems optimise one subsystem in isolation and place every component on the cane itself. IndepenSense combines sensing, vision, voice and guardian monitoring in one architecture and redistributes the weight to the body."

---

## SECTION 3 — SIGNIFICANCE OF THE PROJECT

### [SLIDE NUMBER & TITLE]: 5 — Traditional White Cane versus IndepenSense
**[TEMPLATE LAYOUT MAPPING]:** Two-Column Contrast, with "White Cane" on the left and "IndepenSense" on the right. Matching rows let the eye compare across.

**[LEFT COLUMN / CONTENT FIELD 1]:** *Traditional white cane*
- Detection by **physical contact only**
- Range is roughly **cane length (~1 m)**, at **ground level only**
- **No object identity**: a pole, a person and a sign all feel the same
- **No head-level protection** (branches, awnings, signage)
- **No fall awareness**, and no way to call for help
- Guardian has **zero visibility** of location or status

**[RIGHT COLUMN / CONTENT FIELD 2]:** *IndepenSense*
- **Contactless detection**: **2× DYP-A22 ultrasonic**, upper and ground level
- Proximity warnings start at **200 cm** ⚑ and **all 3 motors** fire inside **50 cm** ⚑
- **Object recognition** and **sign reading** on demand: **Camera Module 3 + YOLOv8** ⚑ + **Tesseract OCR** ⚑
- **MPU-6050 fall detection** at **100 Hz** ⚑ triggers an automatic alarm
- **SOS button** sends a **GPS-tagged** alert over **LTE (HTTPS) + SMS** ⚑
- **Live guardian tracking** on the **web + Android** platform

**[SPEAKER NOTES]:**
"This contrast frames the contribution. The white cane is affordable, reliable and trusted, and we do not claim to replace the skill of using it. We extend what the cane can sense. The white cane's range is its length, at ground level, by contact. IndepenSense adds two ultrasonic sensors, one aimed at ground obstacles and one at upper-body and head-level hazards that a cane sweep physically cannot reach. On request, a camera identifies what is ahead and reads text aloud. An inertial measurement unit watches for falls continuously. Finally, the guardian moves from zero visibility to live location and immediate alerts."

---

### [SLIDE NUMBER & TITLE]: 6 — Dual-Beneficiary Design: User and Guardian
**[TEMPLATE LAYOUT MAPPING]:** Two-Column Contrast with a central device icon: the User side on the left, the Guardian side on the right, and an SDG badge strip along the bottom.

**[LEFT COLUMN / CONTENT FIELD 1]:** *Environmental awareness for the user*
- **Haptic channel:** urgent proximity cues, **pulse rate encodes distance** (parking-sensor model)
- **Audio channel:** descriptive information such as object names, signs, turn instructions and battery status
- **Push-to-Talk** voice commands, so no screen and no visual menu are needed
- **Bilingual speech:** **English + Tagalog** ⚑
- Grounded in **Multimodal Interaction** and **Cognitive Load Theory**: urgent cues go to touch, descriptive information to hearing

**[RIGHT COLUMN / CONTENT FIELD 2]:** *Real-time safety for the guardian*
- **Live GPS location** on the **web dashboard + Android app**
- **Automatic alerts** for **SOS**, **fall detection** and **low battery** ⚑
- Device **heartbeat every 30 s** ⚑ carrying battery and cellular status
- **SMS fallback** that needs signal but **no data connection** ⚑
- **SDG 9:** Industry, Innovation & Infrastructure · **SDG 10:** Reduced Inequalities

**[SPEAKER NOTES]:**
"IndepenSense serves two people at once. For the user, feedback is split by urgency, following Multimodal Interaction and Cognitive Load theory. Proximity is delivered through touch, where the vibration rate rises as an obstacle approaches, much like a car's parking sensor. Descriptive information such as object names, signs and directions is delivered through speech, so the two channels never compete. For the guardian, the device reports a heartbeat every thirty seconds and pushes an alert the moment an SOS, a fall or a low battery occurs. Because mobile data is not always available, every alert also travels by SMS. The project supports SDG 9 on innovation and SDG 10 on reduced inequalities."

---

## SECTION 4 — PROJECT OBJECTIVES

### [SLIDE NUMBER & TITLE]: 7 — General Objective of the Project
**[TEMPLATE LAYOUT MAPPING]:** Title + Single Statement. One large objective statement in a green-bordered box, with three keyword chips beneath.

**[LEFT COLUMN / CONTENT FIELD 1]:**
- **To design and develop IndepenSense**, an **AI-powered, IoT-based smart cane** with **computer vision**, **sensor integration** and **remote guardian monitoring**
- **Purpose:** to improve the **navigation**, **safety** and **situational awareness** of visually impaired individuals

**[RIGHT COLUMN / CONTENT FIELD 2]:**
- Chip 1: **NAVIGATION**
- Chip 2: **SAFETY**
- Chip 3: **SITUATIONAL AWARENESS**

**[SPEAKER NOTES]:**
"Our general objective was to design and develop IndepenSense, an AI-powered, IoT-based smart cane integrating computer vision, multi-sensor input and remote guardian monitoring, in order to improve three outcomes for visually impaired users: navigation, safety and situational awareness. These three words are the measures of success that the rest of this presentation reports against. Every subsystem we describe, and every test we report, traces back to at least one of them. Where a test failed, we will say which of the three outcomes it limits."

---

### [SLIDE NUMBER & TITLE]: 8 — Specific Objectives Mapped to Engineering Goals
**[TEMPLATE LAYOUT MAPPING]:** 3-Box Process Flow: Goal A Hardware Architecture → Goal B IoT Notifications → Goal C Validation. The six specific objectives are grouped under the boxes.

**[LEFT COLUMN / CONTENT FIELD 1]:**
- **Goal A: Develop the hardware architecture**
  - **SO1:** smart cane with **ultrasonic, GPS, IMU, camera** and feedback components
  - **SO2:** **haptic + audio** feedback for guidance and hazard alerts
  - **SO3:** **AI object recognition** as supplementary awareness
- **Goal B: Integrate IoT cellular notification**
  - **SO4:** **GPS/GNSS outdoor navigation** support within test environments
  - **SO5:** **emergency response** with notifications and location monitoring
  - **SO6:** **guardian web platform** for location, alerts and notifications

**[RIGHT COLUMN / CONTENT FIELD 2]:**
- **Goal C: Validate through testing**
  - **Bench:** component tests on **15 modules**, **100+ test cases**
  - **Calibration:** magnetometer heading and IMU fall trials
  - **On-site:** **18 field test cases** at **Robinsons Lipa** with an adult visually impaired participant
- Traceability: each SO maps to at least one results table (**Tables 5–20**)

**[SPEAKER NOTES]:**
"The six specific objectives in the manuscript resolve into three engineering goals. Goal A is the hardware architecture: the sensor suite, the dual-channel feedback system, and object recognition as a supplementary aid, which we deliberately frame as supplementary because vision is the least reliable sensor under real lighting. Goal B is the IoT layer: GPS-based outdoor navigation, the emergency pipeline, and the guardian platform. Goal C is validation, carried out in three stages: component bench tests, calibration procedures, and an on-site trial with a visually impaired participant. Every objective traces to at least one results table, so the panel can check each claim against its evidence."

---

## SECTION 5 — SCOPE AND DELIMITATION

### [SLIDE NUMBER & TITLE]: 9 — Project Scope: Integrated Subsystems
**[TEMPLATE LAYOUT MAPPING]:** 2x2 Grid (Sensing · Vision · Safety · Connectivity), with a fifth strip along the bottom for the Guardian App.

**[LEFT COLUMN / CONTENT FIELD 1]:**
- **Sensing: ultrasonic tracking.** **2× DYP-A22**, UART, upper and ground level, continuous polling
- **Vision: Raspberry Pi Camera Module 3.** **12 MP** sensor, captured at **1280×720, 15 fps** ⚑, with **YOLOv8** detection and **OCR**, triggered **on voice demand**
- **Safety: MPU-6050 fall detection.** 3-axis accelerometer + gyroscope, **I²C**, sampled at **100 Hz** ⚑ on the chest/vest

**[RIGHT COLUMN / CONTENT FIELD 2]:**
- **Connectivity: SIM7600G-H.** **4G LTE** data, **SMS**, and the **integrated GNSS** receiver ⚑ (⚠ item 2)
- **Guardian monitoring:** **web dashboard + Android app** for live location, SOS and fall notifications
- **Also in scope:** **QMC5883P** compass heading, **voice assistant** (PTT), **on-device routing** (GraphHopper + Photon) ⚑
- **Environment:** **outdoor pedestrian** use with GNSS and cellular coverage

**[SPEAKER NOTES]:**
"Our scope is a functional prototype integrating five subsystems. Ultrasonic tracking uses two DYP-A22 sensors on UART. Computer vision uses the Raspberry Pi Camera Module 3, run on demand when the user asks, rather than continuously, which keeps it from draining the battery. Fall detection uses the MPU-6050, sampled at one hundred hertz and mounted on the vest, where the motion reflects the body rather than the swinging cane. The SIM7600G-H provides LTE data, SMS, and the GNSS receiver used for location. The guardian platform, web and Android, completes the loop. The intended environment is outdoor pedestrian travel where satellite and cellular coverage exist."

---

### [SLIDE NUMBER & TITLE]: 10 — Delimitations and Operating Boundaries
**[TEMPLATE LAYOUT MAPPING]:** Two-Column Contrast: "Physical Delimitations" on the left, "Environmental & Network Delimitations" on the right. Add a cone diagram showing the 35°–45° detection profile.

**[LEFT COLUMN / CONTENT FIELD 1]:** *Physical / sensing*
- **Forward-facing detection profile only**, with an effective **35°–45° cone** validated on the bench
- **No lateral (left/right) sensing.** Obstacles beside the user are outside the cone
- The **3 vibration motors share one handle**, so they signal **intensity, not direction** ⚑
- Vision recognises **general object classes** only, with **no fine-grained scene reasoning**
- **Fixed cane length** in the tested build

**[RIGHT COLUMN / CONTENT FIELD 2]:** *Environmental / network*
- **Absolute cellular dependency** for guardian telemetry, SMS and cloud speech features
- **GNSS degrades indoors** and under structural obstruction
- **CV accuracy degrades** in **low light, harsh light, rain**
- Higher **power draw** when vision is active, which shortens runtime
- **Indoor navigation is out of scope**
- **What survives offline** ⚑: obstacle warnings, fall detection, the local alarm, on-device routing and English speech

**[SPEAKER NOTES]:**
"We bound our claims explicitly. Physically, detection is forward-facing. Our bench tests validated a cone of roughly thirty-five to forty-five degrees, and an obstacle beside the user is outside it. The three vibration motors sit in one handle, and their vibration couples through the shell, so the user feels intensity, not direction. We therefore never use them to signal left or right. Environmentally, the guardian features depend completely on cellular coverage, GNSS accuracy falls indoors, and vision is sensitive to lighting. Our design response is that the safety-critical functions, obstacle warnings and fall detection with its local alarm, run entirely on the device and survive any network outage."

---

## SECTION 6 — PROJECT DESCRIPTION & HARDWARE ARCHITECTURE

### [SLIDE NUMBER & TITLE]: 11 — System Overview: Hybrid Edge–Cloud Architecture
**[TEMPLATE LAYOUT MAPPING]:** Hub-and-Spoke Diagram. The wearable sits at the centre, with the wearer and the guardian on either side and a dotted "Internet (optional)" cloud at the top. Field 2 holds the callouts.

**[LEFT COLUMN / CONTENT FIELD 1]:**
- **Edge (Raspberry Pi 5), always on:** obstacle sensing, fall detection, haptics, buzzer, **YOLOv8 + OCR** ⚑, **GraphHopper routing** and **Photon geocoding**, both **on device** ⚑
- **Cloud (optional, with dotted links):** **Mistral** intent classification and open questions ⚑, **Tagalog speech-to-text and text-to-speech** server ⚑, **backend API → guardian dashboard**
- **Cellular, without data:** **emergency SMS** straight to the guardian's phone ⚑

**[RIGHT COLUMN / CONTENT FIELD 2]:**
- **Design rule ⚑:** every cloud stage has a **local fallback**, so the device **degrades** rather than failing
- Wearer → device: **voice, 3 buttons, motion, surroundings**
- Device → wearer: **speech, vibration, buzzer**
- Device → guardian: **HTTPS heartbeat + alerts** over **4G**, **SMS** for alerts
- ⚠ The manuscript describes **cloud scene description**. In the build, vision is **fully local** (item 5)

**[SPEAKER NOTES]:**
"IndepenSense follows the Edge/Hybrid Computing paradigm from our framework. Everything safety-critical runs on the Raspberry Pi 5: obstacle sensing, fall detection, haptic and buzzer output, object detection and text reading. Pedestrian routing and geocoding also run locally, so navigation does not need cloud maps. The cloud is optional. It improves intent classification accuracy and Tagalog speech quality, and it carries telemetry to the guardian. Each cloud stage has a local fallback. The design principle is graceful degradation: with no network, the device still detects obstacles, detects falls, sounds its alarm and speaks; it loses only the guardian's live view."

---

### [SLIDE NUMBER & TITLE]: 12 — Compute and Power Core
**[TEMPLATE LAYOUT MAPPING]:** Two-Column Contrast: "Compute" on the left, "Power" on the right. A photo of the Pi 5 + UPS HAT stack sits between them.

**[LEFT COLUMN / CONTENT FIELD 1]:** *Compute*
- **Raspberry Pi 5**: quad-core ARM, **Raspberry Pi OS Trixie**, **Python 3.13** ⚑
- **~12 W peak** board draw (bare board, worst case)
- **Raspberry Pi Active Cooler** (fan + heatsink) for sustained YOLO and speech inference
- **Micro SD** for OS, models and logs
- Every device sits behind a **hardware-abstraction protocol**, so the full runtime runs on a laptop with mocks ⚑

**[RIGHT COLUMN / CONTENT FIELD 2]:** *Power*
- **Waveshare UPS HAT (E)** with **4× 21700 Li-ion** cells (**3.7 V** nominal each)
- **Single unified supply** for the Pi and **all peripherals**, replacing an earlier dual-source design
- Estimated typical load **≈ 11.7 W** (sum of Table 2) · **SIM7600 transmit peaks up to 2 A**
- **Corrected battery percentage** ⚑: the HAT's gauge reads **~57–59 % on a flat pack**, so the raw value is rescaled
- Battery is **spoken at boot** and shown on the guardian platform
- ⚠ No measured runtime in the manuscript (item 15)

**[SPEAKER NOTES]:**
"The Raspberry Pi 5 was chosen because it is the lowest-power board able to run object detection and speech recognition locally, with roughly twelve watts at worst case and a large ecosystem of compatible peripherals. An active cooler holds clock speed during sustained inference. Power comes from a single Waveshare UPS HAT E with four 21700 cells, which replaced our earlier dual-supply design and simplified the wiring. Summing our component table gives about 11.7 watts typical, with the LTE modem transmitting in bursts of up to two amps. One finding deserves mention. The HAT's own gauge read about fifty-eight percent on an empty pack, so we rescale it; otherwise the low-battery warning could never have fired."

---

### [SLIDE NUMBER & TITLE]: 13 — Perception Layer: Sensors and Interfaces
**[TEMPLATE LAYOUT MAPPING]:** Data Table Matrix with columns Component · Bus · Mounting · Role.

**[LEFT COLUMN / CONTENT FIELD 1]:**
| Component | Bus / Port | Mount | Role |
|---|---|---|---|
| **DYP-A22 Ultrasonic · TOP** | UART `ttyAMA0` ⚑ | Cane | Upper-body / head-level hazards |
| **DYP-A22 Ultrasonic · BOTTOM** | UART `ttyAMA4` ⚑ | Cane | Ground-level obstacles (curbs, walls, planters) |
| **MPU-6050 IMU** | I²C | Vest | Fall detection, walking/still state ⚑ |
| **QMC5883P Magnetometer** | I²C `0x2C` ⚑ | Vest | Compass heading for navigation |
| **Pi Camera Module 3** | CSI ribbon | Cane | Object detection + OCR |

**[RIGHT COLUMN / CONTENT FIELD 2]:**
- **DYP-A22:** waterproof ultrasonic, **UART** output, distance in **cm**, about **15 mA** each
- **MPU-6050:** accelerometer + gyroscope, **~4 mA**, chest-mounted so it measures **body** motion rather than cane swing
- **QMC5883P:** sold as a "QMC5883L" but answers at **0x2C** ⚑. It is **3.3 V only**
- **Camera Module 3:** **12 MP**, run at **1280×720 @ 15 fps** ⚑, **YOLO confidence 0.3** ⚑
- **Drivers own the protocol:** frame parsing, checksums and register maps live in the driver, not the application ⚑

**[SPEAKER NOTES]:**
"The perception layer has five sensors on three buses. Two DYP-A22 ultrasonic sensors sit on separate UARTs. The bottom sensor watches for ground obstacles such as curbs, walls and planters. The top sensor watches for hazards at upper-body and head height, which the cane tip physically cannot reach. The MPU-6050 and the QMC5883P magnetometer share the I²C bus and are mounted on the vest. That placement is deliberate: an IMU on the cane would read every sweep as violent motion, while one on the chest reads the body. The Camera Module 3 connects over CSI. One integration lesson: the magnetometer sold to us as a QMC5883L was in fact a QMC5883P at a different address."

---

### [SLIDE NUMBER & TITLE]: 14 — Communication Layer: SIM7600G-H Telemetry Module
**[TEMPLATE LAYOUT MAPPING]:** 3-Box Process Flow showing three channels out of one module: LTE Data → SMS → GNSS.

**[LEFT COLUMN / CONTENT FIELD 1]:**
- **Box 1: 4G LTE data (HTTPS)**
  - **Heartbeat every 30 s** ⚑: location, battery, signal
  - Alert events pushed **immediately**
  - **Buffered retry** when the link is down ⚑
- **Box 2: SMS**
  - Sent for **Emergency, Fall and Low Battery** ⚑
  - Needs **signal only, no data bearer**
  - Retried for up to **5 min** ⚑
- **Box 3: GNSS**
  - **Integrated receiver** streaming **NMEA ($GN RMC/GGA)** ⚑
  - Multi-constellation: GPS, GLONASS, BeiDou, Galileo

**[RIGHT COLUMN / CONTENT FIELD 2]:**
- **Interface:** **USB** to the Pi 5, with multiple serial endpoints (AT, NMEA)
- **Power:** **5 V**, **~0.3 A** typical, **~2 A transmit peaks**
- **Cost:** **₱5,384.92**, the second-largest BOM item
- **Why one module:** one antenna system and one USB link carry **data, SMS and location**
- **Offline hardening** ⚑: network route pre-check, per-host circuit breaker, and a **2 s DNS bound**, which removed a **20 s per-lookup stall** on a dead link
- ⚠ The manuscript names a separate **u-blox NEO-F10N** for GPS (item 2)

**[SPEAKER NOTES]:**
"The SIM7600G-H is the device's only link to the outside world, and it carries three independent channels. LTE data carries the thirty-second heartbeat and immediate alert events to the backend over HTTPS, with buffering and retry when the link drops. SMS carries the same emergency, fall and low-battery alerts directly to the guardian's phone, because SMS needs only signal, not a working data connection. Finally, its integrated GNSS receiver streams position. We also found that on a failing link, a single name lookup could hang for twenty seconds, three times per voice command. Bounding DNS and adding a circuit breaker turned that into one slow command followed by local operation."

---

### [SLIDE NUMBER & TITLE]: 15 — Feedback and User Interface Layer
**[TEMPLATE LAYOUT MAPPING]:** 2x2 Grid: Haptic · Buzzer · Buttons · Audio.

**[LEFT COLUMN / CONTENT FIELD 1]:**
- **Haptic: 3× flat vibration motors** ⚑ on **GPIO 17 / 27 / 22** ⚑, each switched by a **2N2222 NPN** with a **1N4007 flyback diode**
  - Front motor alone = **warning**, all three = **danger (< 50 cm)** ⚑
- **Buzzer: piezo tone buzzer** on **GPIO 18** ⚑
  - **Reserved for emergencies only** ⚑, the one output a **bystander** can perceive

**[RIGHT COLUMN / CONTENT FIELD 2]:**
- **Buttons: 3× 12 mm PBS-33B waterproof momentary**, body-relative ⚑
  - **Right = Push-to-Talk** (also the "yes" confirm)
  - **Front = Emergency SOS** (GPIO 25)
  - **Left = Repeat / Stop** (also "no")
- **Audio: USB open-ear headset** with mic and speaker ⚑
  - Pi 5 has **no 3.5 mm jack**
  - **Open-ear** keeps the user's **ambient hearing** for traffic

**[SPEAKER NOTES]:**
"The output design follows one rule: each channel has a single meaning. Three vibration motors, each driven through a 2N2222 transistor with a flyback diode, signal obstacle proximity. One motor warns, and all three signal danger inside fifty centimetres. The buzzer is reserved for emergencies, because it is the only output a bystander can hear. If it also sounded for an awning, it would mean nothing in a real emergency. The three waterproof buttons are placed by touch: right for push-to-talk, front for SOS, left for repeat or stop. Audio is delivered through an open-ear USB headset, so the user never loses the sound of traffic."

---

### [SLIDE NUMBER & TITLE]: 16 — Ergonomic Split: Cane and Wearable Vest
**[TEMPLATE LAYOUT MAPPING]:** Two-Column Contrast with a central figure. A photo or illustration of the user wearing the vest, with the tube harness to the cane, sits in the middle. Cane-mounted parts go on the left, vest-mounted parts on the right.

**[LEFT COLUMN / CONTENT FIELD 1]:** *Cane assembly (kept light)*
- **2× DYP-A22 ultrasonic** sensors, which must face the path
- **Pi Camera Module 3**, which the user can aim by angling the cane
- **3 vibration motors**, **buzzer** and **3 buttons** in a **3D-printed handle casing**
- **Adjustable, foldable aluminium cane** (₱165)

**[RIGHT COLUMN / CONTENT FIELD 2]:** *Vest enclosure (carries the weight)*
- **Raspberry Pi 5 + Active Cooler** in a **3D-printed case**
- **Waveshare UPS HAT (E) + 4× 21700** cells, the heaviest single item
- **SIM7600G-H**, **MPU-6050**, **QMC5883P**, headset interface
- **High-visibility reflective vest** for night safety (₱358)
- **Tube-like harness** hides the cane-to-vest wiring and doubles as an **anti-loss tether**

**[SPEAKER NOTES]:**
"The most important mechanical decision was to split the system across two bodies. Anything that must sense the path, or be touched, stays on the cane: the ultrasonic sensors, the camera, the motors, the buzzer and the buttons. Everything heavy moves to a reflective vest: the processor, the battery pack, the modem and the inertial sensors. There are two reasons. A cane loaded with four 21700 cells and a Raspberry Pi would fatigue the wrist within minutes. And the IMU must be on the torso to measure the body's fall rather than the cane's swing. The wiring tube that joins them also tethers the cane, so it cannot be dropped and lost, which was confirmed comfortable during field testing."

---

### [SLIDE NUMBER & TITLE]: 17 — Hardware Block Diagram: Four Subsystems
**[TEMPLATE LAYOUT MAPPING]:** Full-Width Diagram + Callouts. Insert Fig. 24 (Prototype Block Diagram), or the level-1 diagram from `docs/block-diagram.md`, reading left to right as input → processing → output, with power below.

**[LEFT COLUMN / CONTENT FIELD 1]:**
- **① Cane perception & feedback:** ultrasonics, camera, buttons → motors, buzzer
- **② Vest core processing:** **Raspberry Pi 5**, IMU, magnetometer, headset
- **③ Power management:** **UPS HAT (E)**, **4× 21700**, unified **5 V** rail
- **④ External communication:** **SIM7600G-H** to the backend and guardian app, plus SMS

**[RIGHT COLUMN / CONTENT FIELD 2]:**
- **Buses:** **UART** (ultrasonics) · **I²C** (IMU, compass, UPS gauge) · **CSI** (camera) · **USB** (modem, headset) · **GPIO** (buttons, motors, buzzer)
- **Arrow legend:** solid = data or control · thick = power · dotted = optional cloud path
- **Distributed but interconnected:** sensing, processing, power and communication are each separable for testing

**[SPEAKER NOTES]:**
"This block diagram consolidates the architecture into four subsystems. Reading left to right: the cane subsystem gathers proximity, image and button input and returns vibration and buzzer output. The vest subsystem processes everything through the Raspberry Pi 5, with the IMU and magnetometer on I²C. The power subsystem provides one unified rail from the UPS HAT. The communication subsystem, through the SIM7600G-H, links the device to the backend, the guardian application, and SMS. Each subsystem uses a distinct bus, UART, I²C, CSI, USB or GPIO, which let us validate each one independently on the bench before integration, as the methods section will show."

---

### [SLIDE NUMBER & TITLE]: 18 — Bill of Materials and Prototype Cost
**[TEMPLATE LAYOUT MAPPING]:** Data Table Matrix of the major cost items, with a total callout box on the right.

**[LEFT COLUMN / CONTENT FIELD 1]:**
| Item | Qty | Cost (₱) |
|---|---|---|
| **Raspberry Pi 5** | 1 | **8,000.00** |
| **SIM7600G-H** GSM/LTE/GNSS | 1 | **5,384.92** |
| **Pi Camera Module 3** | 1 | **1,731.18** |
| **DYP-A22** Ultrasonic | 2 | **1,718.78** |
| **21700 Li-ion** cells | 4 | **1,265.00** |
| Active Cooler | 1 | 582.00 |
| Micro SD card | 1 | 456.00 |
| Earphone / headset | 1 | 391.00 |
| Reflective vest · cane | 1 · 1 | 358.00 · 165.00 |
| MPU-6050 · Magnetometer | 1 · 1 | 183.00 · 125.00 |
| Remaining parts (cables, adapters, buttons, motor, buzzer, u-blox, passives, PCB) | — | 2,095.00 |

**[RIGHT COLUMN / CONTENT FIELD 2]:**
- **TOTAL: ₱22,454.88**
- **Compute + comms = ₱13,384.92 (≈ 60 %)** of the build
- Sensors and feedback parts are **low-cost** (₱45–₱1,719)
- ⚠ The BOM lists **u-blox GPS (₱219)** and **1 vibration motor (₱117)**. Reconcile with the build (items 2–3)
- ⚠ The Waveshare UPS HAT (E) has **no BOM line**. Add it

**[SPEAKER NOTES]:**
"The complete prototype cost twenty-two thousand four hundred fifty-four pesos and eighty-eight centavos. Sixty percent of that is the Raspberry Pi 5 and the SIM7600G-H modem: the compute needed to run vision and speech locally, and the cellular link needed for guardian monitoring. The sensors themselves are inexpensive. Two waterproof ultrasonic sensors, an IMU and a magnetometer together cost under two thousand five hundred pesos. This distribution matters for future cost reduction: the price falls with the compute platform and the modem, not with the sensing. A production version could trade the Pi 5 for a smaller module once the vision model is quantized."

---

## SECTION 7 — PROCESS FLOW & SOFTWARE LOGIC

### [SLIDE NUMBER & TITLE]: 19 — Runtime Concurrency Model: Never Block Safety
**[TEMPLATE LAYOUT MAPPING]:** Hub-and-Spoke Diagram. The main loop is the hub, and the named background threads are the spokes. Insert Fig. 5 (Call Hierarchy) or Fig. 6 (Main Program).

**[LEFT COLUMN / CONTENT FIELD 1]:**
- **One synchronous main loop** handles only cheap reads ⚑:
  - **MPU-6050 at 100 Hz** → fall detector
  - **Both DYP-A22** → obstacle warnings
- **Rule: the main loop never blocks** ⚑. Speech, network and vibration patterns all run off it

**[RIGHT COLUMN / CONTENT FIELD 2]:**
- **Fixed, named background threads** ⚑:
  - **Voice thread**, one per PTT press
  - **Announcer**, which owns all speech from the main loop
  - **Haptic pattern workers**, serialised by a mutex
  - **Heartbeat sender** · **telemetry retry** · **1 Hz GPS cache**
  - Button callbacks (gpiozero)
- **Why it matters ⚑:** inline speech once froze fall detection for **3–4 s per turn instruction**

**[SPEAKER NOTES]:**
"Before the flowcharts, the governing rule: the main loop never blocks. One loop reads the IMU at one hundred hertz and polls both ultrasonic sensors, and does nothing slow. Everything that can take time runs on its own named thread: speech output, voice commands, vibration patterns, the heartbeat, retries and the GPS cache. We learned this the hard way. In an early build, each spoken turn instruction played inline and halted fall detection and obstacle sensing for three to four seconds, every time. Moving speech to a dedicated announcer thread removed that gap entirely. A safety device cannot stop watching while it is talking."

---

### [SLIDE NUMBER & TITLE]: 20 — Startup Sequence: Safety Features First
**[TEMPLATE LAYOUT MAPPING]:** Horizontal Timeline: power on → boot clip → safety live → voice stack loading → greeting. Insert Fig. 7 (Startup) and Fig. 8 (Voice Stack Loader).

**[LEFT COLUMN / CONTENT FIELD 1]:**
- **T0: Power on.** A pre-rendered boot announcement plays **before any model loads** ⚑
- **T + seconds: Safety live** ⚑. IMU, ultrasonics, buttons, motors, telemetry and SMS are open, and **fall detection, obstacle warnings and SOS are active**
- **In parallel: Voice-stack thread** ⚑ loads Whisper, TTS, the intent parser and YOLO/OCR
- **Ready:** greeting + **battery percentage** spoken, and voice commands enabled

**[RIGHT COLUMN / CONTENT FIELD 2]:**
- **Why ⚑:** model loading took **~200 s** from the SD card, and **none** of the safety features need a model
- A PTT press before the stack is ready gets a **"busy" cue**, not silence
- A model that **fails to load still fails the process** loudly, which avoids a silent half-working device
- Startup diagnostics cover **battery**, **connectivity**, **GPS** and **sensor readiness**

**[SPEAKER NOTES]:**
"Startup is ordered by safety priority. At power-on, a pre-recorded announcement plays immediately, because silence from an assistive device is indistinguishable from failure. Within seconds, the inertial sensor, both ultrasonic sensors, the buttons, the motors and the alert path are live, so the user is protected while the heavier components load. The voice stack, comprising speech recognition, speech synthesis, the intent parser and the vision models, loads on a separate thread. That took about two hundred seconds from the SD card, and the safety features used to wait behind it. When the stack is ready, the device greets the user and announces the battery level."

---

### [SLIDE NUMBER & TITLE]: 21 — Active Multi-Sensor Scanning Loop
**[TEMPLATE LAYOUT MAPPING]:** 3-Box Process Flow: Read → Decide → Signal. Insert Fig. 9 (Main Loop) and Fig. 11 (Obstacle Feedback).

**[LEFT COLUMN / CONTENT FIELD 1]:**
- **Read:** IMU sample (**100 Hz**) and the latest **top/bottom** ultrasonic distances
- **Decide:**
  - Is the wearer **walking or still**? (chest IMU) ⚑
  - Closest obstacle → **proximity tier**
  - **Hysteresis band of 15 cm** ⚑ so cane sway does not cause false tier changes
- **Signal:** spawn a haptic pattern on a worker thread, **never inline** ⚑

**[RIGHT COLUMN / CONTENT FIELD 2]:** *Proximity rhythm (parking-sensor model) ⚑*
| Distance | Pattern |
|---|---|
| **> 200 cm** | Silent |
| **~100 cm** | **~1 pulse/s**, front motor |
| **< 50 cm** | **3–5 pulses/s**, **all 3 motors** |
| **< 30 cm** | **8 pulses/s** (maximum) |
- **80 ms** pulses, **rate rather than strength**, because skin adapts to steady buzzing
- **Standing still:** quiet, with a danger reminder every **15 s**

**[SPEAKER NOTES]:**
"The scanning loop runs read, decide and signal on every pass. It reads the IMU and the latest distances from both ultrasonic sensors. It then decides two things: whether the wearer is walking or standing, and how close the nearest obstacle is. The vibration encodes distance as pulse rate rather than strength, exactly like a car's parking sensor. It is silent beyond two metres, roughly one pulse per second at one metre, and up to eight per second inside thirty centimetres, with all three motors firing inside fifty. We chose rate because people judge rhythm far better than amplitude, and skin adapts to a steady buzz within seconds. A fifteen-centimetre hysteresis band prevents normal cane sway from causing false alerts."

---

### [SLIDE NUMBER & TITLE]: 22 — Push-to-Talk Voice Command Pipeline
**[TEMPLATE LAYOUT MAPPING]:** Horizontal Process Flow (five steps): Press → Record → Transcribe → Classify → Execute & Speak. Insert Fig. 15–17 (Voice Command, Intent Parsing, Intent Execution).

**[LEFT COLUMN / CONTENT FIELD 1]:**
- **① Press PTT (right):** a chime confirms, and recording starts
- **② Record:** the press again (or a timeout) stops it
- **③ Speech-to-text** ⚑: **English → Whisper tiny on device (1.13 s)** · **Tagalog → cloud Whisper large-v3-turbo**, with local fallback
- **④ Intent classification** ⚑:
  - **Embedding fast path** (~**52%** of utterances, ~**30 ms**)
  - → **Mistral (cloud)** → **Qwen 3 1.7B (local)** when offline
- **⑤ Execute + speak:** navigation, vision, status, time, language, emergency

**[RIGHT COLUMN / CONTENT FIELD 2]:**
- **Intents served** ⚑: `navigation.start/stop/progress/location` · `vision.describe` · `vision.read` · `device.status` · `place.save/list/locate` · `system.time/volume/language/help/shutdown` · `emergency.trigger` · `guardian.status_ok`
- **Camera wakes only on a vision intent**, never continuously
- **Working blip** if the answer takes **> 1.5 s** ⚑, so silence never reads as a crash
- **Repeat/Stop** cancels a command mid-pipeline ⚑

**[SPEAKER NOTES]:**
"A voice command follows five stages. The user presses push-to-talk, hears a chime and speaks. Speech is transcribed on the device for English in about one point one seconds. Tagalog, which local models handled poorly, goes to a cloud transcription server, with the local model kept as a fallback. The transcript is classified in three tiers. A fast on-device embedding matcher answers about half of all commands in thirty milliseconds; the rest go to a cloud language model, and to a local model if the cloud is unreachable. The intent then executes and the answer is spoken. The camera wakes only when the intent needs it, which protects battery life."

---

### [SLIDE NUMBER & TITLE]: 23 — Feedback Execution: Haptic and Audio Arbitration
**[TEMPLATE LAYOUT MAPPING]:** Two-Column Contrast: "Haptic Path" on the left, "Audio Path" on the right. Insert Fig. 23 (Speech Output) and Fig. 22 (Repeat/Stop).

**[LEFT COLUMN / CONTENT FIELD 1]:** *Haptic path*
- Short-lived **pattern worker threads**, **serialised by a mutex** ⚑
- Encodes **intensity only**: front motor = warning, all 3 = danger
- **Navigation never uses the motors** ⚑, because left and right motors in one handle feel identical
- Used for: **obstacle proximity**, and **SOS / fall alarm** (all 3 motors + buzzer)

**[RIGHT COLUMN / CONTENT FIELD 2]:** *Audio path*
- **Announcer thread** queues every main-loop message ⚑
- **Pre-rendered clips** ⚑: static messages are synthesised **once** and replayed from disk, and templated messages are cached
- **English → Piper (0.07–0.30 s)** · **Tagalog → cloud Filipino voice**, with **MMS fallback** ⚑
- **Critical messages interrupt** speech, even mid-synthesis ⚑
- **Repeat** replays the last message, and **Stop** cuts it off mid-sentence

**[SPEAKER NOTES]:**
"Feedback runs on two arbitrated paths. Haptic patterns run on short-lived worker threads under a mutex, so two warnings can never collide. Because all three motors are in the same handle, the hand feels one vibrator with three intensities, not three directions. So the motors carry proximity, and every navigation instruction is spoken. The audio path is owned by a single announcer thread. Static phrases are synthesised once and replayed from storage, which makes the emergency messages instant even with no network. Critical messages such as a fall or a dead battery interrupt whatever is playing. The repeat button replays the last message or, while the device is speaking, stops it."

---

### [SLIDE NUMBER & TITLE]: 24 — High-Priority Interrupts: Emergency and Fall
**[TEMPLATE LAYOUT MAPPING]:** Two-Column Contrast, with two trigger paths converging on one shared "Alert Delivery" box at the bottom. Insert Fig. 10 (Fall Detection), Fig. 20 (Emergency Alert) and Fig. 21 (Alert Delivery).

**[LEFT COLUMN / CONTENT FIELD 1]:** *Trigger A: Emergency button (front)*
- A gpiozero callback fires on its **own thread**, preempting nothing on the safety loop
- **Cancels any voice cycle** in progress ⚑
- **10 s re-arm** ⚑: a repeat press is still felt but does **not** double-notify the guardian, and the window **clears early if delivery failed**

*Trigger B: Fall detection (MPU-6050, two routes) ⚑*
- **Collapse:** **free fall < 0.5 g for ≥ 0.1 s** → **impact > 2.0 g within 0.5 s** → **stillness (σ < 0.15 g) for 2 s**
- **Trip:** **impact > 3.0 g** → **torso tilt > 50°** → **stillness**

**[RIGHT COLUMN / CONTENT FIELD 2]:** *Shared alert delivery*
- **Local alarm:** **buzzer + all 3 motors**, the **same alarm as the SOS button** ⚑
- **Spoken to the wearer:** "fall detected", so the user knows what was sent
- **Guardian:** **HTTPS event** with **GPS + timestamp** → dashboard / app
- **SMS** in parallel, retried for **5 min** ⚑
- **Voice "I'm safe now"** sends an **all-clear** to the guardian ⚑

**[SPEAKER NOTES]:**
"Two triggers bypass everything else. The emergency button fires on its own callback thread, cancels any voice command in progress, and starts delivery immediately. A second press within ten seconds is acknowledged but not re-sent, unless the first delivery failed. Fall detection runs two routes. A straight collapse appears as free fall, then impact, then stillness. A trip does not: a chest sensor in a trip pivots about the feet and never goes weightless, so the second route looks for impact, then a horizontal torso, then stillness. Both triggers produce the same response: buzzer and motors locally, a spoken confirmation, a GPS-tagged alert to the dashboard, and an SMS in parallel."

---

## SECTION 8 — METHODS & TESTING FRAMEWORK

### [SLIDE NUMBER & TITLE]: 25 — Engineering Planning and Design Methodology
**[TEMPLATE LAYOUT MAPPING]:** Circular Cycle / 4-Box Process Flow: Identify → Model → Develop → Test, with the Agile loop inside the Develop box. Insert Fig. 3 (Agile Model).

**[LEFT COLUMN / CONTENT FIELD 1]:**
- **Research design:** **engineering planning and design approach**
- **① Identify:** technical research + **unstructured in-person interviews**
- **② Model:** feature set, component selection, cane/vest split
- **③ Develop:** **Agile**, iterative, one feature at a time, then integrated
- **④ Test:** circuit → component → software → system

**[RIGHT COLUMN / CONTENT FIELD 2]:**
- **Sampling:** **purposive**, visually impaired residents of **Batangas / Lipa City**
- **Ethics:** **informed consent**, confidentiality, academic use only
- **Software discipline** ⚑:
  - **Unit tests** run on a Mac with **mocked hardware**
  - **Manual tests** run on the Pi for each wired component
- **Feature order:** object recognition, fall detection and audio/haptic feedback were each built and verified **before integration**

**[SPEAKER NOTES]:**
"We followed an engineering planning and design methodology in four stages. We identified the problem through technical research and in-person interviews with visually impaired residents, selected by purposive sampling with informed consent. We modelled a solution, choosing components and deciding the cane-and-vest split. We developed iteratively under Agile, building and verifying each feature on its own before integrating it. Every hardware module has a mock, so the full runtime is unit-tested on a laptop, and every physical component has a manual test script run on the device. Finally, we tested in four layers, from individual circuits up to the complete system in the field."

---

### [SLIDE NUMBER & TITLE]: 26 — Breadboard Verification to Universal PCB
**[TEMPLATE LAYOUT MAPPING]:** Two-Column Contrast with Before/After photos: breadboard (Fig. 24, First Prototype) on the left, perfboard/PCB and the mounted assembly (Fig. 25) on the right, joined by an arrow.

**[LEFT COLUMN / CONTENT FIELD 1]:** *Stage 1: Breadboard component verification*
- Each sensor and module verified **individually**: **pin configuration**, **signal transmission**, firmware response
- **Multimeter** checks for **voltage levels**, **continuity** and **current**
- Power distribution from the **UPS HAT (E)** verified under load
- Wiring faults (**loose, shorted, mis-wired**) caught **before** integration

**[RIGHT COLUMN / CONTENT FIELD 2]:** *Stage 2: Migration to a universal PCB*
- Transferred to a **5 × 7 cm universal PCB** with **soldered joints**
- **Why:** breadboard contacts **work loose under cane vibration and swing**
- **Mechanical trace durability** and **secure connections** for field use
- Motor drivers on board: **2N2222 NPN ×4**, **1N4007 ×4**, **1 kΩ / 10 kΩ** resistors
- Wiring documented in **`docs/hardware.md`**, the single source of truth ⚑

**[SPEAKER NOTES]:**
"Hardware was built in two stages. On a breadboard, we verified each component in isolation: correct pins, clean signals and expected firmware responses, confirmed with a multimeter for voltage, continuity and current. Once every module passed, we migrated the circuit to a universal PCB with soldered joints. The reason is mechanical. A cane is swung and tapped thousands of times per walk, and breadboard contacts loosen under exactly that vibration. The board carries the transistor and diode drivers for the motors. Every connection is recorded in one wiring document that serves as the single source of truth for the build."

---

### [SLIDE NUMBER & TITLE]: 27 — Magnetometer Calibration: Eliminating Magnetic Offsets
**[TEMPLATE LAYOUT MAPPING]:** 3-Box Process Flow: Collect → Fit → Verify. A circle-plot illustration (raw ellipse → corrected circle) sits on the right.

**[LEFT COLUMN / CONTENT FIELD 1]:**
- **① Collect:** QMC5883P **mounted on the vest**, calibrated **in its operating position**, rotated through **many orientations**
- **② Fit:** compute **hard-iron offsets** (centre shift) and scale correction from the X/Y/Z cloud
- **③ Verify:** heading compared against a **phone compass reference** at **N, NE, E, SE, S**
- **Recalibrate** when headings deviate, then re-test

**[RIGHT COLUMN / CONTENT FIELD 2]:**
- **Why on the vest:** nearby **metal, battery cells and the modem** distort the field, so calibration must include the mount
- **What it enables ⚑:**
  - **Turn-to-face** guidance before the first step (stop band **±15°**)
  - **Departure heading** passed to the router
  - **Missed-turn detection** within **~10 m** of walking
- Status: **`COMPASS_CALIBRATED = True`** on the assembled unit ⚑
- ⚠ **W, SW, NW** not yet verified (item 16)

**[SPEAKER NOTES]:**
"A magnetometer reads every nearby piece of metal and current as well as Earth's field. The vest carries a battery pack, a modem and a processor, so a factory calibration is meaningless here. We therefore calibrated the QMC5883P in its operating position on the vest, rotating it through many orientations and fitting the offsets that shift the measured ellipse back to a centred circle. We then compared headings against a phone compass. The calibrated compass enables turn-to-face guidance, with a fifteen-degree tolerance band, and detects a missed turn within about ten metres of walking. We acknowledge that only five of the eight compass points have been verified so far."

---

### [SLIDE NUMBER & TITLE]: 28 — Four-Layer Testing Framework
**[TEMPLATE LAYOUT MAPPING]:** 4-Step Staircase / Pyramid: Circuit → Component → Software → System (controlled, then real-world).

**[LEFT COLUMN / CONTENT FIELD 1]:**
- **L1 Circuit testing:** multimeter checks of voltage, continuity and current, plus UPS rail stability
- **L2 Component testing:** each module under **controlled conditions**, covering distance accuracy, image quality, GPS accuracy, IMU motion and feedback response
- **L3 Software testing:** platform features (**GPS tracking, SOS, notifications**), device logic, and **unstable-network** behaviour
- **L4 System testing:**
  - **Phase 1:** controlled environment
  - **Phase 2:** **real-world on-site** (Robinsons Lipa)

**[RIGHT COLUMN / CONTENT FIELD 2]:**
- **Pass criterion:** the actual result matches the expected result per test case, reported as **pass count / total**
- **Evidence:** **Tables 5–20** in Chapter 3, **20 tables in total**
- **Metrics:** detection accuracy, response, feedback consistency, delivery success
- **Pre- and post-interviews** for qualitative usability

**[SPEAKER NOTES]:**
"Testing proceeded in four layers, each gating the next. Circuit testing confirmed correct voltage and continuity. Component testing put each module through defined cases under controlled conditions. Software testing exercised the guardian platform and the device logic, including behaviour under an unstable network. System testing ran in two phases: first in a controlled environment, then on site with a visually impaired participant. Every test case defines an expected result in advance and is scored pass or fail against it, and we report the totals per module. The qualitative side, comfort and usability, came from interviews before and after the field trial."

---

## SECTION 9 — RESULTS: PRE-DEVELOPMENT SURVEY

### [SLIDE NUMBER & TITLE]: 29 — Interview Findings Driving Design Requirements
**[TEMPLATE LAYOUT MAPPING]:** Data Table Matrix with columns: Finding → Design Implication.

**[LEFT COLUMN / CONTENT FIELD 1]:**
| Finding (Table 3) | Design implication |
|---|---|
| Adults **31+**, Lipa City | **Simple, tactile controls** |
| **Mixed vision levels** | **Audio + vibration** together |
| Mostly **traditional cane** users | **Extend** the cane, don't replace it |
| Low confidence in **unfamiliar places** | **GPS guidance + audio** |
| Daily challenge: **identifying obstacles** | **Ultrasonic + object recognition** |
| History of **falls / dangerous incidents** | **Fall detection + emergency alert** |
| Want **distinct patterns per obstacle** | **Distinguishable feedback** |

**[RIGHT COLUMN / CONTENT FIELD 2]:**
- **Most requested features:** obstacle detection, object recognition, GPS assistance, emergency alerts
- **All four** are implemented in the prototype
- Participant suggestion → **distance encoded as vibration rate** ⚑

**[SPEAKER NOTES]:**
"Our interviews produced requirements, not just context. Participants were adults over thirty-one, so the controls had to be simple and tactile. Their vision ranged from shadow perception to none, so we committed to both audio and vibration rather than either alone. Most already used a cane, so we extended it rather than replacing it. Their stated challenges, identifying obstacles, unfamiliar places and falls, became the three core subsystems. They asked specifically for distinguishable feedback, which became our decision to encode distance in the vibration rate. Each row on this slide is a design decision we can trace back to a participant's words."

---

## SECTION 10 — RESULTS: BENCH VALIDATION (PASSED)

### [SLIDE NUMBER & TITLE]: 30 — Bench Validation: Ultrasonic Sensors 1 and 2
**[TEMPLATE LAYOUT MAPPING]:** Data Table Matrix of four test cases × two sensors, with green PASSED chips, plus a cone diagram showing the 35°–45° angled test.

**[LEFT COLUMN / CONTENT FIELD 1]:**
| Test case | Expected | Sensor 1 | Sensor 2 |
|---|---|---|---|
| **30 cm** detection | 30 cm | **30 cm · PASSED** | **30 cm · PASSED** |
| **60 cm** detection | 60 cm | **60 cm · PASSED** | **60 cm · PASSED** |
| **1 m** detection | 100 cm | **100 cm · PASSED** | **100 cm · PASSED** |
| **Angled 35°–45°** | Detected in cone | **Detected · PASSED** | **Detected · PASSED** |
| **Summary** | | **4/4 · 100%** | **4/4 · 100%** |

**[RIGHT COLUMN / CONTENT FIELD 2]:**
- **DYP-A22** on UART, powered and unobstructed
- Exact match at **all three distances** on **both sensors**
- **Off-axis detection confirmed at 35°–45°**, which **defines the forward cone** in our delimitations
- **Combined: 8/8 · 100%**
- ⚠ Manuscript typo: "100 **meters**" should be **100 cm** (item 9)

**[SPEAKER NOTES]:**
"Both DYP-A22 ultrasonic sensors were tested at thirty centimetres, sixty centimetres and one metre, and against an object placed thirty-five to forty-five degrees off the sensor axis. Both sensors read the exact expected distance in every case and detected the angled object, for eight of eight passes. Two points matter for interpretation. First, these distances span our entire warning range, from the first pulse to maximum alert. Second, the angled test is what defines our forward cone. It tells us where coverage ends, which is exactly why lateral sensors appear among our recommendations."

---

### [SLIDE NUMBER & TITLE]: 31 — Bench Validation: Buttons, Motors and Buzzer
**[TEMPLATE LAYOUT MAPPING]:** 3-Box Grid, one box per component family, each with a large "x/x · 100%" headline.

**[LEFT COLUMN / CONTENT FIELD 1]:**
- **Push Buttons 1, 2, 3: 2/2 each · 6/6 · 100%**
  - **Single press** → designated action triggered
  - **Idle** → **no false triggers**, no floating input
- **Vibration Motors: 4/4 · 100%**
  - **Activates** on trigger · **auto-off** after **2–3 s**
  - **Silent when idle** · **consistent across repeated cycles**, with no dropout or overheating

**[RIGHT COLUMN / CONTENT FIELD 2]:**
- **Emergency Buzzer: 6/6 · 100%**
  - **BUZ-001** activation on HIGH · **BUZ-002** silent on LOW
  - **BUZ-003** immediate on emergency
  - **BUZ-004** repeated alerts
  - **BUZ-005** ignores invalid input
  - **BUZ-006** recovers after power loss
- **Combined: 16/16 · 100%**

**[SPEAKER NOTES]:**
"The user-interface hardware passed every bench case. All three push buttons registered single presses reliably and, just as importantly, produced no false triggers when idle, which rules out floating inputs on the GPIO lines. The vibration motors activated on command, stopped on their own after the pattern ended, stayed silent when idle, and ran through repeated alert cycles without dropout or overheating. The buzzer passed six cases, including rejection of invalid signals and correct operation after power loss, which matters because it is the emergency output. In total, sixteen of sixteen. These are the components the user touches and relies on in an emergency."

---

### [SLIDE NUMBER & TITLE]: 32 — Bench Validation: SIM7600G-H and Guardian Platform
**[TEMPLATE LAYOUT MAPPING]:** Two-Column Contrast: the module test matrix on the left, the app test matrix on the right.

**[LEFT COLUMN / CONTENT FIELD 1]:** *SIM7600G-H: 9/9 · 100%*
- **SIM-001** power on · **SIM-002** SIM detected
- **SIM-003** **network registration**
- **SIM-004** weak-signal handling
- **SIM-005** **SMS send** · **SIM-006** SMS receive
- **SIM-007** **LTE data connection**
- **SIM-008** GNSS fix returned ⚠ (item 11)
- **SIM-009** **auto-reconnect** after interruption

**[RIGHT COLUMN / CONTENT FIELD 2]:** *Guardian App: 5/5 · 100%* · *Audio Feedback: 5/5 · 100%*
- **TC-APP-01** device ↔ app connection
- **TC-APP-02** **SOS notification received**
- **TC-APP-03** **live location displayed**
- **TC-APP-04** device status shown
- **TC-APP-05** alert delivered
- **TC-AUD-01–05:** output device, **TTS intelligibility**, object descriptions, alert notifications, **clarity**
- **Combined: 19/19 · 100%**

**[SPEAKER NOTES]:**
"The communication chain passed end to end. The SIM7600G-H powered up, recognised the SIM, registered on the network, sent and received SMS, opened an LTE data connection, and reconnected on its own after we interrupted the signal: nine of nine. On the guardian side, the application connected to the device, received the SOS notification, displayed the user's live location and device status, and received alert notifications: five of five. The spoken output path also passed all five cases for intelligibility and clarity. Together, these results validate the second engineering goal: IoT cellular notification from device to guardian."

---

### [SLIDE NUMBER & TITLE]: 33 — Calibration Results: Compass Heading Accuracy
**[TEMPLATE LAYOUT MAPPING]:** Data Table Matrix with columns Heading × Before Calibration × After Recalibration, plus a compass-rose graphic.

**[LEFT COLUMN / CONTENT FIELD 1]:**
| Heading | Initial | After recalibration |
|---|---|---|
| **N** | Heading deviation · **FAIL** | **N identified · PASS** |
| **NE** | Inconsistent · **FAIL** | **NE identified · PASS** |
| **E** | Wrong direction · **FAIL** | **E identified · PASS** |
| **SE** | Read as E/S · **FAIL** | **SE identified · PASS** |
| **S** | **Read as N** · **FAIL** | **S identified · PASS** |
| **Summary** | **0/5** | **5/5 · 100%** |

**[RIGHT COLUMN / CONTENT FIELD 2]:**
- **TC-MAG-01** detected on I²C · **TC-MAG-02** valid raw X/Y/Z · **TC-MAG-03** calibration applied: **all PASS**
- **The S → N inversion** is the textbook signature of an **uncorrected hard-iron offset**
- Calibration took heading identification from **0/5 to 5/5**
- **Remaining work:** **W, SW, NW** untested, and **degree-level error** not yet quantified against true bearings

**[SPEAKER NOTES]:**
"The compass results show why calibration is not optional. Before recalibration, all five tested headings were wrong, and south was reported as north. That one-hundred-eighty-degree inversion is the classic signature of a hard-iron offset, here from the battery pack and electronics on the vest. After recalibration in the mounted position, all five headings were identified correctly, from zero of five to five of five. We are careful about the limits of this claim. It is direction classification, not a measured error in degrees, and the western headings remain untested. Both gaps are clearly defined and are the next calibration step."

---

## SECTION 11 — RESULTS: BENCH VALIDATION (FAILED / LIMITATIONS)

### [SLIDE NUMBER & TITLE]: 34 — Limitation: MPU-6050 Long-Operation Consistency
**[TEMPLATE LAYOUT MAPPING]:** Two-Column Contrast, with the test matrix on the left (FAILED row highlighted) and the analysis on the right.

**[LEFT COLUMN / CONTENT FIELD 1]:** *MPU-6050: 8/9 · 88.89%*
- **PASSED:** **MPU-001** I²C init · **002** stationary stability · **003** movement · **004** rotation · **005** sudden motion · **006** disconnect detection · **007** vibration noise
- **MPU-008 Long operation (several hours): FAILED**
- **MPU-009 Long operation (repeat run): PASSED**
- **Verdict: mixed reliability** over continuous hours

**[RIGHT COLUMN / CONTENT FIELD 2]:** *Fall-motion trials (Gyroscope Testing)*
- **Full standing fall:** **not detected**
- **Partial fall:** **not detected**
- **Fall from push-up position:** **detected**
- **Reading:** a single-route (free-fall) detector catches **straight collapses**, not **trips**
- **Design response ⚑:** a second **impact → tilt > 50° → stillness** route, giving **3/3 falls, 7/7 daily activities** on **recorded traces** (offline replay, *not* live use)

**[SPEAKER NOTES]:**
"The MPU-6050 passed every functional case: initialisation, stability, movement, rotation, sudden motion, disconnection and vibration noise. It produced one failure and one pass on the same multi-hour continuous test, so we report its long-run reliability as mixed, not confirmed. The fall trials were more revealing. Our first detector missed a standing fall and a partial fall, and caught only a fall from a push-up position. The cause is physical: in a trip, a chest sensor rotates about the feet and never goes weightless, so a free-fall detector never fires. We added a second route based on impact and torso tilt, which caught all three recorded falls and rejected seven ordinary activities on replayed traces. Live confirmation is still pending."

---

### [SLIDE NUMBER & TITLE]: 35 — Limitation: Audio Input Capture Block
**[TEMPLATE LAYOUT MAPPING]:** Data Table Matrix of eight cases with the two FAILED rows highlighted, and a root-cause callout on the right.

**[LEFT COLUMN / CONTENT FIELD 1]:** *Audio Input/Output: 6/8 · 75%*
| Case | Result |
|---|---|
| AUD-001 Microphone detection | **PASSED** |
| **AUD-002 Low-volume capture** | **FAILED** |
| AUD-003 High volume, no clipping | **PASSED** |
| **AUD-004 Background-noise isolation** | **FAILED** |
| AUD-005 No false triggers in silence | **PASSED** |
| AUD-006 Clear playback | **PASSED** |
| AUD-007 Minimal response delay | **PASSED** |
| AUD-008 Device-disconnect handling | **PASSED** |

**[RIGHT COLUMN / CONTENT FIELD 2]:**
- **Failure 1:** a **soft voice is not captured** reliably
- **Failure 2:** **ambient noise is not filtered**, so street or mall noise reaches the transcriber
- **Probable cause:** **open-ear headset mic** sits **away from the mouth**, by design, to keep the ears free, and has **no noise suppression stage**
- **Impact:** lower **speech-to-text accuracy** → misheard commands
- **Mitigations in place ⚑:** too-short or empty recordings are **answered aloud**, never silently dropped

**[SPEAKER NOTES]:**
"The audio input block failed two of its eight cases, and they are related. It failed to capture low-volume speech, and it failed to isolate background noise. Both trace to the same design trade-off. We chose an open-ear headset so the user keeps hearing traffic, but its microphone sits farther from the mouth and has no noise-suppression stage. In a quiet room this is fine. In a busy public space, the transcriber receives a weaker voice inside more noise. The output side passed all its cases, including clean playback and safe handling of a disconnected device. Our recommendations address input specifically."

---

### [SLIDE NUMBER & TITLE]: 36 — Limitation: GPS Location Accuracy Drift
**[TEMPLATE LAYOUT MAPPING]:** Two-Column Contrast, with the test matrix on the left and a map screenshot on the right (Fig. 27, GPS Testing) showing a 10 m tolerance circle against the reported fix.

**[LEFT COLUMN / CONTENT FIELD 1]:** *GPS: 5/7 · 71.43%*
- **PASSED:** **TC-GPS-01** module detected · **02** satellite acquisition · **04** stable while stationary · **05** live updates while moving · **07** auto-recovery after obstruction
- **TC-GPS-03 Location retrieval: FAILED.** Fix at **13.9428247 N, 121.1458764 E** **deviated beyond the 10 m tolerance**
- **TC-GPS-06 Signal interruption: FAILED** ⚠ (the behaviour matched its expectation, item 12)

**[RIGHT COLUMN / CONTENT FIELD 2]:**
- **Receiver:** SIM7600G-H **integrated GNSS** ⚑ (⚠ item 2)
- **Why > 10 m matters:** pedestrian turns and building entrances are often **< 10 m apart**
- **Contributing factors:** antenna placement **on the body (vest)**, **multipath** near buildings, **cold-start** fix quality
- **Design response ⚑:** turn-to-face tolerance set to **±15°**, because the target bearing **inherits several metres of GPS error**
- **Stationary stability passed**, so the error is an **offset**, not jitter

**[SPEAKER NOTES]:**
"GPS passed five of seven cases. Detection, satellite acquisition, stationary stability, live tracking and recovery after obstruction all worked. The critical failure is accuracy: the reported fix deviated beyond our ten-metre tolerance. For a pedestrian that matters, because a turn or an entrance can be closer than ten metres. Since stationary readings were stable, the error is a consistent offset rather than noise, which points to antenna placement on the body and multipath near buildings. We designed around this where we could. The compass tolerance of fifteen degrees exists precisely because the bearing we compute already carries several metres of GPS uncertainty."

---

### [SLIDE NUMBER & TITLE]: 37 — Limitation: Object Recognition Under Variable Conditions
**[TEMPLATE LAYOUT MAPPING]:** Data Table Matrix of six cases with the FAILED row highlighted, and two example camera frames (good vs poor lighting) on the right.

**[LEFT COLUMN / CONTENT FIELD 1]:** *Camera / Object Recognition: 5/6 · 83.33%*
- **PASSED:** **TC-CAM-01** camera detected · **02** **voice-activated capture** · **03** image captured and processed · **04** **objects recognised and described** · **05** **description spoken**
- **TC-CAM-06 Different distances and lighting: FAILED.** Performance **varied with distance and light**

**[RIGHT COLUMN / CONTENT FIELD 2]:**
- **Model ⚑:** **YOLOv8m, Open Images V7** (~600 classes), **confidence ≥ 0.3** (⚠ item 4: paper says v8n)
- **Input:** **1280×720** frames from **Camera Module 3**
- **Failure mechanism:** small or distant objects shrink below the detector's resolution, and **low or harsh light** lowers confidence below the threshold
- **Graceful fallback ⚑:** when nothing is recognised, the device reports the **forward ultrasonic distance** instead ("something is about 40 cm away")
- **Pipeline works end to end.** **Robustness** is the gap

**[SPEAKER NOTES]:**
"The vision pipeline passed every functional stage. The camera initialised, a voice command activated it, images were captured and processed, objects were recognised and the description was spoken: five of five. It failed the robustness case. Recognition varied with distance and lighting. Distant objects occupy too few pixels for reliable detection, and poor or harsh lighting pushes confidence below our threshold. We designed for this failure. When the camera recognises nothing, the device does not say 'nothing there'. It reports the ultrasonic distance, so the user is never told a path is clear when it is not."

---

### [SLIDE NUMBER & TITLE]: 38 — Bench Validation Summary Matrix
**[TEMPLATE LAYOUT MAPPING]:** Data Table Matrix (full width) with a pass-rate bar per row, green ≥ 90%, amber 70–89%.

**[LEFT COLUMN / CONTENT FIELD 1]:**
| Module | Table | Passed / Total | Rate |
|---|---|---|---|
| Ultrasonic Sensor 1 | 5 | **4/4** | **100%** |
| Ultrasonic Sensor 2 | 6 | **4/4** | **100%** |
| Push Buttons 1–3 | 7–9 | **6/6** | **100%** |
| Vibration Motors | 10 | **4/4** | **100%** |
| Buzzer | 11 | **6/6** | **100%** |
| SIM7600G-H | 14 | **9/9** | **100%** |
| Audio Feedback | 18 | **5/5** | **100%** |
| Guardian App | 19 | **5/5** | **100%** |
| MPU-6050 | 13 | **8/9** | **88.89%** |
| Camera / Object Recognition | 16 | **5/6** | **83.33%** |
| Audio Input/Output | 12 | **6/8** | **75.00%** |
| GPS | 17 | **5/7** | **71.43%** |
| Magnetometer headings (post-cal.) | 15 | **5/5** | **100%** |

**[RIGHT COLUMN / CONTENT FIELD 2]:**
- **Aggregate (excluding magnetometer): 67/74 · 90.5%** *(computed from Tables 5–19)*
- **Every failure sits in a perception or environment-sensitive block**: audio input, GPS, vision, long-run IMU
- **Every safety-actuation block passed 100%**: buttons, motors, buzzer, SMS, app alerts

**[SPEAKER NOTES]:**
"This matrix consolidates the bench evidence. Across twelve modules, sixty-seven of seventy-four cases passed, about ninety and a half percent. The distribution matters more than the aggregate. Every component in the emergency chain passed completely: the buttons, the motors, the buzzer, the modem's SMS and data links, and the guardian application. Every failure sits in a block that perceives a noisy, variable world: microphone capture, satellite positioning, vision under changing light, and multi-hour IMU stability. That pattern is consistent with our architecture. The actuation path we control is reliable, and the perception path is where future work belongs."

---

## SECTION 12 — RESULTS: ON-SITE DEPLOYMENT

### [SLIDE NUMBER & TITLE]: 39 — On-Site Field Test: Robinsons Lipa
**[TEMPLATE LAYOUT MAPPING]:** Two-Column Contrast: protocol on the left, a field photo (Fig. 25, On-Site Testing) on the right.

**[LEFT COLUMN / CONTENT FIELD 1]:**
- **Venue:** **Robinsons Lipa**, with walking paths, indoor areas, people and fixtures
- **Participant:** **one adult** with visual impairment
- **Protocol:** **18 test cases (TC-ONS-01 to 18)** covering mobility tasks, obstacle approaches, voice commands, camera requests, GPS transitions, SOS simulation, simulated falls and extended use
- **Post-test interview** guided by the Appendix A instrument

**[RIGHT COLUMN / CONTENT FIELD 2]:**
- **Result: 17/18 · 94.44%**
- **Why this venue:** **accessible** for the participant, and **safer** than unfamiliar outdoor streets for a first field trial
- Realistic obstacles: **walls, chairs, displays, crowds**
- **Indoor-outdoor transitions** exercised GNSS loss and recovery
- **Threat to validity:** **n = 1** participant, a **single session**

**[SPEAKER NOTES]:**
"The field trial was held at Robinsons Lipa with one adult visually impaired participant, across eighteen defined test cases. We chose the venue deliberately. Travelling to an unfamiliar outdoor site poses real transport and safety risks for a visually impaired participant, and a mall offers realistic obstacles such as walls, displays, chairs and crowds, in a controlled and accessible setting. Moving between indoor and outdoor areas also let us observe GNSS loss and recovery. Seventeen of eighteen cases passed. We state the main threat to validity plainly: one participant in one session establishes feasibility, not generalisable performance."

---

### [SLIDE NUMBER & TITLE]: 40 — Usability Wins: Haptic Collision Avoidance
**[TEMPLATE LAYOUT MAPPING]:** 2x2 Grid of four field test cases, each with a participant quote or paraphrase.

**[LEFT COLUMN / CONTENT FIELD 1]:**
- **TC-ONS-03 Obstacle detection: PASSED.** Vibration alerts came **before any collision** with walls, chairs and displays
- **TC-ONS-04 Dynamic distance tracking: PASSED.** The participant **used the vibration to estimate obstacle distance** while walking toward and away from it

**[RIGHT COLUMN / CONTENT FIELD 2]:**
- **TC-ONS-05 Vibration comfort: PASSED.** Vibration was **comfortable and useful** for proximity
- **TC-ONS-01/02 Independent movement: PASSED.** "**Easy to use**", with **added awareness** in an unfamiliar place
- **Interpretation:** the **rate-encodes-distance** design was understood **without training**

**[SPEAKER NOTES]:**
"The strongest field result is the haptic channel. The participant received vibration alerts before every collision with walls, chairs and displays. More significantly, they used the vibration to judge how far away an obstacle was as they walked toward it and away from it. That is the exact behaviour the parking-sensor rhythm was designed to produce, and it was understood intuitively, without prior training. They described the vibration as comfortable and useful, and said that in an unfamiliar place the device gave them additional awareness. This validates our decision to put proximity on touch and keep speech for description."

---

### [SLIDE NUMBER & TITLE]: 41 — Usability Wins: Ergonomics, Controls and Connectivity
**[TEMPLATE LAYOUT MAPPING]:** 3-Box Process Flow, with three boxes: Wearability · Controls · Safety Link.

**[LEFT COLUMN / CONTENT FIELD 1]:**
- **Wearability: TC-ONS-16 PASSED.** The prototype was **lightweight and manageable**, and the **vest made it easier to carry**
- **Controls: TC-ONS-07 / 17 PASSED.** Buttons were **easily locatable by touch** and easy to press, including the **power switch**
- **Voice: TC-ONS-07 PASSED.** PTT command **recognised** and the function **activated**

**[RIGHT COLUMN / CONTENT FIELD 2]:**
- **Safety link: TC-ONS-13 PASSED.** **Emergency SOS** reached the **guardian application**
- **Tracking: TC-ONS-12 PASSED.** Guardian app **received updated location and status**
- **GNSS: TC-ONS-10 / 11 PASSED.** Location **recorded**, with **reconnection** after indoor/outdoor transitions
- **Endurance: TC-ONS-15 PASSED.** **No unexpected shutdowns** during the session (⚠ item 13: fix the note)
- **Camera: TC-ONS-08 PASSED.** **Helpful** for identifying objects ahead

**[SPEAKER NOTES]:**
"The remaining usability results validate the ergonomic and connectivity decisions. The participant found the system lightweight and manageable, and credited the vest for making it easier to carry, which is direct confirmation of the cane-and-vest split. All buttons, including the power switch, were found by touch without assistance. On the safety side, the SOS alert reached the guardian application, live location and status updates arrived, and GNSS reconnected across indoor-outdoor transitions. The hardware ran for the full session with no unexpected shutdown. The participant also found the camera helpful in principle, which brings us to the failures."

---

### [SLIDE NUMBER & TITLE]: 42 — Critical Failure: Computer Vision in Public Lighting
**[TEMPLATE LAYOUT MAPPING]:** Two-Column Contrast: "What failed" on the left, "Root cause analysis" on the right, under a red-accented FAILED banner.

**[LEFT COLUMN / CONTENT FIELD 1]:** *TC-ONS-09 Object recognition with common objects: FAILED*
- Test objects: **signs, chairs, tables, displays**
- Objects **not detected with high accuracy**
- Recognition **dropped significantly** under **public indoor lighting** and **depth/distance variation**
- **Public signs not read accurately**
- On **one or two occasions** a misdetection **affected the spoken description**
- Consistent with bench **TC-CAM-06 (FAILED)**

**[RIGHT COLUMN / CONTENT FIELD 2]:**
- **Lighting:** mall lighting creates **glare, reflections and back-lit displays**
- **Depth:** objects at varying range fall **below detector resolution**
- **Sign reading:** OCR needs **near-frontal, sharp, well-lit text**. Signs are **angled, distant and stylised**, and a blind user **cannot aim** the camera precisely
- **Compute:** a larger CPU model on the Pi limits **frame rate and retries** ⚑
- **Safety boundary held:** obstacle avoidance relies on the **ultrasonics**, not vision

**[SPEAKER NOTES]:**
"Object recognition in the field is our most significant failure, and we report it as such. With signs, chairs, tables and displays, accuracy fell markedly under public indoor lighting and at varying distances, signs were not read reliably, and on one or two occasions a misdetection changed the spoken description. There are three causes. Mall lighting produces glare and back-lit surfaces. Distant objects fall below the detector's effective resolution. And text reading needs a sharp, frontal view that a user without sight cannot easily aim for. The safety boundary held, however: no collision depended on vision, because obstacle avoidance is carried by the ultrasonic sensors."

---

### [SLIDE NUMBER & TITLE]: 43 — Edge Cases: Speech Accent and Fall Verification
**[TEMPLATE LAYOUT MAPPING]:** Two-Column Contrast: "Audio Assistant" on the left, "Fall Detection" on the right, each with a status chip.

**[LEFT COLUMN / CONTENT FIELD 1]:** *TC-ONS-06 Audio feedback: PASSED, with a qualification*
- The participant **could hear** the feedback, and it was **generally understandable**
- **The assistant's voice had a heavy accent**, which the participant flagged for improvement
- **Context ⚑:** **English** uses **Piper** on device · **Tagalog** uses a **cloud Filipino fine-tune**, falling back to **Meta MMS**, which is **markedly less natural**
- **Needed:** confirm **which language and voice** was active during the trial

**[RIGHT COLUMN / CONTENT FIELD 2]:** *TC-ONS-14 Fall detection: UNCONFIRMED*
- The system **triggered on simulated fall movements**
- **Accuracy was not confirmed** during **live, active use**
- The participant reported **real falls on raised road surfaces and humps**, which is the exact scenario the feature targets
- **Why it is unconfirmed:** a real fall **cannot ethically be induced** in a visually impaired participant
- ⚠ Present as **"triggered in simulation, accuracy unconfirmed"**, not as an unqualified PASS (item 13)

**[SPEAKER NOTES]:**
"Two further results need careful framing. The audio assistant was audible and understandable, but the participant noted a heavy accent. Our English voice runs on the device, while Tagalog uses a Filipino-trained cloud voice and falls back to a noticeably less natural local model when the network is weak, so a localised voice is a clear recommendation. On fall detection, the system responded to simulated falls, but we cannot claim accuracy in live use. The reason is ethical: we cannot ask a visually impaired participant to actually fall. Validating this feature properly needs controlled trials with sighted volunteers and padded surfaces, which we propose as future work."

---

### [SLIDE NUMBER & TITLE]: 44 — Post-Test Interview: Design Evaluation Summary
**[TEMPLATE LAYOUT MAPPING]:** Data Table Matrix: Evaluation Item × Participant Response × Finding.

**[LEFT COLUMN / CONTENT FIELD 1]:**
| Evaluation item (Table 4) | Participant response |
|---|---|
| **Overall experience** | **Generally positive** |
| **Buttons & controls** | **Easy to locate and operate by touch** |
| **Physical design & weight** | **Lightweight, manageable**, vest helps |
| **Obstacle detection** | **Appreciated**, helped navigation |
| **Audio clarity** | **Appreciated** |
| **Vibration feedback** | **Appreciated** |
| **Object recognition** | Liked the feature, **accuracy needs work** |
| **Emergency / fall** | Falls on **humps**, accuracy **unconfirmed** |
| **GPS / location** | Seen as useful, **no performance assessment** |

**[RIGHT COLUMN / CONTENT FIELD 2]:**
- **Most valued:** **obstacle detection, vibration, audio output, camera**
- **Requested improvements:** **object recognition accuracy** and **directional guidance**
- **Directional guidance** aligns with the **left/right sensing** recommendation, since the motors cannot convey side ⚑

**[SPEAKER NOTES]:**
"The post-test interview confirms the pattern in the quantitative results. The participant's overall response was positive, and the features they valued most were obstacle detection, vibration, audio output and the camera. Physical design and controls drew no complaints. Two improvements were requested: object recognition accuracy, which matches our bench and field failures, and directional guidance, meaning knowing which side an obstacle is on. That second request is significant, because our current hardware cannot provide it. Both sensors face forward and all motors share one handle. It directly motivates one of our recommendations."

---

## SECTION 13 — CONCLUSION

### [SLIDE NUMBER & TITLE]: 45 — Conclusion: Objectives Against Evidence
**[TEMPLATE LAYOUT MAPPING]:** Data Table Matrix: Objective × Evidence × Status, with green ACHIEVED chips and amber ACHIEVED (WITH LIMITS) chips.

**[LEFT COLUMN / CONTENT FIELD 1]:**
| Objective | Evidence | Status |
|---|---|---|
| **SO1** Sensor-equipped smart cane | Tables 5–6, 13–17 | **Achieved** |
| **SO2** Haptic + audio feedback | Tables 10–12, 18; TC-ONS-03–06 | **Achieved** |
| **SO3** AI object recognition (supplementary) | Table 16; TC-ONS-08/09 | **Achieved, accuracy limited** |
| **SO4** GPS outdoor navigation | Table 17; TC-ONS-10/11 | **Achieved, > 10 m drift** ⚠ item 14 |
| **SO5** Emergency response + location | Tables 11, 14, 19; TC-ONS-13 | **Achieved** |
| **SO6** Guardian web platform | Table 19; TC-ONS-12 | **Achieved** |

**[RIGHT COLUMN / CONTENT FIELD 2]:**
- **All six specific objectives were implemented and demonstrated** at the prototype level
- **Bench: 67/74 (90.5%)** · **On-site: 17/18 (94.44%)**
- **Safety-actuation chain: 100%** on the bench

**[SPEAKER NOTES]:**
"We conclude that all primary objectives were achieved at the prototype level, and this table shows the evidence for each. The sensor-equipped cane, the dual-channel feedback, the emergency response and the guardian platform are fully supported by passing tests. Object recognition and GPS navigation were implemented and demonstrated, but with measured accuracy limits that we have reported rather than hidden. Across the bench, ninety point five percent of cases passed; in the field, seventeen of eighteen. Most importantly, the components a user depends on in an emergency passed every test we ran."

---

### [SLIDE NUMBER & TITLE]: 46 — Conclusion: A Validated Multi-Modal Baseline
**[TEMPLATE LAYOUT MAPPING]:** 3-Box Process Flow with three "validated" claims, and a closing statement banner underneath.

**[LEFT COLUMN / CONTENT FIELD 1]:**
- **Validated 1: Multi-modal integration is feasible.** Sensing, vision, voice and cellular alerting run together on **one Raspberry Pi 5**
- **Validated 2: The ergonomic split works.** A **light cane + weighted vest** was rated comfortable in the field
- **Validated 3: Distributed safety works.** Local alarm, **HTTPS + SMS** to the guardian, and **offline survival** of safety features

**[RIGHT COLUMN / CONTENT FIELD 2]:**
- **Baseline established** for **user spatial safety**: forward obstacle cone, fall alerting, guardian visibility
- **Defined frontier:** vision robustness, GNSS accuracy, audio capture, fall verification
- **Contribution:** an **integrated architecture**, where the literature mostly offers **single-subsystem improvements**

**[SPEAKER NOTES]:**
"Beyond the objectives, the prototype validates three claims. First, multi-modal integration is feasible on a single embedded platform: sensing, vision, voice and cellular alerting coexist without compromising the safety loop. Second, the ergonomic split between a light cane and a weighted vest works, as the participant confirmed. Third, safety can be distributed: a local alarm, two independent channels to the guardian, and safety functions that survive a network outage. Together these establish a baseline for user spatial safety, with a clearly defined frontier. That is our contribution to a literature that has largely improved one subsystem at a time."

---

## SECTION 14 — RECOMMENDATIONS

### [SLIDE NUMBER & TITLE]: 47 — Recommendation 1: Quantized Computer Vision
**[TEMPLATE LAYOUT MAPPING]:** Two-Column Contrast: "Current" on the left, "Recommended" on the right, with an arrow between them.

**[LEFT COLUMN / CONTENT FIELD 1]:** *Current*
- **YOLOv8m** ⚑, **FP32 PyTorch** on the **Pi 5 CPU**
- **1280×720** input · conf **0.3**
- Field accuracy **dropped** in indoor light and with depth variation (**TC-ONS-09**)

**[RIGHT COLUMN / CONTENT FIELD 2]:** *Recommended*
- **Model quantization:** **INT8** export (e.g. **NCNN / ONNX Runtime / TFLite**) for **faster inference** on ARM
- Speed buys **multi-frame voting** (several frames per request), which raises **effective accuracy** without a bigger model
- Evaluate **YOLOv8n/s vs m** on a **local dataset** (Lipa signage, mall fixtures)
- **Fine-tune** on **locally collected images**; add **exposure / HDR** settings for glare
- Consider an **edge accelerator** (e.g. Raspberry Pi AI HAT) if the budget allows

**[SPEAKER NOTES]:**
"Our first recommendation targets the largest field failure. The current detector runs at full precision on the Pi's CPU, which limits how many frames we can analyse per request. Quantizing the model to eight-bit integers and exporting it to an ARM-optimised runtime would substantially shorten inference. That speed matters less for its own sake than for what it enables: analysing several frames and voting, which smooths over a single bad frame under glare. We also recommend benchmarking smaller model variants against a locally collected dataset of Lipa signage and indoor fixtures, and fine-tuning on it."

---

### [SLIDE NUMBER & TITLE]: 48 — Recommendation 2: Left and Right Sensing
**[TEMPLATE LAYOUT MAPPING]:** Diagram + Callouts. A top-down view of the user shows the current forward cone (35°–45°) next to the proposed forward + left + right coverage.

**[LEFT COLUMN / CONTENT FIELD 1]:**
- **Current:** **2 forward-facing ultrasonics** (top + bottom) cover only a **35°–45° cone**
- **Gap:** obstacles **beside** the user are **undetected**
- **Participant request:** **directional guidance** (Table 4)
- **Hardware truth ⚑:** **3 motors in one handle** are perceived as **one vibrator**, so side **cannot** be encoded today

**[RIGHT COLUMN / CONTENT FIELD 2]:**
- **Add lateral ultrasonics**, angled left and right, for **near-180° frontal coverage**
- **Relocate haptics off the handle**: **wrist bands** or **vest-shoulder motors** on separate bodies, so left and right are **physically distinguishable**
- Alternatively, use **spatial audio cues** (left/right ear) for side
- **Re-test** with an **angular coverage protocol** (0°, ±30°, ±60°, ±90°)

**[SPEAKER NOTES]:**
"Our second recommendation answers the participant's request for directional guidance. Today both ultrasonic sensors face forward, covering a cone of about thirty-five to forty-five degrees. We recommend adding angled left and right sensors. Detection alone is not enough, however, and this is a finding we want to emphasise. Our three motors sit in the same handle, and the hand cannot tell which one is vibrating. So directional feedback also requires moving the motors onto separate parts of the body, such as wrist bands or the vest's shoulders, or using left- and right-ear audio cues. A sensor upgrade without a feedback upgrade would detect the side but could not tell the user."

---

### [SLIDE NUMBER & TITLE]: 49 — Recommendation 3: Battery and Power Optimization
**[TEMPLATE LAYOUT MAPPING]:** 2x2 Grid of four optimisation levers.

**[LEFT COLUMN / CONTENT FIELD 1]:**
- **Measure first:** publish a **measured runtime** under **idle, walking, vision and alert** profiles (⚠ item 15)
- **Compute:** quantized vision (Rec. 1) and **CPU frequency governor** scaling at idle
- **Peripherals:** power-gate the **camera** between requests and duty-cycle the **SIM7600** where latency allows

**[RIGHT COLUMN / CONTENT FIELD 2]:**
- **Storage:** replace the **SD card** with **NVMe / high-endurance media**. Model loading took **~200 s** ⚑ and the card **failed read-back checks** ⚑
- **Gauge:** a **calibrated fuel-gauge curve** for the **4× 21700** pack (the raw gauge reads ~58% when empty ⚑)
- **Baseline:** **≈ 11.7 W typical** (Table 2 sum)
- **Target:** a **full day of use** on one charge

**[SPEAKER NOTES]:**
"Our third recommendation is power. The first step is measurement: a published runtime under defined usage profiles, which the current manuscript does not yet report. From the estimated baseline of about twelve watts, the main levers are compute and peripherals. Quantized vision reduces CPU load. The processor can scale down when idle, the camera can be fully powered off between requests, and the modem can be duty-cycled where alert latency allows. We also recommend replacing the SD card. Model loading from it took about two hundred seconds, and our card failed read-back verification, which threatens both boot time and data integrity."

---

### [SLIDE NUMBER & TITLE]: 50 — Recommendation 4: Adjustable Physical Cane Length
**[TEMPLATE LAYOUT MAPPING]:** Two-Column Contrast, with a height-range illustration of users at different heights holding the cane.

**[LEFT COLUMN / CONTENT FIELD 1]:**
- **Finding:** the participant identified the **overall dimensions of the cane** as needing improvement
- **Why length matters:** it sets the **sweep arc**, **wrist angle** and, critically, the **sensor aim**
- The ultrasonic heights (**ankle level and upper body**) shift with cane length and grip

**[RIGHT COLUMN / CONTENT FIELD 2]:**
- **Telescoping shaft** with **detented length stops**, sized to user height
- **Sensor mounts that hold their angle** across lengths, or **tilt-adjustable brackets**
- **Software:** a **per-user height setting** in `config.py` to rescale the obstacle thresholds
- **Harness:** cane-to-vest **cable slack** sized for the longest setting
- **Validate** with **multiple users of different heights**

**[SPEAKER NOTES]:**
"The fourth recommendation is mechanical. The participant identified the cane's overall dimensions as an area for improvement, and length has an electronic consequence as well as an ergonomic one. Cane length sets the angle at which the sensors meet the path, so a cane sized for one user aims its sensors wrongly for another. We recommend a telescoping shaft with fixed length stops, sensor brackets that hold their angle across lengths, and a per-user height setting so the obstacle thresholds scale with the geometry. This must be validated with several users of different heights, which ties into our broader recommendation for more participants."

---

### [SLIDE NUMBER & TITLE]: 51 — Recommendation 5: Localized, Natural Audio Models
**[TEMPLATE LAYOUT MAPPING]:** Two-Column Contrast: "Speech Output" on the left, "Speech Input" on the right.

**[LEFT COLUMN / CONTENT FIELD 1]:** *Speech output (accent)*
- Field finding: **heavy accent** (TC-ONS-06)
- Train or fine-tune a **Filipino-English and Tagalog voice** on **local speakers**
- Run it **on device**, so quality does not depend on the network ⚑ (the cloud Filipino voice currently falls back to **MMS**)
- **User-selectable voice and speaking rate**
- **Listening tests** with visually impaired users (MOS scoring)

**[RIGHT COLUMN / CONTENT FIELD 2]:** *Speech input (capture)*
- Bench failures **AUD-002** (low volume) and **AUD-004** (noise)
- **Noise suppression / beamforming** before transcription
- **Voice-activity detection** to trim silence and noise
- A **directional or boom microphone** that keeps **open-ear output**
- **Local Tagalog STT** that runs in **real time** (on-device Tagalog Whisper `small` runs at an **RTF of 2.23×** ⚑)

**[SPEAKER NOTES]:**
"Our fifth recommendation covers both directions of speech. On output, the participant noted a heavy accent. We recommend a voice trained on local Filipino and Tagalog speakers and, ideally, running it on the device, so its quality does not drop when the network does. That should be validated with listening tests by visually impaired users, the people who depend on it most. On input, the two bench failures, quiet speech and background noise, call for a noise-suppression and voice-activity stage before transcription, and a more directional microphone that still leaves the ear open. Local Tagalog transcription also needs to get faster than real time."

---

### [SLIDE NUMBER & TITLE]: 52 — Recommendation 6: Validation and Platform Extensions
**[TEMPLATE LAYOUT MAPPING]:** 2x2 Grid: Participants · Fall Validation · GNSS · Guardian App.

**[LEFT COLUMN / CONTENT FIELD 1]:**
- **More participants and environments:** move beyond **n = 1**, covering outdoor streets, night and rain
- **Fall detection validation:** controlled trials with **sighted volunteers on crash mats**, reporting **sensitivity / specificity**, plus **multi-hour IMU soak tests** (MPU-008)

**[RIGHT COLUMN / CONTENT FIELD 2]:**
- **GNSS accuracy:** **external active antenna** at the shoulder, measured **CEP against surveyed points**, and **sensor fusion** with IMU/compass dead-reckoning
- **Guardian app:** richer monitoring, **notification acknowledgement**, a guardian-friendly interface
- **Navigation test protocol:** a **turn-by-turn route test** to close the evidence gap on **SO4** (⚠ item 14)

**[SPEAKER NOTES]:**
"Our final recommendation group strengthens the evidence itself. First, more participants and more environments, including outdoor streets, night and rain, to move from feasibility toward generalisable performance. Second, a proper fall-detection study using sighted volunteers falling onto crash mats, reporting sensitivity and specificity, together with multi-hour soak tests to resolve the IMU's mixed long-run result. Third, GNSS accuracy measured against surveyed reference points, with an external antenna and dead-reckoning from the IMU and compass. Finally, a formal turn-by-turn navigation test, and continued development of the guardian application."

---

## SECTION 15 — CLOSING

### [SLIDE NUMBER & TITLE]: 53 — Thank You: Questions from the Panel
**[TEMPLATE LAYOUT MAPPING]:** Title Slide (closing variant): centred "Thank You", the project name below it, the authors and a prototype photo.

**[LEFT COLUMN / CONTENT FIELD 1]:**
- **Thank You**
- **IndepenSense:** IoT-Based Smart Cane with Computer Vision and Remote Guardian Monitoring
- **De La Salle Lipa · CITE · Computer Engineering Department**

**[RIGHT COLUMN / CONTENT FIELD 2]:**
- **Lubay, Cian Eythan Jeremy · Odi, Mearck Francis Voughn · Rivera, Katelyn Denise**
- **Group 5 · October 2026**
- *Prototype available for live demonstration*

**[SPEAKER NOTES]:**
"To summarise: IndepenSense integrates dual ultrasonic sensing, on-demand computer vision, inertial fall detection and cellular guardian monitoring into a single wearable system. Its safety chain passed every bench test, and in the field it gave a visually impaired participant usable, intuitive awareness of their surroundings. We have reported its limits as precisely as its successes: vision robustness, GPS accuracy, audio capture and unconfirmed live fall detection. Those limits define the next stage of this work. Thank you for your attention. The prototype is here for demonstration, and we welcome the panel's questions."

---

## BACKUP SLIDES (for Q&A, not presented)

### [SLIDE NUMBER & TITLE]: B1 — Theoretical Framework of IndepenSense
**[TEMPLATE LAYOUT MAPPING]:** Hub-and-Spoke Diagram. Insert Fig. 1 (Visual Theoretical Framework), with HAAT at the centre and four supporting theories around it.

**[LEFT COLUMN / CONTENT FIELD 1]:**
- **HAAT Model:** **Human** (visually impaired user) · **Activity** (independent mobility) · **Assistive Technology** (smart cane) · **Context** (physical and social, including guardians)
- **Multi-Sensor Data Fusion:** ultrasonic + camera + GPS + IMU are **complementary**, each covering another's blind spot

**[RIGHT COLUMN / CONTENT FIELD 2]:**
- **Edge/Hybrid Computing:** safety-critical work at the **edge**, heavy intelligence in the **cloud** when available
- **Cognitive Load Theory:** **filter and prioritise**, so only actionable information is delivered
- **Multimodal Interaction:** **haptic for urgency**, **audio for description**

**[SPEAKER NOTES]:**
"If the panel asks about our theoretical grounding: the HAAT model frames the device as a system of human, activity, technology and context, which is why guardian monitoring belongs inside the design rather than beside it. Multi-sensor fusion justifies combining sensors whose weaknesses are complementary. The edge-hybrid paradigm determines what must run locally, namely everything safety-critical. Cognitive Load Theory is why the device does not announce every detection. Multimodal Interaction Theory is why urgency goes to touch and description goes to speech, so the two channels never compete for the user's attention."

---

### [SLIDE NUMBER & TITLE]: B2 — Voice Intent Classification Performance ⚑
**[TEMPLATE LAYOUT MAPPING]:** Data Table Matrix + Bar Chart: cloud vs local accuracy per test group.

**[LEFT COLUMN / CONTENT FIELD 1]:**
- **Three-stage parser** ⚑: **embedding fast path → Mistral (cloud) → Qwen 3 1.7B (local)**
- **Fast path:** answers **~52%** of utterances in **~30 ms**, on device, for **closed intents only**
- **Benchmark:** **226 test utterances** across **English, Tagalog and adversarial** groups
- **Cloud 98.7%** vs **local 82.3%**
- **Adversarial group: 66.7% → 100%**

**[RIGHT COLUMN / CONTENT FIELD 2]:**
- **Cloud timeout 2.5 s**, then local fallback
- The fallback triggers on a **transport failure only**, never on a correct "unknown"
- **Cautious intents:** `system.shutdown`, `place.delete`, `guardian.status_ok`, and a *missed* `emergency.trigger`
- **Speech-to-text latency:** English Whisper tiny **1.13 s** on device · Tagalog Whisper small **5.29 s** locally (RTF **2.23×**) → cloud
- *Source: `llm_probe` / `latency_bench`, measured on the Pi; not yet in the manuscript*

**[SPEAKER NOTES]:**
"If asked how reliable voice commands are: classification is three-staged. A local embedding matcher answers about half of all commands in thirty milliseconds. The remainder goes to a cloud model, with a small local model as the fallback when offline. On our 226-utterance benchmark across English, Tagalog and adversarial phrasings, the cloud scored 98.7 percent against the local model's 82.3. The adversarial group, where a misclassification would trigger a real action, rose from 66.7 to one hundred percent. These figures come from the current build and should be added to the manuscript before being cited in the defense."

---

### [SLIDE NUMBER & TITLE]: B3 — Offline Behaviour and Graceful Degradation ⚑
**[TEMPLATE LAYOUT MAPPING]:** Data Table Matrix: Function × Online × Offline.

**[LEFT COLUMN / CONTENT FIELD 1]:**
| Function | Online | Offline |
|---|---|---|
| Obstacle warnings | ✔ | **✔** |
| Fall detection + local alarm | ✔ | **✔** |
| SOS buzzer + motors | ✔ | **✔** |
| Emergency SMS | ✔ | **✔** (needs cell signal, not data) |
| Routing + geocoding | ✔ | **✔** (GraphHopper + Photon on Pi) |
| English speech in/out | ✔ | **✔** |
| Tagalog speech | Cloud | Local fallback (slower, lower quality) |
| Intent parsing | Cloud 98.7% | Local 82.3% |
| Guardian dashboard | ✔ | ✘, buffered and retried |
| Open questions | ✔ | ✘, "needs internet" |

**[RIGHT COLUMN / CONTENT FIELD 2]:**
- **DNS stall fix:** **20 s** per lookup on a dead link → bounded to **2 s**
- **Circuit breaker:** a failed host is skipped for **30 s**, giving "one slow command, then local"
- **Route pre-check** answers in **~0.2 ms**, with no packets sent

**[SPEAKER NOTES]:**
"If asked what happens without a network: everything that protects the user keeps working. Obstacle warnings, fall detection, the local alarm and the SOS button are fully local, and SMS needs only cellular signal, not data. Routing and geocoding run on the Pi itself. English speech is on the device. What degrades is Tagalog speech quality, intent accuracy and the guardian's live dashboard, which buffers and retries. We also fixed a subtle failure: on a dying link, each name lookup hung for twenty seconds. Bounding it and skipping a failed host for thirty seconds turns that into one slow command, then local operation."

---

### [SLIDE NUMBER & TITLE]: B4 — Anticipated Panel Questions and Answers
**[TEMPLATE LAYOUT MAPPING]:** Two-Column Contrast: questions on the left, short answers on the right.

**[LEFT COLUMN / CONTENT FIELD 1]:**
- **Q1.** Why test an **outdoor-scoped** device **inside a mall**?
- **Q2.** Is **n = 1** enough to conclude usability?
- **Q3.** Fall detection marked PASSED but **unconfirmed**. Which is it?
- **Q4.** How long does the battery last?
- **Q5.** Why not vibrate **left/right** for navigation?
- **Q6.** Why a Raspberry Pi 5 and not a cheaper microcontroller?
- **Q7.** SIM-008 passed but TC-GPS-03 failed. Contradiction?

**[RIGHT COLUMN / CONTENT FIELD 2]:**
- **A1.** Participant **safety and accessibility**. Obstacle, vision and alert features are **location-agnostic**, and indoor/outdoor transitions **exercised GNSS recovery**
- **A2.** No. It establishes **feasibility**, and we list it as a **threat to validity** and recommend a larger study
- **A3.** It **triggered on simulated movements**, but **live accuracy is unconfirmed**, because a real fall cannot be ethically induced
- **A4.** *(Fill in the measured runtime.)* Estimated load ≈ **11.7 W**
- **A5.** All three motors share **one handle**, and the hand **cannot distinguish them**. Navigation is spoken
- **A6.** **Local vision and speech recognition** need an application processor. A microcontroller would push **all** of that to the cloud, and **offline** use would be lost
- **A7.** SIM-008 tested that a **fix is returned**, while TC-GPS-03 tested **accuracy**. They are different criteria (fix the wording, item 11)

**[SPEAKER NOTES]:**
"This slide is for preparation only and is not presented. Each answer is short, factual and concedes the limitation before defending the decision, which is the posture a panel respects. The most likely pressure points are the single participant, the indoor venue for an outdoor-scoped system, the fall-detection status, and the missing runtime figure. Rehearse these four until each answer is under twenty seconds. If a panel member identifies an inconsistency that is listed in the errata table at the top of this document, acknowledge it directly, state the corrected value, and note that the manuscript will be amended."
