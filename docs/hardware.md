# Hardware Reference

Quick-look wiring guide for assembling or re-testing the IndepenSense hardware.
Update this file every time a component's wiring changes.

Components are listed in **assembly order** — the order you would wire them on
the bench. Each section opens with its pin list; explanation, caveats and
manual tests come after, so you never have to read prose to find a pin.

---

## Pin index

Every occupied pin on the 40-pin header, in physical pin order. Find your pin
here, then read that component's section.

```
Pin 1  (3V3)              DYP-A22 TOP          VCC   — also feeds the 3.3 V rail
Pin 2  (5V)               MPU6050              VCC   — and the motors' 5 V rail
Pin 3  (GPIO 2 / SDA)     shared I2C1          SDA   — MPU6050, compass, UPS HAT
Pin 4  (5V)               Perfboard
Pin 5  (GPIO 3 / SCL)     shared I2C1          SCL   — MPU6050, compass, UPS HAT
Pin 6  (GND)              DYP-A22 TOP          GND
Pin 8  (GPIO 14 / TX)     DYP-A22 TOP          RX
Pin 9  (GND)              MPU6050              GND
Pin 10 (GPIO 15 / RX)     DYP-A22 TOP          TX
Pin 11 (GPIO 17)          Vibration motor      FRONT
Pin 12 (GPIO 18)          Active buzzer        +
Pin 13 (GPIO 27)          Vibration motor      RIGHT
Pin 14 (GND)              QMC5883P compass     GND
Pin 15 (GPIO 22)          Vibration motor      LEFT
Pin 16 (GPIO 23)          Button               PTT
Pin 17 (3V3)              DYP-A22 BOTTOM       VCC
Pin 18 (GPIO 24)          Button               EMERGENCY
Pin 22 (GPIO 25)          Button               REPEAT / STOP
Pin 30 (GND)              DYP-A22 BOTTOM       GND
Pin 32 (GPIO 12 / TX)     DYP-A22 BOTTOM       RX
Pin 33 (GPIO 13 / RX)     DYP-A22 BOTTOM       TX
```

Free GND pins for the shared ground rail: **20, 25, 34, 39**.

**Shared rails.** Both 3.3 V pins (1 and 17) are consumed by the two DYP-A22s,
but the three buttons and the compass also need 3.3 V. The build therefore has
a distributed 3.3 V rail — splice into it rather than hunting for a free header
pin. Same for SDA/SCL: the MPU6050, compass and UPS HAT share the same two
wires.

**Critical:** DYP-A22 is a **3.3 V** sensor. Wiring it to a 5 V pin will
damage it. The compass is the same — it is the one component most likely to be
destroyed by copying the MPU6050's Pin 2.

## Raspberry Pi 5 — 40-pin GPIO header

```
       3V3  (1) (2)  5V
     GPIO2  (3) (4)  5V
     GPIO3  (5) (6)  GND
     GPIO4  (7) (8)  GPIO14 / UART0 TX
       GND  (9) (10) GPIO15 / UART0 RX
    GPIO17 (11) (12) GPIO18
    GPIO27 (13) (14) GND
    GPIO22 (15) (16) GPIO23
       3V3 (17) (18) GPIO24
    GPIO10 (19) (20) GND
     GPIO9 (21) (22) GPIO25
    GPIO11 (23) (24) GPIO8
       GND (25) (26) GPIO7
     ID_SD (27) (28) ID_SC
     GPIO5 (29) (30) GND
     GPIO6 (31) (32) GPIO12
    GPIO13 (33) (34) GND
    GPIO19 (35) (36) GPIO16
    GPIO26 (37) (38) GPIO20
       GND (39) (40) GPIO21
```







**Power rails:**
- 3.3V → pins 1, 17
- 5V → pins 2, 4
- GND → pins 6, 9, 14, 20, 25, 30, 34, 39

## Status vocabulary

These mean different things and the difference matters when deciding what
still needs testing:

| Status | Means |
|---|---|
| `working` | wired **and** confirmed good by its manual test on the prototype |
| `wired` | physically connected, manual test not yet run — assume nothing |
| `wired, calibration outstanding` | connected and reading, but its numbers are not yet trustworthy |

