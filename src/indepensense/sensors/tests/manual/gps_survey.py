"""Manual hardware test: survey one spot and measure how good the fix is.

`single_gps_test` answers "is the GPS talking?". This answers the question
that decides whether GPS-based indoor navigation is viable at all:
**how much does the reported position wander while the device is not
moving, and is the fix even live?**

Stand still at a labelled spot, let it sample for a minute or two, and
read the summary. Repeat for each place you care about. Every sample is
appended to a CSV so a whole building can be surveyed across several
runs and analysed afterwards.

    python -m indepensense.sensors.tests.manual.gps_survey --label kitchen
    python -m indepensense.sensors.tests.manual.gps_survey --label hallway --seconds 180

Requires the GNSS antenna connected and GPS enabled on the modem — see
`single_gps_test` for the one-time `AT+CGPS=1` step.

Reading the summary
-------------------

**fix rate** — share of samples with `fix_quality > 0`. Below ~90% means
the receiver is struggling; navigation would drop out unpredictably.

**satellites / HDOP** — a trustworthy fix needs 4+ satellites and HDOP
under about 2. HDOP is a unitless geometry multiplier: low means the
visible satellites are well spread, high means they are clustered and
the position is poorly constrained regardless of how many there are.

**scatter** — how far samples fall from their own mean, in metres, while
the device sat still. This is the number that decides indoor viability.
Compare it against the size of the spaces you want to distinguish: if
scatter is 8 m and your rooms are 4 m across, the system cannot tell
which room it is in no matter how stable the reading looks.

**frozen samples** — consecutive samples with byte-identical lat/lon.
This is the trap this tool exists to catch. A GNSS receiver that loses
lock indoors often keeps reporting its last known position instead of
reporting failure, so the numbers look clean and precise while being
minutes stale. Real fixes always jitter a little. A long frozen run
means you are reading a memory of the last outdoor fix, not your
current position — and it will look most convincing exactly where it is
least true.
"""
import argparse
import csv
import math
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

from indepensense.config import SIM7600_GPS_PORT
from indepensense.sensors.gps import SIM7600GPS

DEFAULT_OUTPUT = Path("gps_survey.csv")
CSV_FIELDS = [
    "recorded_at",
    "label",
    "lat",
    "lon",
    "altitude_m",
    "satellites",
    "hdop",
    "fix_quality",
]


def _offsets_m(
    lat: float,
    lon: float,
    ref_lat: float,
    ref_lon: float,
) -> tuple[float, float]:
    """Convert a lat/lon delta to metres east/north of a reference point.

    Local flat-earth approximation. At the tens-of-metres scale we're
    measuring it is accurate to well under a centimetre, and unlike
    haversine it keeps the two axes separate — useful because GNSS error
    is often anisotropic (worse east-west than north-south, or the
    reverse, depending on which satellites are visible).
    """
    lat_scale = 111_320.0
    lon_scale = 111_320.0 * math.cos(math.radians(ref_lat))
    return (lon - ref_lon) * lon_scale, (lat - ref_lat) * lat_scale


