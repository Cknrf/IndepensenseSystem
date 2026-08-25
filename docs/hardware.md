# Hardware Reference

Quick-look wiring guide for assembling or re-testing the IndepenSense hardware.
Update this file every time a component's wiring changes.

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

**Critical:** DYP-A22 is a **3.3V** sensor. Wiring it to a 5V pin will damage it.

## Components

### DYP-A22 Ultrasonic — TOP sensor — STATUS: working

Cane-mounted, forward-facing, positioned high on the cane to detect
head-level obstacles (branches, low signage, awnings). This sensor
provides the wearable's unique value — the user's cane already sweeps
low obstacles by touch, but nothing else catches head-level danger.

UART port: `/dev/ttyAMA0` (UART0, default Pi UART).
Baud: 115200.

Pin 1 (VCC)
Pin 6 (GND)
Pin 8 (RX)
Pin 10 (TX)

Pin configurable via `DYP_A22_TOP_PORT` in `indepensense.config`.

### DYP-A22 Ultrasonic — BOTTOM sensor — STATUS: working

Cane-mounted, forward-facing, positioned low on the cane to detect
foot-level obstacles (curbs, planters, walls). Supplements what the
cane already senses by touch — advance warning at ~1 m.

UART port: `/dev/ttyAMA4` (UART4).
Baud: 115200.

Pin 17 (VCC)
Pin 30 (GND)
Pin 32 (RX)
Pin 33 (TX)

Pin configurable via `DYP_A22_BOTTOM_PORT` in `indepensense.config`.

### Raspberry Pi Camera Module 3 — STATUS: planned

CAM/DISP 0

### MPU6050 IMU — STATUS: working

I²C device on the Pi's primary I²C bus (I2C1) at address `0x68`. Used
by the fall detector at 100 Hz sample rate. ±8 g accelerometer range
configured in the driver. Shares the I²C bus with the Waveshare UPS
HAT (E) — they have different addresses so no conflict.

Pin 2 (VCC)     VCC
Pin 9 (GND)     GND
Pin 3 (GPIO 2)  SDA
Pin 5 (GPIO 3)  SCL

Manual test:

```
python -m indepensense.sensors.tests.manual.single_mpu6050_test
```

### QMC5883L magnetometer — STATUS: driver ready, awaiting wiring

Standalone 3-axis compass on I2C1 at address `0x0D`. Independent of the IMU:
it shares only the SDA/SCL wires, so it appears in `i2cdetect` immediately,
with no host-side setup needed.

**Why a separate chip.** The plan was an MPU9250, whose package contains an
AK8963 magnetometer beside the accel + gyro. The module that arrived is a
relabelled MPU6500 with no magnetometer die at all — a common counterfeit.
Its accel + gyro half still works as an MPU6050 (`0x68`, byte-compatible),
but heading had to move to a dedicated part, and the AK8963 driver
(`sensors/magnetometer.py`, which enabled MPU9250 bypass mode to reach
`0x0C`) was deleted along with it.

To check whether an "MPU9250" is genuine, read `WHO_AM_I` (`0x75`): `0x71` =
MPU9250, `0x73` = MPU9255, `0x70` = MPU6500 (no compass), `0x68` = MPU6050.

**⚠️ Power it from 3.3 V, NOT Pin 2.** The MPU6050 row above uses Pin 2,
which is 5 V — that board has a regulator, GY-271-style QMC5883L breakouts
often do not, and most pass SDA/SCL through **unshifted**. Copying the
MPU6050 pin table verbatim is the most likely way to destroy this sensor.
3.3 V is safe on either board variant: the bare chip runs at 2.16-3.6 V, and
a board that does carry an LDO still passes 3.3 V through fine.

Four wires. Both are **taps onto rails that already exist**, not free header
pins — the Pi's only two 3.3 V pins (1 and 17) are already taken by the two
DYP-A22s, and the three push buttons already need 3.3 V, so the build has a
distributed 3.3 V rail regardless. Splice into it; do the same for SDA/SCL,
which the MPU6050 is already on.

