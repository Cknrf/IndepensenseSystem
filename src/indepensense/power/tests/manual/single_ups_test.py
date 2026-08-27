"""Manual hardware test: read from the Waveshare UPS HAT (E).

Run on a Pi 5 with the HAT installed and batteries inserted. Confirms
the driver returns sensible values matching Waveshare's own `ups.py`
demo. Ctrl-C to stop.

    python -m indepensense.power.tests.manual.single_ups_test
    python -m indepensense.power.tests.manual.single_ups_test --csv
    python -m indepensense.power.tests.manual.single_ups_test --csv --interval 10

With `--csv` this doubles as the fuel-gauge characterisation rig. The
HAT reports a `percentage` we do not compute and cannot see the firmware
for, and it has been observed reading ~60% on a pack that then died
within a minute of the charger coming off. Three columns exist to work
out why:

  `mah_per_pct`   `remaining_mah / percentage`. Constant across a whole
                  charge cycle means the gauge is scaling one fixed
                  capacity — `percentage` is then a voltage reading in
                  disguise, and inherits every error voltage has. Drift
                  means it is counting coulombs against a learned
                  capacity, which fails instead by drifting away from a
                  stale reference.

  `min_cell_mv`   The pack dies when its *weakest* cell hits the BMS
                  cutoff, not when the average does. Any pack-level
                  estimate is blind to this.

  `cell_spread`   Highest minus lowest cell. Widens under load and as
                  the pack ages; the wider it is, the more optimistic
                  any pack-level percentage becomes.

Plot `percentage` against `pack_mv` from one full charge afterwards. A
straight line means a linear voltage map, which over-reports badly in
the lower half of a Li-ion discharge curve.

CSVs land in `config.BATTERY_LOG_DIR`, not the current directory — a
charge cycle runs for hours and the file should not depend on where the
test was launched from. Every row is flushed and fsynced, because the
discharge run is expected to end with the HAT cutting power to the Pi
mid-sample.
"""
import argparse
import csv
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from indepensense.config import BATTERY_LOG_DIR
from indepensense.power.waveshare_ups_e import WaveshareUPSHatE


# Sentinel for a bare `--csv` with no filename.
_TIMESTAMPED = object()

_CSV_COLUMNS = [
    "iso_time",
    "elapsed_s",
    "state",
    "percentage",
    "remaining_mah",
    "mah_per_pct",
    "pack_mv",
    "current_ma",
    "cell1_mv",
    "cell2_mv",
    "cell3_mv",
    "cell4_mv",
    "min_cell_mv",
    "cell_spread_mv",
]


def _resolve_csv_path(value) -> Path | None:
    """Turn the `--csv` argument into a concrete path, or None if unset.

    Relative names resolve against `BATTERY_LOG_DIR` rather than the
    current directory. An absolute path is honoured as given — the
    escape hatch for writing to a USB stick.
    """
    if value is None:
        return None
    if value is _TIMESTAMPED:
        stamp = datetime.now().strftime("%B-%d-%Y_%H-%M-%S")
        return BATTERY_LOG_DIR / f"{stamp}_battery.csv"
    path = Path(value)
    return path if path.is_absolute() else BATTERY_LOG_DIR / path


def main():
    parser = argparse.ArgumentParser(
        description="Waveshare UPS HAT (E) reader / fuel-gauge characterisation"
    )
    parser.add_argument("--interval", type=float, default=2.0,
                        help="seconds between reads (default: 2.0). Use 10-30 "
                             "for a multi-hour charge cycle.")
    parser.add_argument("--csv", nargs="?", const=_TIMESTAMPED, default=None,
                        metavar="NAME",
                        help=f"also log samples to a CSV under {BATTERY_LOG_DIR}. "
                             f"Bare --csv uses a timestamped filename; "
                             f"--csv NAME uses NAME; an absolute path is used "
                             f"as given.")
    args = parser.parse_args()

    reader = WaveshareUPSHatE()

    csv_file = None
    csv_writer = None
    csv_path = _resolve_csv_path(args.csv)
    if csv_path is not None:
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        csv_file = open(csv_path, "w", newline="")
        csv_writer = csv.writer(csv_file)
        csv_writer.writerow(_CSV_COLUMNS)
        print(f"Logging to {csv_path}")

    print("Reading Waveshare UPS HAT (E). Ctrl-C to stop.")
    started = time.monotonic()
    try:
        while True:
            reading = reader.read()
            if reading is None:
                # Keep going rather than bailing: a multi-hour charge run
                # should survive a single bus glitch.
                print("[read] failed (transient I²C error)", flush=True)
            else:
                cells = reading.cell_voltages_mv
                min_cell = min(cells)
                spread = max(cells) - min_cell
                # Guard the ratio: percentage legitimately hits 0 on a
                # flat pack, which is exactly when the run is most
                # interesting and least worth crashing.
                ratio = (
                    reading.remaining_mah / reading.percentage
                    if reading.percentage else 0.0
                )

                print(
                    f"[{reading.charging_state:>14s}] "
                    f"{reading.percentage:3d}% | "
                    f"{reading.remaining_mah:5d} mAh | "
                    f"{ratio:5.1f} mAh/% | "
                    f"{reading.voltage_mv:5d} mV | "
                    f"{reading.current_ma:+5d} mA | "
                    f"cells {'/'.join(str(v) for v in cells)} mV | "
                    f"min {min_cell} spread {spread:3d}"
                    + (" | critical" if reading.is_critical_low else ""),
                    flush=True,
                )

                if csv_writer:
                    csv_writer.writerow([
                        datetime.now().isoformat(timespec="seconds"),
                        f"{time.monotonic() - started:.1f}",
                        reading.charging_state,
                        reading.percentage,
                        reading.remaining_mah,
                        f"{ratio:.2f}",
                        reading.voltage_mv,
                        reading.current_ma,
                        *cells,
                        min_cell,
                        spread,
                    ])
                    # Flush AND fsync every row. The discharge run ends
                    # with the HAT cutting power mid-sample — no signal,
                    # no unwinding, the Pi just stops. `flush()` alone
                    # only moves bytes from Python's buffer into the OS
                    # page cache, which a hard power cut discards; the
                    # tail rows are exactly the ones worth having.
                    # fsync forces them onto the SD card. At a 2-30 s
                    # sampling interval the write cost is irrelevant.
                    csv_file.flush()
                    os.fsync(csv_file.fileno())

            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        reader.close()
        if csv_file:
            csv_file.close()
            print(f"CSV saved: {csv_path}")


if __name__ == "__main__":
    sys.exit(main())