Everything is wired as of 2026-09-13. What remains is running each manual
test on the assembled unit and promoting `wired` to `working` — or finding
out why it cannot be.

---

# 1. DYP-A22 Ultrasonic — TOP sensor — STATUS: working

UART port: `/dev/ttyAMA0` (UART0, default Pi UART).
Baud: 115200.

```
Pin 1  (VCC)      3.3 V — NOT 5 V
Pin 6  (GND)
Pin 8  (RX)       sensor RX ← Pi TX
Pin 10 (TX)       sensor TX → Pi RX
```

RX and TX cross over: the label is the *sensor's* pin, so the sensor's RX goes
to the Pi's TX and vice versa.

Cane-mounted, forward-facing, positioned high on the cane to detect
head-level obstacles (branches, low signage, awnings). This sensor
provides the wearable's unique value — the user's cane already sweeps
low obstacles by touch, but nothing else catches head-level danger.

Port configurable via `DYP_A22_TOP_PORT` in `indepensense.config`.

# 2. DYP-A22 Ultrasonic — BOTTOM sensor — STATUS: working

UART port: `/dev/ttyAMA4` (UART4).
Baud: 115200.

```
Pin 17 (VCC)      3.3 V — NOT 5 V
Pin 30 (GND)
Pin 32 (RX)       sensor RX ← Pi TX
Pin 33 (TX)       sensor TX → Pi RX
```

Cane-mounted, forward-facing, positioned low on the cane to detect
foot-level obstacles (curbs, planters, walls). Supplements what the
cane already senses by touch — advance warning at ~1 m.

UART4 does not exist until `dtoverlay=uart4` is in
`/boot/firmware/config.txt` — see the one-time setup section at the end.

Port configurable via `DYP_A22_BOTTOM_PORT` in `indepensense.config`.

Manual tests:

```bash
python -m indepensense.sensors.tests.manual.single_dyp_test   # top only
python -m indepensense.sensors.tests.manual.dual_dyp_test     # top + bottom
```

# 3. Push Buttons (3x, KY-004 style) — STATUS: working

Each button needs three wires — VCC and GND tap the shared rails, OUT goes to
its own GPIO:

```
Push-to-talk (PTT)          left on the enclosure
    3.3 V rail  (VCC)
    GND rail    (GND)       pins 20, 25, 34 or 39
    Pin 16      (OUT)       GPIO 23

Emergency                   position unrecorded
    3.3 V rail  (VCC)
    GND rail    (GND)
    Pin 18      (OUT)       GPIO 24

Repeat / stop speech        position unrecorded
    3.3 V rail  (VCC)
    GND rail    (GND)
    Pin 22      (OUT)       GPIO 25
```

VCC is the shared 3.3 V rail, not a header pin — pins 1 and 17 are taken by
the two DYP-A22s.

Three identical breakout-mounted buttons. Each module has an on-board
10 kΩ pull-down resistor and drives OUT HIGH when pressed (active-high
logic), which is the opposite of a bare tactile switch. The driver
(`src/indepensense/feedback/gpio_button.py`) configures gpiozero for
active-high pull-down accordingly.

The third button carries two meanings, decided by whether the wearable is
currently speaking: a press interrupts speech in progress, and otherwise
replays the last response. They are companions rather than a compromise —
both concern the last thing the device said, and there is no state in
which the user wants both. A dedicated stop button was never an option
anyway; all three were assigned before the enclosure was fabricated.

All three pins are configurable via `PTT_BUTTON_GPIO`, `EMERGENCY_BUTTON_GPIO`,
and `REPEAT_BUTTON_GPIO` in `indepensense.config`.

### Physical position is spoken aloud — keep it true

Positions are **body-relative: as worn, user facing forward** — the same
frame the three vibration motors use (front / right / left below). A
position is meaningless without a frame, and the user cannot look down to
resolve an ambiguous one.

The PTT position is not merely documentation. The wearable reads it out
when it asks the user to confirm a destination:

> "Jollibee Lipa City, 400 meters away. Press the **left** button to
> confirm, or wait to cancel."