```
3.3 V rail          VCC     <-- NOT Pin 2 (5 V). Pins 1 and 17 are taken by
                                the DYP-A22s — tap the shared 3.3 V rail.
Pin 14 (GND)        GND     <-- or any free GND: 20, 25, 34, 39
Pin 3 (GPIO 2)      SDA     <-- shared with the MPU6050 and the UPS HAT
Pin 5 (GPIO 3)      SCL     <-- shared
DRDY                not connected
```

No level shifter and no I²C address conflict: `0x0D` (compass), `0x68` (IMU)
and `0x2D` (UPS HAT) are distinct, and everything on this bus is 3.3 V logic.

Pull-up caveat: the Pi has fixed 1.8 kΩ pull-ups on GPIO 2/3, and each
breakout adds its own (typically 4.7 kΩ). Three devices in parallel pull the
effective resistance to roughly 1 kΩ, near the point where an I²C device
can't sink enough current to drive the line low. If the bus turns flaky after
adding this module — dropped reads, `i2cdetect` showing addresses
intermittently — remove the two pull-up resistors on the QMC5883L breakout
rather than lowering the Pi's (which is not adjustable).

**Naming trap.** Modules sold as "HMC5883L" or "GY-271" almost always carry a
QMC5883L, which is *not* register-compatible with Honeywell's original. The
QMC5883L answers at `0x0D` with little-endian data; a real HMC5883L answers
at `0x1E` with big-endian data and is not supported by this driver. The
driver checks the chip-ID register (`0x0D`, expects `0xFF`) at construction
and refuses to open on a mismatch — the app then runs without a compass and
prints the reason, rather than reporting a heading that never moves.

Mount the board with its **X-axis pointing toward the front of the cane** and
Z vertical. `sensors/base.heading_from_field` computes heading as
`atan2(y, x)`; a rotated mount yields a rotated heading.

Configurable via `MAG_I2C_BUS`, `MAG_ADDRESS` and `HEADING_CHECK_INTERVAL_S`
in `indepensense.config`. The chip runs continuous ±8 G, 10 Hz, 512×
oversampling (set in the driver — see its docstring for the reasoning);
`app.py` samples the cached heading at 2 Hz.

**Calibration is required before heading means anything.** `MAG_OFFSET_X/Y/Z`
and `MAG_SCALE_X/Y/Z` in `config.py` are still at identity values. One 30 s
rotation sweep produces both: offsets cancel hard-iron bias (constant pull
from the motor magnets, battery pack, Pi), scales cancel soft-iron distortion
(the field sphere stretched into an ellipsoid, which makes heading error
depend on which way you face). Re-run whenever the physical layout changes —
batteries moved, motor added, any ferromagnetic part relocated. Calibrate
away from desks, speakers and steel furniture.

Known limitations: no tilt compensation (heading degrades when the cane is
off-vertical) and no magnetic declination applied, so this reports *magnetic*
north, not true north.

Manual tests:

```
python -m indepensense.sensors.tests.manual.single_magnetometer_test
python -m indepensense.sensors.tests.manual.magnetometer_calibrate
```

### Waveshare UPS HAT (E) — STATUS: working

Battery power + fuel gauge for the wearable. Four 18650 Li-ion cells
in a 4S1P configuration (nominal ~14.4 V, full charge ~16.8 V) via a
proprietary I²C fuel gauge at address `0x2D`.

**Mounts UNDER the Pi via pogo pins** — spring-loaded contacts on the
HAT touch test points on the Pi's underside. No GPIO header pins are
used, so it doesn't conflict with any sensor/actuator wiring. The HAT
also delivers 5 V power to the Pi (replaces the USB-C power supply).

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

### Active Buzzer — STATUS: driver ready, awaiting wiring

Standard hobby active buzzer, driven directly from a GPIO pin. GPIO HIGH
sounds the tone; LOW is silent. Active buzzers contain their own
oscillator so no PWM is needed.

