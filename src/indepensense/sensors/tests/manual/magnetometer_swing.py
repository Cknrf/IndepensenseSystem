"""Calibrate the compass the way the vest is actually used: upright, turning.

This replaces the six-face sweep for this build. `magnetometer_calibrate`
fits a sphere in three dimensions, which needs the vest tumbled onto every
face — and on the assembled unit that never produced a usable result. The
best attempt, after its coverage problems were fixed, left 41.2% spread,
and fitting a *freely oriented* ellipsoid instead of the per-axis one got
that only to 38.1%. The samples do not lie on an ellipsoid at all.

Why the sweep was the wrong instrument
--------------------------------------

The magnetometer is mounted permanently and vertically on the vest, and
the wearer turns horizontally. The device is **never** upside down or on
its side in use. The sweep demanded exactly those orientations, which is
where anything magnetic mounted on something flexible shifts under
gravity — and a shifted component means the offset is a function of which
way up the vest is, which no stored calibration can follow.

So the sweep failed on orientations the device does not experience. The
fix is to stop measuring them.

What this does instead
----------------------

Turning upright through a full circle traces an **ellipse in one plane**:
the two horizontal field components, displaced from the origin by the
horizontal hard iron and stretched by horizontal soft iron. Fit that
ellipse and the heading is corrected.

Two or three unknowns rather than nine, measured in the only orientation
that matters. This is "swinging the compass" — the deviation card used in
marine navigation for a century — and it was already the planned fallback
here (`docs/deferred.md`, raised 2026-09-12 from a teammate's Arduino
prototype). Its revisit condition was *mounted calibration done and
heading error still too large*, which is now met.

It absorbs whatever the sphere fit could not, **without modelling it**:
hard iron, horizontal soft iron, residual mount tilt, all as one
correction. The price is that it is valid only for the worn orientation —
hold the vest on its side and the heading is meaningless. For a sensor
bolted upright to a vest, that is not a limitation.

What it cannot fix
------------------

A heading error that is not repeatable. If pointing north twice gives two
answers, nothing here helps — see `magnetometer_stability`. This assumes
the error is a fixed function of which way the vest faces.

Run on the Pi, standing where you will walk, holding the vest as worn:

    python -m indepensense.sensors.tests.manual.magnetometer_swing

Then confirm against a phone compass when it asks, and paste the printed
values into `config.py`.
"""
import math
import statistics
import time

from indepensense.config import (
    MAG_ADDRESS,
    MAG_FORWARD_AXIS,
    MAG_I2C_BUS,
    MAG_LEFT_AXIS,
)
from indepensense.sensors.base import heading_from_field
from indepensense.sensors.qmc5883p import QMC5883P
from indepensense.sensors.tests.manual.magnetometer_calibrate import (
    _TONE_BAD,
    _TONE_COUNTDOWN,
    _TONE_FINISH,
    _TONE_GOOD,
    _TONE_START,
    _beep,
    arc_covered,
    reject_outliers,
)

SWING_S = 30.0

# Worst heading error, in degrees, that the swing may leave.
#
# The sphere fit graded on the spread of corrected magnitudes, and this
# test did too at first — which was the wrong question. Spread is a proxy;
# a compass is judged in degrees. The two are related exactly enough to
# convert (see `heading_error_deg`), and converting changes the verdict:
# the sphere fit's 10% threshold is 2.7 degrees, far stricter than
# anything here needs, and the first real swing came in at 12.5% spread —
# graded BAD — which is 3.5 degrees.
#
# Five degrees is a third of `ORIENTATION_ALIGNED_TOLERANCE_DEG` (15),
# which is the tightest consumer. That leaves the rest of the budget for
# GPS bearing error and torso sway, which are larger and not fixable here.
_MAX_HEADING_ERROR_DEG = 5.0

# A full circle, less a little slack for starting slowly.
_GOOD_ARC_DEG = 330.0

_AXES = ("x", "y", "z")


def _component(field, spec):
    sign = -1.0 if spec.startswith("-") else 1.0
    return sign * field[_AXES.index(spec[-1])]