That word comes from the `button.ptt_position` key in
`src/indepensense/intents/messages.py`, in both English and Tagalog. **If
the enclosure is rebuilt and PTT moves, change that key** — otherwise the
device confidently sends a blind user to press the emergency button. The
key exists separately from the sentences that use it precisely so this is
one edit rather than a hunt.

Emergency and Repeat positions are left blank rather than guessed: nothing
currently speaks them, and a wrong value here is worse than a missing one.
Fill them in from the physical prototype when convenient.

Manual test:

```bash
python -m indepensense.feedback.tests.manual.button_test           # PTT pin
python -m indepensense.feedback.tests.manual.button_test 24        # any pin
```

# 4. Vibration Motors (3x) — STATUS: wired

The GPIO drives a transistor base, never the motor directly:

```
Front (turn ahead)
    Pin 11      GPIO 17 → 1 kΩ resistor → NPN base

Right (turn right)
    Pin 13      GPIO 27 → 1 kΩ resistor → NPN base

Left (turn left)
    Pin 15      GPIO 22 → 1 kΩ resistor → NPN base
```

Directional cueing, body-relative as worn. Each motor needs its own NPN
transistor circuit because the motors draw 60-100 mA each — well above the
Pi's per-pin GPIO source limit (~16 mA).

**Per-motor circuit (repeat 3 times):**

```
Motor +     → 5V rail (Pi physical pin 2 or 4)
Motor −     → NPN transistor collector (2N2222 or 2N3904)
NPN emitter → GND rail
NPN base    → 1 kΩ resistor → Pi GPIO (pin 11 / 13 / 15)
Flyback diode (1N4001):
    cathode (striped end) → Motor +
    anode                 → Motor −
```

The flyback diode is not optional — the reverse voltage spike when a
motor stops can otherwise destroy the transistor or the Pi's GPIO.

Pins configurable via `VIBRATION_FRONT_GPIO`, `VIBRATION_RIGHT_GPIO`,
and `VIBRATION_LEFT_GPIO` in `indepensense.config`.

Manual test:

```bash
python -m indepensense.feedback.tests.manual.vibration_test
```

# 5. Active Buzzer — STATUS: working (judged too loud — see `docs/deferred.md`)

```
Pin 12   (+)      GPIO 18 — PWM-capable, useful later if swapped for a passive buzzer
GND rail (−)      pins 20, 25, 34 or 39
```

Standard hobby active buzzer, driven directly from a GPIO pin. GPIO HIGH
sounds the tone; LOW is silent. Active buzzers contain their own
oscillator so no PWM is needed.

Pin configurable via `BUZZER_GPIO` in `indepensense.config`.

Current draw caveat: most hobby active buzzers pull 15-25 mA at 3.3 V,
which is at the edge of the Pi's per-pin GPIO source limit (~16 mA). If
`vcgencmd get_throttled` shows non-zero after adding the buzzer, add an
NPN transistor between the GPIO and the buzzer's + pin (same pattern as
the vibration motors above).

Manual test:

```bash
python -m indepensense.feedback.tests.manual.buzzer_test              # default GPIO 18
python -m indepensense.feedback.tests.manual.buzzer_test 21           # any pin
```

# 6. MPU6050 IMU — STATUS: working

I²C device on the Pi's primary I²C bus (I2C1) at address `0x68`.

```
Pin 2 (VCC)     VCC     5 V — this board has an on-board regulator
Pin 9 (GND)     GND
Pin 3 (GPIO 2)  SDA     shared with the compass and the UPS HAT
Pin 5 (GPIO 3)  SCL     shared
```

Used by the fall detector at 100 Hz sample rate. ±8 g accelerometer range
configured in the driver. Shares the I²C bus with the compass (`0x2C`) and
the Waveshare UPS HAT (`0x2D`) — all three addresses are distinct, so no
conflict.

**Do not copy the Pin 2 (5 V) line to the compass.** The MPU6050 tolerates it
because of its regulator; most compass breakouts do not. See the next section.

Address configurable via `MPU6050_ADDRESS` in `indepensense.config`.

Manual test:

```bash
python -m indepensense.sensors.tests.manual.single_mpu6050_test
```

