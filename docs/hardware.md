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

### DYP-A22 Ultrasonic Sensor #1 (primary) — STATUS: working

UART port: `/dev/ttyAMA0` (UART0, default Pi UART).
Baud: 115200.

Pin 1 (VCC)
Pin 6 (GND)
Pin 8 (RX)
Pin 10 (TX)

### DYP-A22 Ultrasonic Sensor #2 (secondary) — STATUS: working

UART port: `/dev/ttyAMA4` (UART4).
Baud: 115200.

Pin 17 (VCC)
Pin 30 (GND)
Pin 32 (RX)
Pin 33 (TX)

### Raspberry Pi Camera Module 3 — STATUS: planned

CAM/DISP 0

### MPU6050 IMU — STATUS: planned

I²C device. Will use Pi's primary I²C (I2C1).

Pin 2 (VCC)
Pin 9 (GND)
Pin 3 (GPIO 2)
Pin 5 (GPIO 3)

### Active Buzzer — STATUS: planned

| Buzzer pin | Pi physical pin | Pi GPIO  | Notes |
|------------|-----------------|----------|-------|
| +          | TBD             | TBD      | any free GPIO |
| -          | any GND         | GND      |       |

### Vibration Motor — STATUS: planned

Likely needs a transistor driver (e.g. 2N2222) — motor draws more current than
a GPIO can source directly.

| Component  | Pi physical pin | Pi GPIO  | Notes |
|------------|-----------------|----------|-------|
| Gate / base| TBD             | TBD      | through resistor |
| GND        | any GND         | GND      |       |

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



