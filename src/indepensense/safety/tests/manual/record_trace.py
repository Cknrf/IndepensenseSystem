"""Manual hardware test: record a labelled IMU trace to CSV.

Captures raw accelerometer samples from the vest so they can be replayed
through the fall detector offline, as many times and at as many threshold
settings as you like. The physical work is done once; the tuning after it
costs nothing and needs no hardware.

    python -m indepensense.safety.tests.manual.record_trace adl_walking
    python -m indepensense.safety.tests.manual.record_trace fall_forward --seconds 12

Why record instead of judging live
-----------------------------------

`live_fall_test` answers "did it fire this time". That is one bit per
physical attempt, and you cannot repeat a fall enough times to tune three
thresholds against it. A recorded trace can be replayed against the whole
threshold grid in seconds — the same reason `embedding_probe` exists
rather than tuning the NLU by talking to the device.

It also means a threshold change months from now is re-verified against
the falls you already captured, instead of requiring someone to fall over
again.

Naming matters
--------------

`fall_probe` reads the expected outcome from the filename prefix:

    fall_*   — the detector SHOULD fire
    adl_*    — the detector MUST NOT fire (activities of daily living)

Anything else is recorded but scored as unlabelled. Record plenty of
`adl_` traces: false positives are the failure mode nobody tests, and on
this device a false alert reaches a guardian and teaches them to ignore
the next one.

Orientation does not matter
---------------------------

The detector thresholds on `magnitude_g` — the vector length of the three
accelerometer axes — and never reads the gyro. A sensor glued vertically
to a vest produces exactly the same magnitudes as one lying flat, so the
mounting angle needs no calibration and no correction here.

Safety
------

Do not drop the assembled prototype. The Pi, UPS HAT, camera ribbon and
SD card are not shock-rated, and the electronics are the expensive part.
For fall traces, wear the vest and fall onto a thick mattress or crash
mat — a body plus a soft surface absorbs far more than a bare drop does.
Record every `adl_` trace first; those carry no risk at all and are the
half of the dataset most likely to be missing.
"""
import argparse
import sys
import time
from pathlib import Path

from indepensense.config import (
    MPU6050_ADDRESS,
    MPU6050_I2C_BUS,
    PROJECT_ROOT,
)
from indepensense.safety.fall_detector import magnitude_g
from indepensense.sensors.mpu6050 import MPU6050

TRACE_DIR = PROJECT_ROOT / "var" / "traces"

# Target sampling rate. Matches the main loop's IMU cadence so a recorded
# trace exercises the detector at the rate it actually sees on the device.
# The achieved rate is reported at the end and written into the CSV header
# — if the Pi cannot sustain this under load, the replay must know, because
# `freefall_min_duration_s` is counted in seconds but satisfied in samples.
TARGET_HZ = 100.0


def next_path(label: str) -> Path:
    TRACE_DIR.mkdir(parents=True, exist_ok=True)
    n = 1
    while (path := TRACE_DIR / f"{label}-{n:02d}.csv").exists():
        n += 1
    return path


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "label",
        help="trace name; prefix with fall_ or adl_ so fall_probe can score it",
    )
    ap.add_argument("--seconds", type=float, default=15.0)
    ap.add_argument("--hz", type=float, default=TARGET_HZ)
    args = ap.parse_args()

    if not args.label.startswith(("fall_", "adl_")):
        print(
            f"  WARNING: {args.label!r} starts with neither 'fall_' nor 'adl_'. "
            "fall_probe will record it but cannot score it.",
            file=sys.stderr,
        )

    imu = MPU6050(bus_number=MPU6050_I2C_BUS, address=MPU6050_ADDRESS)
    path = next_path(args.label)
    period = 1.0 / args.hz

    print(f"\nRecording {args.seconds:.0f}s to {path}")
    print("  3...", flush=True); time.sleep(1)
    print("  2...", flush=True); time.sleep(1)
    print("  1...", flush=True); time.sleep(1)
    print("  GO", flush=True)

    rows: list[tuple[float, float, float, float]] = []
    dropped = 0
    t_start = time.monotonic()
    next_due = t_start

    while (now := time.monotonic()) - t_start < args.seconds:
        reading = imu.read()
        if reading is None:
            dropped += 1
        else:
            rows.append(
                (now - t_start, reading.accel_x, reading.accel_y, reading.accel_z)
            )
        next_due += period
        if (sleep_for := next_due - time.monotonic()) > 0:
            time.sleep(sleep_for)

    elapsed = time.monotonic() - t_start
    achieved_hz = len(rows) / elapsed if elapsed else 0.0

    with path.open("w") as f:
        # The achieved rate is part of the data, not a log line: a trace
        # captured at 40 Hz means something different to a detector whose
        # freefall gate needs 0.1 s of consecutive samples.
        f.write(f"# label={args.label} achieved_hz={achieved_hz:.1f} dropped={dropped}\n")
        f.write("t,ax,ay,az\n")
        for t, ax, ay, az in rows:
            f.write(f"{t:.4f},{ax:.4f},{ay:.4f},{az:.4f}\n")

    mags = [
        magnitude_g(_Reading(ax, ay, az)) for _, ax, ay, az in rows
    ] or [0.0]
    print(f"\n  Wrote {len(rows)} samples to {path}")
    print(f"  Achieved {achieved_hz:.1f} Hz (target {args.hz:.0f}), {dropped} failed reads.")
    if achieved_hz < 0.8 * args.hz:
        print("  WARNING: well under target. The detector's freefall gate needs")
        print("           0.1 s of consecutive sub-0.5 g samples; at this rate that")
        print("           is very few samples and detection will be unreliable.")
    print(f"  |a| range {min(mags):.2f} - {max(mags):.2f} g, resting ~{mags[0]:.2f} g")
    print("\n  Replay with: python -m indepensense.safety.tests.manual.fall_probe\n")

    imu.close()


class _Reading:
    """Minimal stand-in so `magnitude_g` can be reused for the summary."""

    def __init__(self, ax: float, ay: float, az: float):
        self.accel_x, self.accel_y, self.accel_z = ax, ay, az


if __name__ == "__main__":
    main()