# 7. QMC5883P magnetometer — STATUS: wired, calibration outstanding

Standalone 3-axis compass on I2C1 at address **`0x2C`**. Independent of the
IMU: it shares only the SDA/SCL wires, so it appears in `i2cdetect`
immediately, with no host-side setup needed.

```
3.3 V rail      VDD     ⚠️ NOT Pin 2 (5 V). Pins 1 and 17 are taken by the
                           DYP-A22s — tap the shared 3.3 V rail.
Pin 14 (GND)    GND     or any free GND: 20, 25, 34, 39
Pin 3 (GPIO 2)  SDA     shared with the MPU6050 and the UPS HAT
Pin 5 (GPIO 3)  SCK     shared. Labelled SCK on this part, = SCL
                DRDY    not connected
```

**⚠️ Power it from 3.3 V, NOT Pin 2.** The MPU6050 section above uses Pin 2,
which is 5 V — that board has a regulator, GY-271-style compass breakouts
often do not, and most pass SDA/SCL through **unshifted**. Copying the
MPU6050 pin list verbatim is the most likely way to destroy this sensor.
3.3 V is safe on either board variant: the bare chip runs at 2.5-3.6 V, and a
board that does carry an LDO still passes 3.3 V through fine.

Two of the four wires are **taps onto rails that already exist**, not free
header pins — the Pi's only two 3.3 V pins (1 and 17) are already taken by the
two DYP-A22s, and the three push buttons already need 3.3 V, so the build has
a distributed 3.3 V rail regardless. Splice into it; do the same for SDA/SCL,
which the MPU6050 is already on.

No level shifter and no I²C address conflict: `0x2C` (compass), `0x68` (IMU)
and `0x2D` (UPS HAT) are distinct — note `0x2C` and `0x2D` are adjacent but
not colliding — and everything on this bus is 3.3 V logic.

Pull-up caveat: the Pi has fixed 1.8 kΩ pull-ups on GPIO 2/3, and each
breakout adds its own (typically 4.7 kΩ). Three devices in parallel pull the
effective resistance to roughly 1 kΩ, near the point where a device can't
sink enough current to drive the line low. If the bus turns flaky after
adding this module — dropped reads, `i2cdetect` showing addresses
intermittently — remove the two pull-up resistors on the compass breakout
rather than the Pi's (which are not adjustable).

### Nothing acts on the heading yet, by design

`config.COMPASS_CALIBRATED` is `False`, which makes `App.trusted_heading()`
return `None` and leaves every consumer behaving as it did before the compass
existed. The driver still opens and the reading is still cached —
`App.latest_heading()` and the manual tests below show it — but routing will
not use a bearing that has not been verified on the assembled unit.

Until it is set True, three built features stay inert by design:
turn-to-face guidance, the departure heading sent to the router, and turn
verification.

Flip it only after steps 1-4 in the `COMPASS_CALIBRATED` comment in
`config.py`: fix the axis roles, run the calibration sweep, paste the
values, and check all four cardinals against a phone compass.

Verified on the bench: chip ID `0x80`, both control registers holding, and a
horizontal field of 41.7 μT measured from a flat rotation sweep against ~40 μT
expected for Manila — which validates the ±8 G / 3750 LSB/G conversion
independently of the datasheet.

### The part is a QMC5883P, not the QMC5883L the listing claimed

The board was bought as a "QMC5883L Electronic Compass Module"; `i2cdetect`
answered at `0x2C`, which is the QMC5883P. QST ships at least three parts
under this family name and they share nothing but the marketing:

| Part | Addr | Chip ID | Data regs | Status | ±8 G sensitivity |
|---|---|---|---|---|---|
| QMC5883**P** (ours) | `0x2C` | `0x00` → `0x80` | `0x01`-`0x06` | `0x09` | 3750 LSB/G |
| QMC5883**L** | `0x0D` | `0x0D` → `0xFF` | `0x00`-`0x05` | `0x06` | 3000 LSB/G |
| HMC5883L (Honeywell) | `0x1E` | `0x0A` → `'H48'` | `0x03`-`0x08` | `0x09` | n/a |