def fit_ellipse_2d(points):
    """Fit a general ellipse to `(u, v)` points. `(centre, transform)` or None.

    General rather than axis-aligned, because horizontal soft iron tilts
    the ellipse and a tilted one has a cross term that per-axis scales
    cannot express. Fitting it here, then reporting how much of it an
    axis-aligned correction recovers, is what decides whether the values
    can go into `config.py` as they stand.

    Five unknowns against several hundred points, in the plane the vest
    actually turns in. That is a far better conditioned problem than the
    nine-parameter fit over a tumbled sphere, which is the whole argument
    for this approach.
    """
    import numpy as np                  # lazy: Pi-only at module import time

    if len(points) < 40:
        return None

    data = np.asarray(points, dtype=float)
    u, v = data[:, 0], data[:, 1]

    design = np.column_stack([u * u, u * v, v * v, u, v])
    try:
        params, _res, rank, _sv = np.linalg.lstsq(
            design, np.ones(len(data)), rcond=None
        )
    except np.linalg.LinAlgError:
        return None
    if rank < 5:
        return None

    a, b, c, d, e = params
    shape = np.array([[a, b / 2.0], [b / 2.0, c]])
    values, _vectors = np.linalg.eigh(shape)
    if np.any(values <= 0):
        return None                     # a hyperbola, not an ellipse

    try:
        centre = np.linalg.solve(2 * shape, -np.array([d, e]))
    except np.linalg.LinAlgError:
        return None

    scale = 1.0 + float(centre @ shape @ centre)
    if scale <= 0:
        return None
    values, vectors = np.linalg.eigh(shape / scale)
    if np.any(values <= 0):
        return None
    transform = vectors @ np.diag(np.sqrt(values)) @ vectors.T
    return centre, transform


def axis_aligned_from(points):
    """`(centre, scales)` for the per-axis model `config.py` stores.

    Centre from the midpoints, scales normalising the two half-spans to
    their mean — the same convention as the three-axis calibration, so
    the numbers drop into the same fields.
    """
    us = [p[0] for p in points]
    vs = [p[1] for p in points]
    centre = ((max(us) + min(us)) / 2.0, (max(vs) + min(vs)) / 2.0)
    spans = ((max(us) - min(us)) / 2.0, (max(vs) - min(vs)) / 2.0)
    if min(spans) <= 0:
        return None
    mean_span = sum(spans) / 2.0
    return centre, (mean_span / spans[0], mean_span / spans[1])


def heading_error_deg(spread_pct):
    """Worst heading error implied by a spread of corrected magnitudes.

    A residual that still varies around the turn is an ellipse the
    correction did not fully round off, and for an ellipse the two are
    related in closed form: with semi-axes `1+d` and `1-d`, the spread of
    magnitudes is `2d` and the largest angular error is `arcsin(d)`.
    So the worst heading error is `arcsin(spread / 2)`.

    Checked against a numerical sweep of ellipse ratios: 12.2% spread
    gives 3.5 degrees both ways, 36.4% gives 10.6.

    Assumes the leftover distortion is elliptical, which is what soft iron
    and a residual tilt both produce. It is an estimate of the shape error
    only — absolute accuracy, including whether north is where the device
    thinks, is what the phone-compass check measures and nothing here can
    substitute for it.
    """
    half = min(1.0, max(0.0, spread_pct / 200.0))
    return math.degrees(math.asin(half))


def spread_of(points, centre, scales):
    """Percentage spread of corrected magnitudes, and their mean."""
    magnitudes = [
        math.hypot((u - centre[0]) * scales[0], (v - centre[1]) * scales[1])
        for u, v in points
    ]
    mean = statistics.fmean(magnitudes)
    if mean <= 0:
        return 100.0, 0.0
    return (max(magnitudes) - min(magnitudes)) / mean * 100.0, mean


def general_spread(points, fitted):
    """Percentage spread a full 2x2 correction would leave."""
    import numpy as np

    centre, transform = fitted
    corrected = (np.asarray(points, dtype=float) - centre) @ transform.T
    magnitudes = np.linalg.norm(corrected, axis=1)
    mean = float(magnitudes.mean())
    if mean <= 0:
        return 100.0
    return float(magnitudes.max() - magnitudes.min()) / mean * 100.0


def collect(mag, seconds):
    print(f"\n  Hold the vest UPRIGHT, exactly as it is worn.")
    print(f"  Turn yourself slowly through one full circle over "
          f"{seconds:.0f} seconds.")
    print("  Keep it level and against your body — this is the orientation")
    print("  the calibration will be valid for.")
    print()
    for remaining in (3, 2, 1):
        print(f"    {remaining}...", flush=True)
        _beep(_TONE_COUNTDOWN)
        time.sleep(0.7)
    print("    GO", flush=True)
    _beep(_TONE_START)

    samples = []
    started = time.time()
    while time.time() - started < seconds:
        reading = mag.read()
        if reading is not None:
            samples.append((reading.magnetic_x, reading.magnetic_y,
                            reading.magnetic_z))
            left = seconds - (time.time() - started)
            print(f"\r    {left:4.1f}s  {len(samples):4d} samples", end="",
                  flush=True)
        time.sleep(0.05)
    print()
    _beep(_TONE_FINISH)
    return samples


