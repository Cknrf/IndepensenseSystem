"""Empirical probe: replay recorded IMU traces through the fall detector.

Answers the question a live drop test cannot: **across every trace we
have, how many real falls does the detector catch, and how many ordinary
activities does it mistake for one?**

Sensitivity and specificity are reported separately, and the separation
is the point. A detector that fires on everything scores 100% on falls
and is useless; one that never fires scores 100% on daily activity and
is worse than useless. Neither number means anything alone.

Runs entirely offline — no Pi, no IMU, no vest. `ThresholdFallDetector`
is a pure function over `IMUReading`, so a trace recorded once can be
replayed against the whole threshold grid in seconds. That is what makes
tuning possible at all: you cannot ask someone to fall over forty times
to sweep three thresholds.

    # score every trace at the thresholds in config.py
    python -m indepensense.safety.tests.manual.fall_probe

    # find a better operating point
    python -m indepensense.safety.tests.manual.fall_probe --sweep

    # look at one trace in detail
    python -m indepensense.safety.tests.manual.fall_probe --trace fall_forward-01

Traces come from `record_trace.py` and live in `var/traces/`. Expected
outcome is read from the filename: `fall_*` should fire, `adl_*` must
not.

Interpreting the result
-----------------------

Expect high specificity and imperfect sensitivity. The detector requires
a freefall phase before the impact, which is an excellent filter against
sitting down heavily — and which real falls do not always produce. A
fall where the wearer grabs a railing, slides down a wall, or lands on
outstretched hands may never drop below the freefall threshold.

That is a deliberate trade, not a defect: a false alert reaches a
guardian, and a guardian who learns to ignore alerts is a worse outcome
than a missed one. But the numbers should be reported, not assumed — and
if sensitivity is very low, the fix is a second detection path for
non-freefall falls rather than a lower threshold, which would surrender
the specificity that makes the alerts worth trusting.
"""
import argparse
import math
import re
from dataclasses import dataclass
from pathlib import Path

from indepensense.config import (
    FALL_FREEFALL_MIN_DURATION_S,
    FALL_FREEFALL_THRESHOLD_G,
    FALL_IMPACT_THRESHOLD_G,
    FALL_IMPACT_WINDOW_S,
    FALL_STILLNESS_DURATION_S,
    FALL_STILLNESS_MAX_STDDEV_G,
    PROJECT_ROOT,
)
from indepensense.safety.fall_detector import ThresholdFallDetector, magnitude_g
from indepensense.sensors.base import IMUReading

TRACE_DIR = PROJECT_ROOT / "var" / "traces"

# Sweep grid: freefall threshold against freefall *duration*.
#
# Not impact, which the first real recordings showed is not the binding
# constraint — a mattress fall already peaked at 6.6 g against a 2.0 g
# threshold, while the same trace failed the freefall gate. The gate is
# a threshold AND a duration, and a torso-mounted sensor in a forward
# fall rotates about the knees rather than dropping freely, so it spends
# far less time near zero g than a true drop would.
#
# Impact is still sweepable with --impact; it just does not belong on
# the axis of a table meant to find the operating point.
FREEFALL_GRID = (0.4, 0.5, 0.6, 0.7, 0.8)
DURATION_GRID = (0.03, 0.05, 0.08, 0.10, 0.15)


@dataclass(frozen=True)
class Trace:
    name: str
    is_fall: bool | None       # None when the filename carries no label
    readings: list[IMUReading]
    achieved_hz: float


def load_traces(directory: Path) -> list[Trace]:
    traces = []
    for path in sorted(directory.glob("*.csv")):
        traces.append(load_trace(path))
    return traces


def load_trace(path: Path) -> Trace:
    hz = 0.0
    readings: list[IMUReading] = []

    for line in path.read_text().splitlines():
        if line.startswith("#"):
            if m := re.search(r"achieved_hz=([\d.]+)", line):
                hz = float(m.group(1))
            continue
        if not line.strip() or line.startswith("t,"):
            continue
        values = [float(v) for v in line.split(",")]
        if len(values) != 7:
            # Traces recorded before the gyro was captured. Rejected
            # rather than zero-filled: a rotation-based detector reading
            # gx=gy=gz=0 would conclude "no rotation at all" and score
            # every old fall as a miss, which looks like an algorithm
            # result rather than missing data. Loudly useless beats
            # quietly wrong.
            raise SystemExit(
                f"{path.name} has {len(values)} columns, expected 7 "
                f"(t,ax,ay,az,gx,gy,gz).\nIt predates gyro recording. "
                f"Delete it and re-record — a rotation signal cannot be "
                f"recovered from an accelerometer-only trace."
            )
        t, ax, ay, az, gx, gy, gz = values
        readings.append(
            IMUReading(
                accel_x=ax, accel_y=ay, accel_z=az,
                gyro_x=gx, gyro_y=gy, gyro_z=gz,
                # Never read by the detector, and not worth a column.
                temperature_c=0.0,
                timestamp=t,
            )
        )

    stem = path.stem
    is_fall = True if stem.startswith("fall_") else False if stem.startswith("adl_") else None
    return Trace(name=stem, is_fall=is_fall, readings=readings, achieved_hz=hz)