The address is what identifies the part — the silkscreen (GY-271, GY-273,
"HMC5883L") does not. `sensors/qmc5883p.py` verifies chip ID `0x80` at
construction and refuses to open otherwise; the app then runs without a
compass and prints the reason, rather than reporting a heading that never
moves.

**Why a separate chip at all.** The plan was an MPU9250, whose package
contains an AK8963 magnetometer beside the accel + gyro. The module that
arrived is a relabelled MPU6500 with no magnetometer die — a common
counterfeit. Its accel + gyro half still works as an MPU6050 (`0x68`,
byte-compatible), but heading had to move to a dedicated part. To check
whether an "MPU9250" is genuine, read `WHO_AM_I` (`0x75`): `0x71` = MPU9250,
`0x73` = MPU9255, `0x70` = MPU6500 (no compass), `0x68` = MPU6050.

### Mount orientation is configuration, not a fixed assumption

Heading uses the two field components that are horizontal once the board is
fixed in place, and which axes those are depends on how it is mounted:

| | Board lying flat (bench) | Board upright (vest back) |
|---|---|---|
| x | horizontal — left/right | horizontal — left/right |
| y | horizontal — front/back | **vertical** — up/down |
| z | **vertical** — up/down | horizontal — front/back |

`MAG_FORWARD_AXIS` and `MAG_LEFT_AXIS` in `config.py` name them, as a letter
with an optional sign (`"+x"`, `"-z"`). Defaults are `"+x"` / `"+y"`, correct
for a board lying flat. The planned mount is **upright on the back of the
vest**, which puts the board normal (z) front-to-back and makes y vertical —
so heading will come from z and x, with the signs depending on which face
points outward.

Determine the signs on the assembled unit, away from metal:

1. **Confirm which axis is the board normal.** Rotate the unit about the
   vertical axis (as if the wearer were turning on the spot). Two axes trace a
   circle; the third barely moves. The one that barely moves is vertical, and
   it is the one heading must *exclude*.
2. **Find forward.** Face the unit at magnetic north (phone compass is close
   enough). Whichever remaining axis reads its largest positive value is
   `+forward`; if the largest value is negative, it is `-forward`.
3. **Find left.** Turn 90° to the right, so north is now on the unit's left.
   The other horizontal axis now carries the field; its sign gives
   `MAG_LEFT_AXIS`.
4. **Verify.** Run `single_magnetometer_test`. Turning right must make the
   heading *increase* (N→E→S→W = 0→90→180→270). If it decreases, one sign is
   wrong — flip `MAG_LEFT_AXIS`.

Step 4 is not optional. A flipped sign mirrors the heading rather than
rotating it, so no offset can compensate, and a mirrored compass reads
plausibly while sending the user the wrong way.

### Calibration is required before heading means anything

`MAG_OFFSET_X/Y/Z` and `MAG_SCALE_X/Y/Z` in `config.py` are still at identity
values. One 30 s rotation sweep produces both: offsets cancel hard-iron bias
(constant pull from the motor magnets, battery pack, Pi), scales cancel
soft-iron distortion (the field sphere stretched into an ellipsoid, which
makes heading error depend on which way you face). Re-run whenever the
physical layout changes — batteries moved, motor added, any ferromagnetic
part relocated. Calibrate away from desks, speakers and steel furniture.

Known limitations: no tilt compensation (heading degrades when the cane is
off-vertical) and no magnetic declination applied, so this reports *magnetic*
north, not true north.

Configurable via `MAG_I2C_BUS`, `MAG_ADDRESS` and `HEADING_CHECK_INTERVAL_S`
in `indepensense.config`. The chip runs normal mode at ±8 G, 10 Hz, maximum
oversampling (set in the driver — see its docstring for the reasoning);
`app.py` samples the cached heading at 2 Hz.

Manual tests:

```bash
python -m indepensense.sensors.tests.manual.single_magnetometer_test
python -m indepensense.sensors.tests.manual.magnetometer_calibrate
```

---

# Not on the GPIO header

These use no header pins at all, which is why they are separated from the
numbered list above — nothing here can conflict with the wiring you just did.

## Waveshare UPS HAT (E) — STATUS: working