def _summarise(label: str, samples: list[dict], no_fix_count: int) -> None:
    total = len(samples) + no_fix_count
    print()
    print("=" * 60)
    print(f"  Survey summary — {label}")
    print("=" * 60)

    if not samples:
        print(f"  No fix in any of {total} samples. Nothing to summarise.")
        print("  GPS is not usable at this spot.")
        return

    located = [s for s in samples if s["fix_quality"] > 0]
    print(f"  samples          : {total} ({no_fix_count} with no reading at all)")
    print(f"  fix rate         : {len(located)}/{total} = {100 * len(located) / total:.0f}%")

    sats = [s["satellites"] for s in samples if s["satellites"] is not None]
    if sats:
        print(f"  satellites       : min {min(sats)}, median {statistics.median(sats):.0f}, max {max(sats)}")
    hdops = [s["hdop"] for s in samples if s["hdop"] is not None]
    if hdops:
        print(f"  HDOP             : min {min(hdops):.1f}, median {statistics.median(hdops):.1f}, max {max(hdops):.1f}")

    if not located:
        print("  No samples with a valid fix — scatter cannot be measured.")
        return

    # Scatter: distance of each sample from the mean of all samples.
    mean_lat = statistics.fmean(s["lat"] for s in located)
    mean_lon = statistics.fmean(s["lon"] for s in located)
    distances = []
    for s in located:
        east, north = _offsets_m(s["lat"], s["lon"], mean_lat, mean_lon)
        distances.append(math.hypot(east, north))
    distances.sort()

    print(f"  mean position    : {mean_lat:+.6f}, {mean_lon:+.6f}")
    print(f"  scatter (median) : {statistics.median(distances):.1f} m")
    print(f"  scatter (95th)   : {distances[int(0.95 * (len(distances) - 1))]:.1f} m")
    print(f"  scatter (worst)  : {max(distances):.1f} m")

    # Frozen runs — consecutive identical coordinates.
    longest_frozen = current = 1
    for prev, cur in zip(located, located[1:]):
        if (prev["lat"], prev["lon"]) == (cur["lat"], cur["lon"]):
            current += 1
            longest_frozen = max(longest_frozen, current)
        else:
            current = 1
    print(f"  longest frozen   : {longest_frozen} consecutive identical samples")

    print()
    if longest_frozen >= 10:
        # Deliberately do NOT print a resolution figure here. A frozen
        # receiver reports near-zero scatter, which would read as
        # spectacular precision — the exact false conclusion this tool
        # exists to prevent.
        print("  WARNING: a long frozen run means the receiver is very likely")
        print("  replaying its last known fix rather than locating you now.")
        print("  The scatter figures above measure nothing in that case, and")
        print("  low scatter here is evidence of a stale fix, not a good one.")
        print("  Re-run outdoors first to confirm the receiver jitters normally.")
    else:
        print(f"  Rooms/zones must be larger than ~{2 * statistics.median(distances):.0f} m")
        print("  across to be reliably distinguishable at this spot.")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--label", required=True, help="name of the spot being surveyed")
    ap.add_argument("--seconds", type=float, default=120.0, help="how long to sample")
    ap.add_argument("--interval", type=float, default=1.0, help="seconds between samples")
    ap.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="CSV to append to")
    args = ap.parse_args()

    gps = SIM7600GPS(port=SIM7600_GPS_PORT)
    samples: list[dict] = []
    no_fix_count = 0

    write_header = not args.output.exists()
    print(f"Surveying '{args.label}' for {args.seconds:.0f}s → {args.output}")
    print("Stand still and keep the antenna where it will actually be worn.")
    print("Ctrl-C to stop early and summarise what was collected.\n")

    try:
        with args.output.open("a", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
            if write_header:
                writer.writeheader()

            deadline = time.monotonic() + args.seconds
            while time.monotonic() < deadline:
                fix = gps.read()
                if fix is None:
                    no_fix_count += 1
                    print("  no reading")
                else:
                    row = {
                        "recorded_at": datetime.now(timezone.utc).isoformat(),
                        "label": args.label,
                        "lat": fix.lat,
                        "lon": fix.lon,
                        "altitude_m": fix.altitude_m,
                        "satellites": fix.satellites,
                        "hdop": fix.hdop,
                        "fix_quality": fix.fix_quality,
                    }
                    writer.writerow(row)
                    handle.flush()   # survive a Ctrl-C mid-survey
                    samples.append(row)
                    print(
                        f"  {fix.lat:+.6f}, {fix.lon:+.6f} | "
                        f"sats {fix.satellites} | hdop {fix.hdop} | "
                        f"quality {fix.fix_quality}"
                    )
                time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nStopped early.")
    finally:
        gps.close()

    _summarise(args.label, samples, no_fix_count)


if __name__ == "__main__":
    main()
