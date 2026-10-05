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
Pin 3  (GPIO 2 / SDA)     shared I2C1          SDA   — MPU6050, UPS HAT
Pin 4  (5V)               Perfboard
Pin 5  (GPIO 3 / SCL)     shared I2C1          SCL   — MPU6050, UPS HAT
Pin 6  (GND)              DYP-A22 TOP          GND
Pin 8  (GPIO 14 / TX)     DYP-A22 TOP          RX
Pin 9  (GND)              MPU6050              GND
Pin 10 (GPIO 15 / RX)     DYP-A22 TOP          TX
Pin 11 (GPIO 17)          Vibration motor      FRONT
Pin 12 (GPIO 18)          Active buzzer        +
Pin 13 (GPIO 27)          Vibration motor      RIGHT
Pin 15 (GPIO 22)          Vibration motor      LEFT
Pin 16 (GPIO 23)          Button               PTT
Pin 17 (3V3)              DYP-A22 BOTTOM       VCC
Pin 18 (GPIO 24)          Button               EMERGENCY
Pin 21 (GPIO 9 / SCL4)    QMC5883P compass     SCK   — I2C4, its own bus
Pin 22 (GPIO 25)          Button               REPEAT / STOP
Pin 24 (GPIO 8 / SDA4)    QMC5883P compass     SDA   — I2C4, its own bus
Pin 30 (GND)              DYP-A22 BOTTOM       GND
Pin 32 (GPIO 12 / TX)     DYP-A22 BOTTOM       RX
Pin 33 (GPIO 13 / RX)     DYP-A22 BOTTOM       TX
Pin 34 (GND)              QMC5883P compass     GND
```

Free GND pins for the shared ground rail: **14, 20, 25, 39**.

**Shared rails.** Both 3.3 V pins (1 and 17) are consumed by the two DYP-A22s,
but the three buttons and the compass also need 3.3 V. The build therefore has
a distributed 3.3 V rail — splice into it rather than hunting for a free header
pin.

**Two I²C buses, not one.** I2C1 (pins 3/5) carries the MPU6050 and the UPS
HAT. The compass has its own bus, I2C4, on pins 24/21 — it was on I2C1 and a
third set of pull-ups made that bus unreliable. See the compass section for
the measurements and the reasoning.

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
Push-to-talk (PTT)          RIGHT on the enclosure
    3.3 V rail  (VCC)
    GND rail    (GND)       pins 20, 25, 34 or 39
    Pin 16      (OUT)       GPIO 23

Emergency                   FRONT on the enclosure
    3.3 V rail  (VCC)
    GND rail    (GND)
    Pin 18      (OUT)       GPIO 24

Repeat / stop speech        LEFT on the enclosure
    3.3 V rail  (VCC)
    GND rail    (GND)
    Pin 22      (OUT)       GPIO 25
```

**The positions are spoken aloud, so they are not cosmetic.** `messages.py`
fills `{button}` and `{cancel}` in every confirmation prompt from
`button.ptt_position` and `button.cancel_position`, which describe this
layout. This table recorded PTT as "left" and the other two as "position
unrecorded"; the wearable therefore told users to "press the left button to
confirm" when left is the button that *cancels*. Re-fabricating the
enclosure means editing those two message values, and this table, together.

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
Pin 3 (GPIO 2)  SDA     shared with the UPS HAT
Pin 5 (GPIO 3)  SCL     shared
```

Used by the fall detector at 100 Hz sample rate. ±8 g accelerometer range
configured in the driver. Shares I2C1 with the Waveshare UPS HAT (`0x2D`)
only — two devices, distinct addresses, no conflict. The compass was briefly
on this bus too and had to be moved; see its section for why.

**Do not copy the Pin 2 (5 V) line to the compass.** The MPU6050 tolerates it
because of its regulator; most compass breakouts do not. See the next section.

Address configurable via `MPU6050_ADDRESS` in `indepensense.config`.

Manual test:

```bash
python -m indepensense.sensors.tests.manual.single_mpu6050_test
```

# 7. QMC5883P magnetometer — STATUS: wired, calibration outstanding

Standalone 3-axis compass at address **`0x2C`**, on **its own I²C bus, I2C4**
— not the I2C1 bus the MPU6050 and UPS HAT share. That separation is
deliberate and was forced by measurement; see "Why its own bus" below.

Bus 4 does not exist until `dtoverlay=i2c-gpio,bus=4,...` is in
`/boot/firmware/config.txt` — see the one-time setup section at the end. It is
a **software (bit-banged) bus**, not one of the SoC's hardware I²C
controllers; the reason is below.

```
3.3 V rail      VDD     ⚠️ NOT Pin 2 (5 V). Pins 1 and 17 are taken by the
                           DYP-A22s — tap the shared 3.3 V rail.