**Mounts UNDER the Pi via pogo pins** — spring-loaded contacts on the
HAT touch test points on the Pi's underside. No GPIO header pins are
used, so it doesn't conflict with any sensor/actuator wiring. The HAT
also delivers 5 V power to the Pi (replaces the USB-C power supply).
Its fuel gauge appears on I2C1 at address `0x2D`.

Battery power + fuel gauge for the wearable. Four 21700 Li-ion cells
in a 4S1P configuration (nominal ~14.4 V, full charge ~16.8 V) via a
proprietary I²C fuel gauge.

In 1P the pack's charge capacity equals a *single* cell's — the series
wiring multiplies voltage, not mAh. The gauge divides by a fixed
capacity of ~4750 mAh to produce its `percentage`, so if the installed
cells hold less than that, the reported percentage is optimistic by
exactly that ratio. See the module docstring in
`src/indepensense/power/tests/manual/single_ups_test.py`.

Exposes via I²C (see `src/indepensense/power/waveshare_ups_e.py`):

- **Battery voltage, current** (signed: + discharge, − charge)
- **Percentage** (fuel-gauge-computed, not linearly interpolated)
- **Per-cell voltages** (all four cells individually — useful for
  detecting cell imbalance)
- **Charging state** (idle / charging / fast-charging / discharging)
- **Time to empty / time to full** (fuel-gauge estimates)

Under-voltage protection: the HAT enforces its own shutdown when any
cell drops below ~3.15 V for ~60 s. Our software fires a `Low Battery`
alert to the guardian dashboard when the reported percentage drops
below `LOW_BATTERY_PERCENT` (default 15%) and the wearable is
discharging (not currently plugged in).

Manual test:

```bash
python -m indepensense.power.tests.manual.single_ups_test
```

Prints a live readout of voltage / current / percentage / cell
voltages every 2 seconds.

## Raspberry Pi Camera Module 3 — STATUS: wired

Ribbon cable to the **CAM/DISP 0** connector. The Pi 5 has two; either
works, but `picamera2` enumerates 0 first and nothing here selects a
camera index, so use 0.

Feeds two on-demand intents — `vision.describe` (YOLOv8) and
`vision.read` (Tesseract OCR). Neither runs continuously; both fire only
when a voice command asks, which is what keeps the power and thermal cost
acceptable.

Enable it once via `raspi-config` (see the one-time setup section below)
and confirm the Pi sees it before running anything else:

```bash
rpicam-hello --list-cameras      # should list one camera
```

Manual tests, in order — capture first, then inference:

```bash
python -m indepensense.vision.tests.manual.capture_test
python -m indepensense.vision.tests.manual.detect_test
python -m indepensense.vision.tests.manual.record_test
python -m indepensense.vision.tests.manual.continuous_detect_test   # slow by design
```

Resolution and model size are `CAMERA_WIDTH` / `CAMERA_HEIGHT` and
`YOLO_MODEL_PATH` in `indepensense.config`.

## SIM7600G-H 4G dongle (cellular + GPS) — USB

Plugs into a USB port. The dongle form factor was chosen precisely because
the 40-pin header is full — a HAT would cover it and block wire access to
everything above. GPS NMEA arrives on `/dev/ttyUSB1`.
Full setup, APN and antenna notes: **`docs/sim7600.md`**.

## Microphone and speaker — USB / Bluetooth

No GPIO wiring. Audio routes through PipeWire's default source and sink,
whatever they currently are. Device selection, Bluetooth profile pitfalls
(A2DP vs HSP) and volume handling: **`docs/voice.md`**.

---

# One-time setup

## raspi-config

- **Serial Port** → Login shell over serial: **No**, Serial hardware: **Yes**
- **I2C** → enabled (MPU6050, compass, UPS HAT)
- **Camera** → handled automatically on Pi 5 + Bookworm via libcamera

User must be in the `dialout` group to access `/dev/ttyAMA*` without sudo:

```bash
sudo usermod -aG dialout $USER
```

## `/boot/firmware/config.txt` additions

For the secondary UART (DYP-A22 BOTTOM):

```
dtoverlay=uart4
```

(Reboot required after editing.)

> Add other overlays here as more components are added.