def main():
    print(__doc__.split("Run on the Pi")[0].rstrip())
    print("=" * 70)

    mag = QMC5883P(bus_number=MAG_I2C_BUS, address=MAG_ADDRESS)
    try:
        samples = collect(mag, SWING_S)
    finally:
        mag.close()

    if len(samples) < 60:
        print("\nToo few samples — the magnetometer is not returning data.")
        _beep(_TONE_BAD)
        return 1

    kept, dropped = reject_outliers(samples)
    if dropped:
        print(f"\n  {dropped} of {len(samples)} samples discarded as impossible.")

    # Only the two horizontal components matter; the vertical axis plays no
    # part in heading and is exactly what this test refuses to measure.
    plane = [(_component(s, MAG_FORWARD_AXIS), _component(s, MAG_LEFT_AXIS))
             for s in kept]

    arc = arc_covered([(u, v, 0.0) for u, v in plane])
    print(f"\n  Turned {arc:.0f}° of a full circle.")
    if arc < _GOOD_ARC_DEG:
        print(f"  Not enough. Want {_GOOD_ARC_DEG:.0f}° or more — the unswept")
        print("  part of the circle is where the fit has nothing to go on.")
        _beep(_TONE_BAD)
        return 1

    aligned = axis_aligned_from(plane)
    if aligned is None:
        print("  One axis never moved. The vest was not turned, or the mount")
        print("  axes in config.py are wrong.")
        _beep(_TONE_BAD)
        return 1

    centre, scales = aligned
    spread_pct, field_ut = spread_of(plane, centre, scales)
    error_deg = heading_error_deg(spread_pct)
    good = error_deg <= _MAX_HEADING_ERROR_DEG

    print()
    print("  " + "-" * 64)
    print(f"  SWING QUALITY: {'GOOD' if good else 'BAD'}")
    print(f"  worst heading error about {error_deg:.1f}°, "
          f"against the {_MAX_HEADING_ERROR_DEG:.0f}° this needs")
    print(f"  (corrected field {field_ut:.1f} μT, varying {spread_pct:.1f}% "
          "around the turn)")
    print("  " + "-" * 64)
    print()

    fitted = fit_ellipse_2d(plane)
    if fitted is not None:
        general = general_spread(plane, fitted)
        print(f"  A full 2x2 correction would leave "
              f"{heading_error_deg(general):.1f}° ({general:.1f}% spread),")
        print(f"  against {error_deg:.1f}° from the per-axis model. A large gap")
        print("  means horizontal soft iron has tilted the ellipse; a small")
        print("  one means the simple model is enough and the values below")
        print("  can be used as they are.")
        print()

    if not good:
        print("  The heading will not be reliable. Before re-running, check")
        print("  `magnetometer_stability` — if pointing the same way twice")
        print("  gives two answers, no calibration of any kind will help.")
        _beep(_TONE_BAD)
        return 1

    forward_axis = MAG_FORWARD_AXIS[-1]
    left_axis = MAG_LEFT_AXIS[-1]
    forward_sign = -1.0 if MAG_FORWARD_AXIS.startswith("-") else 1.0
    left_sign = -1.0 if MAG_LEFT_AXIS.startswith("-") else 1.0

    # The fit ran on the *signed components*; config stores per raw axis.
    # component = sign * raw, so the raw-axis offset is sign * centre.
    offsets = {forward_axis: forward_sign * centre[0],
               left_axis: left_sign * centre[1]}
    axis_scales = {forward_axis: scales[0], left_axis: scales[1]}

    print("  Paste into `src/indepensense/config.py`:")
    print()
    for axis in _AXES:
        print(f"    MAG_OFFSET_{axis.upper()} = {offsets.get(axis, 0.0):.3f}")
    for axis in _AXES:
        print(f"    MAG_SCALE_{axis.upper()} = {axis_scales.get(axis, 1.0):.4f}")
    print()
    print("  The vertical axis stays 0.0 / 1.0 on purpose: heading never")
    print("  reads it, and this test deliberately did not measure it.")
    print()

    corrected = [
        ((u - centre[0]) * scales[0], (v - centre[1]) * scales[1])
        for u, v in plane
    ]
    print("  NOW SET ZERO. Face a direction you can check — a street you can")
    print("  read off a satellite map, or a phone compass held well away from")
    print("  the vest. Note what this device reports once the values above are")
    print("  in config.py, then:")
    print()
    print("      MAG_HEADING_OFFSET_DEG = (true bearing) - (reported heading)")
    print()
    print("  Check all four cardinals before trusting it. A constant error is")
    print("  this offset; an error that changes with direction means the swing")
    print("  did not capture the distortion and the values above are wrong.")
    print()
    print(f"  For reference, the swing covered headings "
          f"{min(heading_from_field(f, l) for f, l in corrected):.0f}° to "
          f"{max(heading_from_field(f, l) for f, l in corrected):.0f}°.")
    _beep(_TONE_GOOD)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