Pin 34 (GND)    GND     or any free GND: 14, 20, 25, 39
Pin 24 (GPIO 8) SDA     I2C4 — the compass alone
Pin 21 (GPIO 9) SCK     I2C4. Labelled SCK on this part, = SCL
                DRDY    not connected
```

Pins 24 and 21 are adjacent on the header, which keeps the run short. They
are also SPI0's CE0 and MISO — nothing in this build uses SPI and it is
disabled by default, but an SPI device added later would collide.

**⚠️ Power it from 3.3 V, NOT Pin 2.** The MPU6050 section above uses Pin 2,
which is 5 V — that board has a regulator, GY-271-style compass breakouts
often do not, and most pass SDA/SCL through **unshifted**. Copying the
MPU6050 pin list verbatim is the most likely way to destroy this sensor.
3.3 V is safe on either board variant: the bare chip runs at 2.5-3.6 V, and a
board that does carry an LDO still passes 3.3 V through fine.

VDD is a **tap onto a rail that already exists**, not a free header pin — the
Pi's only two 3.3 V pins (1 and 17) are already taken by the two DYP-A22s,
and the three push buttons already need 3.3 V, so the build has a distributed
3.3 V rail regardless. Splice into it. SDA, SCK and GND all reach free header
pins directly and need no splicing.

No level shifter is needed — everything here is 3.3 V logic.

### Why its own bus

This chip was first wired onto I2C1, spliced into the MPU6050's SDA/SCL. The
bus then failed intermittently, and the way it failed is worth recording.

I²C lines are open-drain: a device signals by *sinking* current to pull the
line low, and pull-up resistors restore the high level. The Pi has fixed
1.8 kΩ pull-ups on GPIO 2/3 that cannot be adjusted, and every breakout adds
its own — typically 4.7 kΩ. With three devices on the bus:

```
1.8k ∥ 4.7k (MPU6050) ∥ 4.7k (UPS HAT) ∥ 4.7k (compass)  ≈  0.95 kΩ
```

At 3.3 V that demands ~3.4 mA of sink current to pull a line low, against the
3 mA an I²C device is only obliged to provide. Two devices were fine; the
third crossed the limit.

The symptoms were **not** a clean dead bus, which is what made it confusing:

- `app.py` aborted with `[Errno 121] Remote I/O error` opening the **MPU6050**
  — a device that had worked for weeks and whose wiring had not been touched.
- Minutes later `i2cdetect -y 1` listed all three addresses correctly, and the
  failure moved to the compass instead.
- A phantom device appeared at `0x08`, an address nothing in this build uses.

The tell is that `i2cdetect`'s probe needs **one** ACK, while the driver's
first `write_byte_data` needs **three** consecutive ACKs (address, register,
value). A marginal bus passes the cheap probe and fails the real transaction,
so a clean `i2cdetect` is not evidence of a healthy bus. A fault that migrates
between devices is in the bus, not in any device.

Two fixes were available: desolder the two 4.7 kΩ pull-ups off the compass
breakout, or give the compass its own bus. The second was chosen — it is
reversible, needs no rework on a populated board, and it means a future I²C
device can never destabilise the IMU or the compass again. The cost is one
config.txt overlay and two header pins, both of which this build has spare.

Lowering the I²C baudrate is the common advice for a flaky bus and would not
have helped: that addresses pull-ups too *weak* and rise times too slow. This
was the opposite fault, and clock speed has no bearing on sink current.

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

`magnetometer_axes` does all of this by measurement and says the answer
out loud, which matters because turning the vest and reading a scrolling
terminal are not things one person does at once:

```bash
python -m indepensense.sensors.tests.manual.magnetometer_axes
```

It needs no compass. Pass 1 finds the vertical axis and refuses to guess
when the motion was a tumble rather than a turn; pass 2 fixes the
mirroring, which is the half no offset can correct. What it cannot
determine without a known bearing — where zero is, to within a whole
number of 90° steps — it reports rather than invents.

The manual procedure it replaces, for reference:

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
everything above. GPS NMEA arrives on USB interface 1 — address it as
`/dev/serial/by-id/...-if01-port0`, never `/dev/ttyUSB1`: the modem
re-enumerates and the number moves with it.
Full setup, APN and antenna notes: **`docs/sim7600.md`**.

## Headset — USB

**NEWMSNR Ear Clip Earphones Wired Long Wear**, an open-ear clip-on headset
with an inline microphone. USB-C plug, connected through a passive USB-C to
USB-A adapter. No GPIO wiring — audio routes through PipeWire's default
source and sink.

The Pi 5 has **no 3.5 mm jack at all**; unlike the Pi 4B, the analog audio
connector was removed from the board. Even on a Pi 4 that jack carried
output and composite video only and never had a microphone input, so any
headset with a mic has to arrive over USB regardless. This one enumerates as
a USB Audio Class device with both endpoints on one card, which is why it
needs no driver:

```
$ lsusb
Bus 001 Device 002: ID 0020:0b21 Generic EarPods
$ aplay -l
card 0: EarPods [EarPods], device 0: USB Audio [USB Audio]
$ arecord -l
card 0: EarPods [EarPods], device 0: USB Audio [USB Audio]
```

Appearing in **both** `aplay -l` and `arecord -l` is the check that matters.
A USB-C earphone that shows nothing in `lsusb` is a passive analog part
relying on the host phone's DAC, and no adapter will make it work here.

**Why a wired headset replaced the Bluetooth earphones and separate USB
microphone.** The AirPods used previously exposed one device with two
mutually exclusive profiles: A2DP gives stereo output and no microphone,
HSP/HFP gives a mono microphone and tinny mono output. Capturing voice
therefore forced the whole output path down to handsfree quality for the
duration, and the profile switch had to be forced by hand. A USB Audio Class
headset is full duplex — playback and capture run at full quality
simultaneously, with no profile negotiation, no pairing at boot, and no
silent reconnect failure. It also collapses two devices into one and frees a
USB port.

The open-ear form factor is the accessibility argument: the ear canal stays
unobstructed, so the user keeps full ambient hearing. For a blind-navigation
wearable that is not a comfort preference — traffic noise, footsteps and
voices are primary navigation input, and occluding earbuds would take away
more situational awareness than the device gives back.

Device selection, microphone gain and volume handling: **`docs/voice.md`**.

---

# One-time setup

## raspi-config

- **Serial Port** → Login shell over serial: **No**, Serial hardware: **Yes**
- **I2C** → enabled (MPU6050 and UPS HAT on I2C1; the compass's I2C4 comes
  from the overlay below)
- **Camera** → handled automatically on Pi 5 + Bookworm via libcamera

User must be in the `dialout` group to access `/dev/ttyAMA*` without sudo:

```bash
sudo usermod -aG dialout $USER
```

## `/boot/firmware/config.txt` additions

For the secondary UART (DYP-A22 BOTTOM) and the compass's own I²C bus:

```
dtoverlay=uart4
dtoverlay=i2c-gpio,bus=4,i2c_gpio_sda=8,i2c_gpio_scl=9
```

**Do not use `dtoverlay=i2c4,pins_8_9` here.** It is the obvious-looking
choice and it silently does nothing on this board: `dtoverlay -h i2c4` says
"BCM2711 only", which is the Pi 4's SoC. The Pi 5 is a BCM2712. The overlay
loads without error and no `/dev/i2c-4` ever appears.

`i2c-gpio` bit-bangs I²C on any two GPIOs and works on every Pi model. It is
slower than a hardware controller, which is irrelevant here — `app.py` samples
the compass at 2 Hz. What matters is that the compass gets its own pair of
pull-ups, and that is true of a software bus just as much as a hardware one.

(Reboot required after editing.)

> Add other overlays here as more components are added.