def replay(
    trace: Trace,
    freefall_g: float,
    impact_g: float,
    freefall_s: float = FALL_FREEFALL_MIN_DURATION_S,
) -> dict | None:
    """Run one trace through a fresh detector. Returns the event, or None.

    A new detector per trace, deliberately: state carried over from a
    previous recording would make the result depend on file ordering.
    """
    detector = ThresholdFallDetector(
        freefall_threshold_g=freefall_g,
        freefall_min_duration_s=freefall_s,
        impact_threshold_g=impact_g,
        impact_window_s=FALL_IMPACT_WINDOW_S,
        stillness_max_stddev_g=FALL_STILLNESS_MAX_STDDEV_G,
        stillness_duration_s=FALL_STILLNESS_DURATION_S,
    )
    reached = set()
    for reading in trace.readings:
        event = detector.process(reading)
        reached.add(detector.state.name)
        if event is not None:
            return {
                "freefall_s": event.freefall_duration_s,
                "impact_g": event.impact_magnitude_g,
                "at_s": event.timestamp,
            }
    # No event. Which states it reached says why — a trace that never
    # left IDLE never looked like freefall at all, which is a different
    # problem from one that hit POST_IMPACT and failed the stillness gate.
    return None if "POST_FREEFALL" not in reached else {"stalled_at": sorted(reached)}


def score(
    traces: list[Trace],
    freefall_g: float,
    impact_g: float,
    freefall_s: float = FALL_FREEFALL_MIN_DURATION_S,
) -> dict:
    tp = fn = tn = fp = 0
    rows = []
    for t in traces:
        if t.is_fall is None:
            continue
        result = replay(t, freefall_g, impact_g, freefall_s)
        fired = result is not None and "stalled_at" not in result
        if t.is_fall:
            tp, fn = (tp + 1, fn) if fired else (tp, fn + 1)
        else:
            fp, tn = (fp + 1, tn) if fired else (fp, tn + 1)
        rows.append((t, fired, result))
    return {"tp": tp, "fn": fn, "tn": tn, "fp": fp, "rows": rows}


def posture_change_deg(trace: Trace, head_s: float = 1.0, tail_s: float = 2.0) -> float:
    """Angle between the body's orientation at the start and the end.

    The measurement that decides whether the proposed orientation gate
    is worth building. Gravity always points down, so the direction of
    the accelerometer vector *at rest* is a direct readout of which way
    the body is leaning — no gyro integration, no drift.

    Averaging over a window is what makes this work: individual samples
    during a fall are dominated by motion, but the mean over a second of
    standing still, or two seconds of lying still, is gravity alone.

    Roughly: 0° means the body ended up as it started; ~90° means it
    went from upright to horizontal. Sitting in a chair should be small
    (the torso stays vertical); falling should be large.

    Mount-independent, so the sensor being glued vertically to the vest
    changes nothing — this compares the trace against its own starting
    orientation, not against an assumed "up".
    """
    if not trace.readings:
        return 0.0

    t0 = trace.readings[0].timestamp
    t_end = trace.readings[-1].timestamp
    head = [r for r in trace.readings if r.timestamp <= t0 + head_s]
    tail = [r for r in trace.readings if r.timestamp >= t_end - tail_s]
    if not head or not tail:
        return 0.0

    def mean_vector(rs):
        n = len(rs)
        return (
            sum(r.accel_x for r in rs) / n,
            sum(r.accel_y for r in rs) / n,
            sum(r.accel_z for r in rs) / n,
        )

    a, b = mean_vector(head), mean_vector(tail)
    na = math.sqrt(sum(v * v for v in a))
    nb = math.sqrt(sum(v * v for v in b))
    if na == 0 or nb == 0:
        return 0.0

    cos = sum(x * y for x, y in zip(a, b)) / (na * nb)
    return math.degrees(math.acos(max(-1.0, min(1.0, cos))))


