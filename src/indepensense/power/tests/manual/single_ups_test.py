"""Manual hardware test: read from the Waveshare UPS HAT (E).

Run on a Pi 5 with the HAT installed and batteries inserted. Confirms
the driver returns sensible values matching Waveshare's own `ups.py`
demo. Ctrl-C to stop.

    python -m indepensense.power.tests.manual.single_ups_test
"""
import time

from indepensense.power.waveshare_ups_e import WaveshareUPSHatE


def main():
    reader = WaveshareUPSHatE()
    print("Reading Waveshare UPS HAT (E). Ctrl-C to stop.")
    try:
        while True:
            reading = reader.read()
            if reading is None:
                print("[read] failed (transient I²C error)")
            else:
                cells = "/".join(f"{v}" for v in reading.cell_voltages_mv)
                print(
                    f"[{reading.charging_state:>14s}] "
                    f"{reading.percentage:3d}% | "
                    f"{reading.voltage_mv:5d} mV | "
                    f"{reading.current_ma:+5d} mA | "
                    f"cells {cells} mV"
                    + (f" | critical" if reading.is_critical_low else "")
                )
            time.sleep(2.0)
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        reader.close()


if __name__ == "__main__":
    main()