| Buzzer pin | Pi physical pin | Pi GPIO  | Notes |
|------------|-----------------|----------|-------|
| +          | 12              | GPIO 18  | GPIO 18 is PWM-capable — useful later if swapped for a passive buzzer |
| -          | any GND         | GND      | shared GND rail is fine |

Pin configurable via `BUZZER_GPIO` in `indepensense.config`.

Current draw caveat: most hobby active buzzers pull 15-25 mA at 3.3 V,
which is at the edge of the Pi's per-pin GPIO source limit (~16 mA). If
`vcgencmd get_throttled` shows non-zero after adding the buzzer, add an
NPN transistor between the GPIO and the buzzer's + pin (same pattern as
the vibration motor will use).

Manual test:
```bash
python -m indepensense.feedback.tests.manual.buzzer_test              # default GPIO 18
python -m indepensense.feedback.tests.manual.buzzer_test 21           # any pin
```

### Push Buttons (KY-004 style) — STATUS: driver ready, awaiting wiring

Three identical breakout-mounted buttons. Each module has an on-board
10 kΩ pull-down resistor and drives OUT HIGH when pressed (active-high
logic), which is the opposite of a bare tactile switch. The driver
(`src/indepensense/feedback/gpio_button.py`) configures gpiozero for
active-high pull-down accordingly.

Each button needs three wires: VCC to Pi 3.3V, GND to Pi GND, OUT to the
GPIO pin listed below.

| Function                     | Pi physical pin | Pi GPIO  |
|------------------------------|-----------------|----------|
| Push-to-talk (PTT)           | 16              | GPIO 23  |
| Emergency                    | 18              | GPIO 24  |
| Repeat last instruction      | 22              | GPIO 25  |

All three pins are configurable via `PTT_BUTTON_GPIO`, `EMERGENCY_BUTTON_GPIO`,
and `REPEAT_BUTTON_GPIO` in `indepensense.config`.

Manual test:
```bash
python -m indepensense.feedback.tests.manual.button_test           # PTT pin
python -m indepensense.feedback.tests.manual.button_test 24        # any pin
```

### Vibration Motors (3x) — STATUS: driver ready, awaiting wiring

Three coin/erm-style hobby vibration motors provide directional cueing:
front (turn ahead), right (turn right), left (turn left). Each motor
needs its own NPN transistor circuit because the motors draw 60-100 mA
each — well above the Pi's per-pin GPIO source limit (~16 mA).

| Function | Pi physical pin | Pi GPIO |
|----------|-----------------|---------|
| Front    | 11              | GPIO 17 |
| Right    | 13              | GPIO 27 |
| Left     | 15              | GPIO 22 |

Pins configurable via `VIBRATION_FRONT_GPIO`, `VIBRATION_RIGHT_GPIO`,
and `VIBRATION_LEFT_GPIO` in `indepensense.config`.

**Per-motor circuit (repeat 3 times):**

```
Motor +     → 5V rail (Pi physical pin 2 or 4)
Motor −     → NPN transistor collector (2N2222 or 2N3904)
NPN emitter → GND rail
NPN base    → 1 kΩ resistor → Pi GPIO
Flyback diode (1N4001):
    cathode (striped end) → Motor +
    anode                 → Motor −
```

The flyback diode is not optional — the reverse voltage spike when a
motor stops can otherwise destroy the transistor or the Pi's GPIO.

Manual test:
```bash
python -m indepensense.feedback.tests.manual.vibration_test
```

## raspi-config one-time setup

- **Serial Port** → Login shell over serial: **No**, Serial hardware: **Yes**
- **I2C** → enabled (for MPU6050)
- **Camera** → handled automatically on Pi 5 + Bookworm via libcamera

User must be in the `dialout` group to access `/dev/ttyAMA*` without sudo:

```
sudo usermod -aG dialout $USER
```

## `/boot/firmware/config.txt` additions

For the secondary UART (DYP-A22 #2):

```
dtoverlay=uart4
```

(Reboot required after editing.)

> Add other overlays here as more components are added.