def peak_rotation_dps(trace: Trace) -> float:
    """Largest single-axis angular rate anywhere in the trace."""
    return max(
        (max(abs(r.gyro_x), abs(r.gyro_y), abs(r.gyro_z)) for r in trace.readings),
        default=0.0,
    )


def longest_run_below(trace: Trace, threshold: float) -> float:
    """Longest unbroken stretch, in seconds, spent under `threshold`.

    The diagnostic for "never reached freefall". Knowing the trace dipped
    to 0.43 g says nothing useful on its own — the gate is a *duration*,
    not a minimum, so what matters is how long it stayed down. A fall
    that touches 0.43 g for 40 ms fails a 100 ms gate, and the fix for
    that is the duration, not the threshold. Without this number the two
    are indistinguishable in the output and you tune the wrong knob.
    """
    best = 0.0
    run_start: float | None = None
    for r in trace.readings:
        if magnitude_g(r) < threshold:
            if run_start is None:
                run_start = r.timestamp
            best = max(best, r.timestamp - run_start)
        else:
            run_start = None
    return best


def _pct(part: int, whole: int) -> str:
    return "n/a" if not whole else f"{100 * part / whole:.0f}%"


def report(s: dict, freefall_g: float, impact_g: float) -> None:
    print(f"\n  thresholds: freefall < {freefall_g} g, impact > {impact_g} g")
    print(f"\n  {'trace':28s} {'expected':>9s} {'fired':>6s}  detail")
    print("  " + "-" * 74)
    for t, fired, result in s["rows"]:
        mags = [magnitude_g(r) for r in t.readings] or [0.0]
        if fired:
            detail = f"freefall {result['freefall_s']:.2f}s, impact {result['impact_g']:.1f}g"
        elif result and "stalled_at" in result:
            detail = f"saw freefall, no confirmed fall ({'/'.join(result['stalled_at'])})"
        else:
            run_ms = 1000 * longest_run_below(t, freefall_g)
            need_ms = 1000 * FALL_FREEFALL_MIN_DURATION_S
            detail = (
                f"no freefall: min |a| {min(mags):.2f} g, longest run under "
                f"{freefall_g} g was {run_ms:.0f} ms (need {need_ms:.0f} ms)"
            )
        mark = "OK " if fired == t.is_fall else "<<<"
        print(f"  {mark} {t.name:24s} {'FALL' if t.is_fall else 'adl':>9s} "
              f"{'yes' if fired else 'no':>6s}  {detail}")

    print("  " + "-" * 74)
    print(f"  sensitivity {_pct(s['tp'], s['tp'] + s['fn']):>5s}  "
          f"({s['tp']}/{s['tp'] + s['fn']} real falls caught)")
    print(f"  specificity {_pct(s['tn'], s['tn'] + s['fp']):>5s}  "
          f"({s['tn']}/{s['tn'] + s['fp']} daily activities correctly ignored)")
    if s["fp"]:
        print(f"\n  {s['fp']} FALSE ALARM(S). Each one reaches a guardian. Fix these")
        print("  before chasing sensitivity — an ignored alert protects nobody.")
    if not (s["tn"] + s["fp"]):
        print("\n  No adl_ traces. Specificity is unmeasured, so a detector that")
        print("  fires on everything would score perfectly here. Record some.")


def sweep(traces: list[Trace], impact_g: float) -> None:
    """Freefall threshold against freefall duration, at a fixed impact.

    Read it by finding rows with zero false alarms first, then taking
    the highest sensitivity among those. A row with better sensitivity
    and one false alarm is not an improvement: the false alarm reaches a
    guardian, and guardians who learn to ignore alerts protect nobody.
    """
    print(f"\n  impact held at {impact_g} g (sweep it with --impact)")
    print(f"\n  {'freefall':>9s} {'for':>7s} {'sens':>6s} {'spec':>6s} "
          f"{'missed':>7s} {'false':>6s}")
    print("  " + "-" * 48)
    for ff in FREEFALL_GRID:
        for dur in DURATION_GRID:
            s = score(traces, ff, impact_g, dur)
            flag = "  <- clean" if s["fp"] == 0 and s["fn"] == 0 else ""
            print(f"  {ff:9.2f} {dur * 1000:5.0f}ms "
                  f"{_pct(s['tp'], s['tp'] + s['fn']):>6s} "
                  f"{_pct(s['tn'], s['tn'] + s['fp']):>6s} "
                  f"{s['fn']:7d} {s['fp']:6d}{flag}")
        print()


def signals(traces: list[Trace]) -> None:
    """Every candidate signal per trace, falls and activities grouped.

    Answers "which measurement actually separates a fall from an
    activity" before any of them is wired into the detector. A signal
    whose fall range overlaps its ADL range cannot be a gate at any
    threshold, and that is far cheaper to discover here than after
    rewriting the state machine around it.
    """
    print(f"\n  {'trace':26s} {'min|a|':>7s} {'peak|a|':>8s} "
          f"{'rot °/s':>8s} {'tilt°':>6s}")
    print("  " + "-" * 60)

    ranges: dict[bool, dict[str, list[float]]] = {
        True: {"min_g": [], "peak_g": [], "rot": [], "tilt": []},
        False: {"min_g": [], "peak_g": [], "rot": [], "tilt": []},
    }

    for is_fall in (True, False):
        for t in (x for x in traces if x.is_fall is is_fall):
            mags = [magnitude_g(r) for r in t.readings] or [0.0]
            row = {
                "min_g": min(mags),
                "peak_g": max(mags),
                "rot": peak_rotation_dps(t),
                "tilt": posture_change_deg(t),
            }
            for k, v in row.items():
                ranges[is_fall][k].append(v)
            print(f"  {'FALL' if is_fall else 'adl ':4s} {t.name:21s} "
                  f"{row['min_g']:7.2f} {row['peak_g']:8.2f} "
                  f"{row['rot']:8.0f} {row['tilt']:6.0f}")
        print()

    print("  " + "-" * 60)
    print("  SEPARATION — does any single signal split falls from activities?\n")
    for key, label, fmt in (
        ("min_g", "lowest |a| (freefall)", "5.2f"),
        ("peak_g", "peak |a| (impact)", "5.2f"),
        ("rot", "peak rotation °/s", "5.0f"),
        ("tilt", "posture change °", "5.0f"),
    ):
        f, a = ranges[True][key], ranges[False][key]
        if not f or not a:
            continue
        # Falls are expected high on every signal except lowest-|a|,
        # where a fall should go LOWER than an activity.
        if key == "min_g":
            gap, verdict = min(a) - max(f), "falls lower"
        else:
            gap, verdict = min(f) - max(a), "falls higher"
        mark = "SEPARATES" if gap > 0 else "overlaps  "
        print(f"  {label:24s} falls {min(f):{fmt}}-{max(f):{fmt}}   "
              f"adl {min(a):{fmt}}-{max(a):{fmt}}   {mark} ({verdict}, gap {gap:+.0f})")
    print("\n  A signal that overlaps cannot be a gate at ANY threshold.")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dir", default=str(TRACE_DIR))
    ap.add_argument("--trace", help="score a single trace by name")
    ap.add_argument("--freefall", type=float, default=FALL_FREEFALL_THRESHOLD_G)
    ap.add_argument("--impact", type=float, default=FALL_IMPACT_THRESHOLD_G)
    ap.add_argument("--sweep", action="store_true")
    ap.add_argument("--signals", action="store_true",
                    help="compare candidate signals before changing the detector")
    args = ap.parse_args()

    directory = Path(args.dir)
    if not directory.exists():
        raise SystemExit(
            f"No traces at {directory}.\n"
            "Record some first:\n"
            "  python -m indepensense.safety.tests.manual.record_trace adl_walking\n"
            "  python -m indepensense.safety.tests.manual.record_trace fall_forward"
        )

    traces = load_traces(directory)
    if args.trace:
        traces = [t for t in traces if t.name == args.trace]
    if not traces:
        raise SystemExit(f"No traces matched in {directory}.")

    labelled = [t for t in traces if t.is_fall is not None]
    rates = {round(t.achieved_hz) for t in traces if t.achieved_hz}
    print(f"\n  {len(traces)} trace(s), {len(labelled)} labelled, from {directory}")
    print(f"  {sum(1 for t in labelled if t.is_fall)} falls, "
          f"{sum(1 for t in labelled if not t.is_fall)} daily activities")
    if rates:
        print(f"  recorded at {sorted(rates)} Hz")
        if min(rates) < 50:
            print("  WARNING: the freefall gate needs 0.1 s of consecutive samples.")
            print("           Below ~50 Hz that is a handful of readings and the")
            print("           result says as much about the sample rate as the algorithm.")

    if args.signals:
        signals(labelled)
    elif args.sweep:
        sweep(labelled, args.impact)
    else:
        report(score(labelled, args.freefall, args.impact), args.freefall, args.impact)
    print()


if __name__ == "__main__":
    main()
