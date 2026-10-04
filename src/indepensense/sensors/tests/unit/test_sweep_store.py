"""Unit tests for the face-at-a-time calibration sweep.

The split exists because one spoiled face used to cost all six. What it
buys in convenience it risks in correctness: the offsets are the device's
OWN magnetic field, valid only for the arrangement that produced them, and
six separate commands make it easy to change that arrangement halfway
without noticing.

Nothing can detect a re-seated battery. These cover what can be detected —
a face out of line with the others, a session left open too long — and the
property that matters most: both modes must derive identical numbers from
identical samples, or the convenient one quietly becomes the wrong one.
"""
import math
import statistics

import pytest

from indepensense.sensors.tests.manual.magnetometer_calibrate import (
    calibration_from_samples,
)
from indepensense.sensors.tests.manual.sweep_store import FACES, SweepStore


def _sphere(count=60, radius=45.0, centre=(0.0, 0.0, 0.0), scale=(1.0, 1.0, 1.0)):
    """Points on a sphere, optionally offset and squashed per axis.

    Stands in for a clean sweep: a correctly behaving sensor reads the
    same field strength in every orientation, so its raw samples lie on a
    sphere displaced by the hard-iron offset.
    """
    points = []
    for i in range(count):
        # Deterministic spiral — no RNG, so a failure is reproducible.
        phi = math.acos(1 - 2 * (i + 0.5) / count)
        theta = math.pi * (1 + 5 ** 0.5) * (i + 0.5)
        points.append((
            centre[0] + radius * math.sin(phi) * math.cos(theta) / scale[0],
            centre[1] + radius * math.sin(phi) * math.sin(theta) / scale[1],
            centre[2] + radius * math.cos(phi) / scale[2],
        ))
    return points


@pytest.fixture
def store(tmp_path):
    return SweepStore(tmp_path / "sweep.json")


# --- the maths ---------------------------------------------------------------

def test_recovers_a_known_hard_iron_offset():
    samples = _sphere(centre=(12.0, -7.0, 3.0))

    offsets, _scales, _spans = calibration_from_samples(samples)

    assert offsets[0] == pytest.approx(12.0, abs=1.5)
    assert offsets[1] == pytest.approx(-7.0, abs=1.5)
    assert offsets[2] == pytest.approx(3.0, abs=1.5)


def test_recovers_a_known_soft_iron_scale():
    """One axis reading short must be scaled back up, not left squashed."""
    samples = _sphere(scale=(1.0, 2.0, 1.0))

    _offsets, scales, _spans = calibration_from_samples(samples)

    assert scales[1] / scales[0] == pytest.approx(2.0, rel=0.1)


def test_an_axis_that_never_moved_is_an_error_not_a_bad_grade():
    """A dead axis is a different failure from a poor sweep, and must not
    print as "try rotating more"."""
    flat = [(x, y, 0.0) for x, y, _z in _sphere()]

    with pytest.raises(ValueError, match="never moved"):
        calibration_from_samples(flat)


def test_no_samples_is_an_error():
    with pytest.raises(ValueError, match="no samples"):
        calibration_from_samples([])


# --- the store ---------------------------------------------------------------

def test_faces_accumulate_across_separate_runs(tmp_path):
    """The whole point: each face is its own command, minutes apart."""
    path = tmp_path / "sweep.json"
    for face in ("front", "back"):
        reopened = SweepStore(path)          # as a fresh process would
        reopened.record(face, [(1.0, 2.0, 3.0)])
        reopened.save()

    assert SweepStore(path).recorded() == ["front", "back"]


def test_rerecording_a_face_replaces_it(store):
    """Re-running a face means the first attempt was bad. Keeping both
    would let the bad one go on poisoning the result."""
    store.record("front", [(1.0, 1.0, 1.0)] * 5)
    store.record("front", [(2.0, 2.0, 2.0)] * 3)

    assert len(store.data["faces"]["front"]["samples"]) == 3


def test_samples_come_back_flat_in_face_order(store):
    store.record("back", [(2.0, 0.0, 0.0)])
    store.record("front", [(1.0, 0.0, 0.0)])

    assert store.samples() == [(1.0, 0.0, 0.0), (2.0, 0.0, 0.0)]


def test_missing_faces_are_reported(store):
    store.record("front", [(1.0, 2.0, 3.0)])

    assert set(store.missing()) == set(FACES) - {"front"}


def test_an_unknown_face_is_rejected(store):
    with pytest.raises(ValueError, match="unknown face"):
        store.record("sideways", [(1.0, 2.0, 3.0)])


def test_a_corrupt_store_does_not_strand_the_operator(tmp_path):
    """Mid-sweep is the worst moment to hand somebody a traceback."""
    path = tmp_path / "sweep.json"
    path.write_text("{ this is not json")

    assert SweepStore(path).recorded() == []


# --- comparing faces -------------------------------------------------------
#
# The first version of this compared faces by their RAW mean field
# strength, reasoning that the ambient field is the same whichever way the
# vest points. That is true of the corrected field and false of the raw
# one: raw = Earth + hard-iron offset, and the offset is fixed in the
# sensor frame while Earth's field turns through it, so raw magnitude
# swings by twice the offset depending purely on how the operator
# rotated. On the first real sweep it ranged 22-50 uT, flagged a
# different innocent face every run, and cost three re-recordings of good
# data.
#
# The comparison is sound only on CORRECTED magnitudes, which do not
# exist until the calibration does.

def test_raw_magnitude_alone_does_not_condemn_a_face():
    """The regression. Two faces sweeping different parts of the same
    sphere have very different raw means and are both perfectly good."""
    offset = (14.0, 0.0, 0.0)
    near = [(offset[0] + 40.0, 0.0, 0.0)] * 20      # raw |B| 54
    far = [(offset[0] - 40.0, 0.0, 0.0)] * 20       # raw |B| 26

    near_mean = sum(math.dist(s, (0, 0, 0)) for s in near) / len(near)
    far_mean = sum(math.dist(s, (0, 0, 0)) for s in far) / len(far)

    # Over twice as large, from one honest offset and no interference.
    assert near_mean / far_mean > 2.0


def test_a_face_held_still_is_flagged(store):
    """The one per-face fault catchable without the calibration: samples
    that are all the same orientation pad the count and add nothing."""
    for face in FACES:
        store.record(face, _sphere(count=30))
    store.record("top", [(40.0, 1.0, 2.0)] * 30)

    assert [face for face, _swing in store.still_faces()] == ["top"]


def test_a_properly_rotated_face_is_not(store):
    for face in FACES:
        store.record(face, _sphere(count=30))

    assert store.still_faces() == []


def test_a_contaminated_face_is_caught_once_corrected(store):
    """What the raw check was reaching for, done where it holds. A face
    recorded in a much stronger field still reads differently after the
    offset is removed, because the offset cannot explain it."""
    from indepensense.sensors.tests.manual.magnetometer_calibrate import (
        face_diagnosis,
    )

    for face in FACES:
        store.record(face, _sphere(count=40, radius=45.0, centre=(10.0, 0.0, 0.0)))
    store.record("left", _sphere(count=40, radius=90.0, centre=(10.0, 0.0, 0.0)))

    diagnosis = face_diagnosis(store)

    assert len(diagnosis) == 1
    assert "left" in diagnosis[0]


def test_a_clean_sweep_flags_no_face(store):
    """A false alarm here sends somebody outside to redo good data, which
    is exactly what the previous check did three times."""
    from indepensense.sensors.tests.manual.magnetometer_calibrate import (
        face_diagnosis,
    )

    for index, face in enumerate(FACES):
        # Each face sweeps a different part of the same offset sphere —
        # very different raw means, identical corrected ones.
        store.record(face, _sphere(count=40, centre=(13.0, -6.0, 4.0))[index::6])

    assert face_diagnosis(store) == []


# --- the two modes must agree ------------------------------------------------

def test_both_modes_derive_the_same_calibration(store):
    """The split must be a change in how samples are collected, nothing
    more. If the convenient mode computed even slightly different numbers
    it would be the wrong one to use, and nobody would know."""
    samples = _sphere(count=60, centre=(9.0, -4.0, 2.0), scale=(1.0, 1.3, 0.8))

    for index, face in enumerate(FACES):
        store.record(face, samples[index::len(FACES)])

    from_faces = calibration_from_samples(store.samples())
    from_one_run = calibration_from_samples(sorted(samples, key=lambda s: s[0]))

    # `approx`, not `==`: the least-squares fit sums over the samples, so
    # a different ordering moves the result in the last few bits. What
    # must hold is that the two modes agree to far better than anybody
    # could measure, not that they are bit-identical.
    for mine, theirs in zip(from_faces, from_one_run):
        assert mine == pytest.approx(theirs, rel=1e-6)


# --- robustness of the derivation -------------------------------------------
#
# The first real sweep graded BAD at 134.8% spread, and the cause was not
# the environment: min/max takes each axis' offset from exactly two
# samples out of 1150, so anything that disturbs an extreme decides the
# answer. A least-squares fit uses every sample — but weights by the
# square of the residual, so one 900 uT frame outvotes a thousand good
# ones. Both collapse under a single bad reading, which is why rejection
# has to happen before either.

def _circles(centre=(12.0, -5.0, 3.0), scales=(1.0, 1.25, 0.85), radius=42.0,
             per=120, faces=6):
    """Six circles, as six single-axis rotations actually produce.

    Not a filled sphere: rotating a vest about one axis traces a circle,
    so this is the coverage the real procedure gives, extremes and all.
    """
    points = []
    for face in range(faces):
        tilt = math.pi * face / faces
        for i in range(per):
            angle = 2 * math.pi * i / per
            unit = (math.cos(angle),
                    math.sin(angle) * math.cos(tilt),
                    math.sin(angle) * math.sin(tilt))
            points.append(tuple(centre[axis] + radius * unit[axis] / scales[axis]
                                for axis in (0, 1, 2)))
    return points


def test_the_fit_recovers_the_offset_from_single_axis_circles():
    """The coverage the real procedure gives, not an idealised sphere."""
    offsets, _scales, _spans = calibration_from_samples(_circles())

    assert offsets == pytest.approx((12.0, -5.0, 3.0), abs=0.5)


def test_one_corrupted_frame_does_not_decide_the_answer():
    """The regression. Two bad frames moved the min/max offset from 12.0
    to 25.0 and the unguarded fit to -537.7."""
    points = _circles()
    points[300] = (900.0, -12.0, 5.0)
    points[500] = (-850.0, 4.0, 2.0)

    offsets, _scales, _spans = calibration_from_samples(points)

    assert offsets == pytest.approx((12.0, -5.0, 3.0), abs=0.5)


def test_many_corrupted_frames_are_still_survivable():
    """A bit-banged bus does not mangle exactly one frame."""
    from indepensense.sensors.tests.manual.magnetometer_calibrate import (
        reject_outliers,
    )

    points = _circles()
    for index in range(0, len(points), 60):
        points[index] = (600.0 + index, -12.0, 5.0)

    _kept, dropped = reject_outliers(points)
    offsets, _scales, _spans = calibration_from_samples(points)

    assert dropped == len(range(0, len(points), 60))
    assert offsets == pytest.approx((12.0, -5.0, 3.0), abs=0.5)


def test_a_clean_sweep_loses_no_samples():
    """Discarding real coverage to tidy the numbers is worse than keeping
    a stray, so the rejection must be inert on good data."""
    from indepensense.sensors.tests.manual.magnetometer_calibrate import (
        reject_outliers,
    )

    _kept, dropped = reject_outliers(_circles())

    assert dropped == 0


def test_the_fit_recovers_soft_iron_scales():
    points = _circles(scales=(1.0, 1.25, 0.85))

    _offsets, scales, _spans = calibration_from_samples(points)

    # Ratios, not absolutes: the convention normalises to the mean axis.
    assert scales[1] / scales[0] == pytest.approx(1.25, rel=0.05)
    assert scales[2] / scales[0] == pytest.approx(0.85, rel=0.05)


def test_a_flat_sweep_falls_back_rather_than_inventing_an_ellipsoid():
    """One plane of rotation does not enclose a volume. Better to decline
    than to return six confident numbers from a degenerate system."""
    from indepensense.sensors.tests.manual.magnetometer_calibrate import (
        fit_ellipsoid,
    )

    flat = [(x, y, 3.0) for x, y, _z in _circles(faces=1)]

    assert fit_ellipsoid(flat) is None


def test_too_few_samples_to_fit_falls_back():
    from indepensense.sensors.tests.manual.magnetometer_calibrate import (
        fit_ellipsoid,
    )

    assert fit_ellipsoid(_sphere(count=10)) is None


# --- a sweep spread across sessions -----------------------------------------
#
# Reported from the field: five faces recorded one evening, the location
# changed overnight because the first spot turned out to have a distorted
# field, then one face re-recorded in the new place. The warning fired
# correctly — and the tool printed a verdict underneath it anyway. That
# verdict happened to be BAD. Had the mixture graded GOOD, six numbers
# would have gone into config.py with a caution above them, and numbers
# win that argument every time.

def test_faces_from_an_earlier_session_are_named(store):
    for face in ("back", "left", "right", "top", "bottom"):
        store.record(face, [(45.0, 0.0, 0.0)], now=0.0)
    store.record("front", [(45.0, 0.0, 0.0)], now=15.2 * 3600)

    stale = store.stale_faces()

    assert {face for face, _age in stale} == {"back", "left", "right",
                                             "top", "bottom"}
    assert all(age == pytest.approx(15.2 * 3600) for _face, age in stale)


def test_the_newest_face_is_never_itself_stale(store):
    """It is the reference the others are judged against."""
    store.record("back", [(45.0, 0.0, 0.0)], now=0.0)
    store.record("front", [(45.0, 0.0, 0.0)], now=10 * 3600)

    assert [face for face, _age in store.stale_faces()] == ["back"]


def test_re_recording_a_stale_face_clears_it(store):
    """Why no override flag is needed: the remedy and the fix are the
    same action."""
    store.record("back", [(45.0, 0.0, 0.0)], now=0.0)
    store.record("front", [(45.0, 0.0, 0.0)], now=10 * 3600)
    assert store.is_stale()

    store.record("back", [(45.0, 0.0, 0.0)], now=10 * 3600 + 60)

    assert store.stale_faces() == []


def test_one_face_alone_is_never_stale(store):
    store.record("front", [(45.0, 0.0, 0.0)], now=0.0)

    assert store.stale_faces() == []


def test_a_stale_session_withholds_values_whatever_the_grade(tmp_path,
                                                             monkeypatch,
                                                             capsys):
    """The actual regression: a warning above a full set of numbers is
    not a guard."""
    import argparse

    from indepensense.sensors.tests.manual import magnetometer_calibrate as cal

    path = tmp_path / "sweep.json"
    monkeypatch.setattr(cal, "_SWEEP_PATH", path)

    store = SweepStore(path)
    clean = _sphere(count=60, centre=(10.0, -4.0, 2.0))
    for index, face in enumerate(FACES):
        # A sweep good enough to grade well — but spread over two days.
        when = 0.0 if face != "front" else 15.2 * 3600
        store.record(face, clean[index::6], now=when)
    store.save()

    args = argparse.Namespace(face=None, status=False, finish=True,
                              reset=False, spin=10.0, seconds=None)
    code = cal.run_face_mode(args)
    output = capsys.readouterr().out

    assert code == 1, "a stale sweep must not report success"
    assert "MAG_OFFSET_X" not in output, "values printed from a mixed sweep"
    assert "not one sweep" in output


# --- how far round each face actually turned --------------------------------
#
# The number that was missing. Sample count says only that time passed,
# axis swing says the vest moved, raw range says where the circle sits
# relative to the hard-iron offset — and a half turn is indistinguishable
# from a full one in all three.
#
# It showed on the real vest as the same face, recorded three times
# minutes apart in one place, giving raw ranges of 17-37, 31-65 and
# 34-62 uT. Re-recording that one face moved the y half-span from 23.3 to
# 35.6, so a single face had been carrying most of one axis' coverage.

def _arc(degrees, count=190, centre=(12.0, -5.0, 3.0), radius=42.0):
    """Samples along part of a circle, as one-axis rotation produces."""
    points = []
    for i in range(count):
        angle = math.radians(degrees) * i / max(1, count - 1)
        points.append((centre[0] + radius * math.cos(angle),
                       centre[1] + radius * math.sin(angle),
                       centre[2] + 5.0))
    return points


@pytest.mark.parametrize("turned,expected", [
    (360, 360), (350, 360), (300, 310), (270, 280), (180, 180),
])
def test_the_arc_is_measured_to_within_a_sector(turned, expected):
    from indepensense.sensors.tests.manual.magnetometer_calibrate import (
        arc_covered,
    )

    assert arc_covered(_arc(turned)) == pytest.approx(expected, abs=15)


def test_a_half_turn_is_not_mistaken_for_a_whole_one():
    """The whole point — these look identical in every other measure."""
    from indepensense.sensors.tests.manual.magnetometer_calibrate import (
        arc_covered, _GOOD_ARC_DEG,
    )

    assert arc_covered(_arc(360)) >= _GOOD_ARC_DEG
    assert arc_covered(_arc(180)) < _GOOD_ARC_DEG


def test_rocking_back_and_forth_earns_no_credit_for_the_repeats():
    """A vest waved through 90 degrees many times covers 90 degrees."""
    from indepensense.sensors.tests.manual.magnetometer_calibrate import (
        arc_covered,
    )

    rocked = _arc(90) + list(reversed(_arc(90))) + _arc(90)

    assert arc_covered(rocked) < 120


def test_the_angle_is_taken_about_the_circle_not_the_samples():
    """The bug found while building this: measuring from the centroid of
    a partial arc inflates it, because the centroid sits inside the arc
    rather than at the centre it curves around. A half turn read 260
    degrees and a quarter turn 220."""
    from indepensense.sensors.tests.manual.magnetometer_calibrate import (
        arc_covered,
    )

    assert arc_covered(_arc(180)) == pytest.approx(180, abs=20)
    assert arc_covered(_arc(90)) == pytest.approx(90, abs=20)


def test_too_few_samples_to_judge_reports_nothing_rather_than_guessing():
    from indepensense.sensors.tests.manual.magnetometer_calibrate import (
        arc_covered,
    )

    assert arc_covered(_arc(360, count=4)) == 0.0


# --- is the stored model wide enough? ---------------------------------------
#
# `config.py` keeps one offset and one scale per axis, which straightens
# an ellipsoid already lined up with the sensor's axes. Soft iron —
# ferrous material near the sensor bending the field — tilts it, and a
# tilted ellipsoid has cross terms no per-axis scale can express.
#
# The real vest, once its coverage problem was fixed, still graded BAD at
# 41.2% spread with balanced half-spans, no flagged face and a correct
# 42 uT field. A deliberately tilted synthetic sweep reproduces that
# almost exactly, which is what the diagnostic below is for.

def _tilted_sweep(count=600, centre=(12.0, -5.0, 3.0), radius=42.0,
                  stretch=(1.0, 0.65, 1.25), degrees=35.0):
    """A sphere squashed along axes rotated away from the sensor's."""
    import numpy as np

    angle = math.radians(degrees)
    rotation = np.array([[math.cos(angle), -math.sin(angle), 0.0],
                         [math.sin(angle), math.cos(angle), 0.0],
                         [0.0, 0.0, 1.0]])
    distortion = rotation @ np.diag(stretch) @ rotation.T

    points = []
    for i in range(count):
        phi = math.acos(1 - 2 * ((i + 0.5) / count))
        theta = math.pi * (1 + 5 ** 0.5) * (i + 0.5)
        vector = np.array([radius * math.sin(phi) * math.cos(theta),
                           radius * math.sin(phi) * math.sin(theta),
                           radius * math.cos(phi)])
        points.append(tuple(np.asarray(centre) + distortion @ vector))
    return points


def test_the_per_axis_model_handles_hard_iron_alone():
    """The case the stored model was designed for."""
    from indepensense.sensors.tests.manual.magnetometer_calibrate import (
        corrected_magnitudes, general_fit_spread,
    )

    points = _sphere(count=600, centre=(12.0, -5.0, 3.0))
    offsets, scales, _spans = calibration_from_samples(points)
    magnitudes = corrected_magnitudes(points, offsets, scales)
    per_axis = (max(magnitudes) - min(magnitudes)) / statistics.fmean(magnitudes) * 100

    assert per_axis < 1.0
    assert general_fit_spread(points)[0] < 1.0


def test_tilted_soft_iron_defeats_the_per_axis_model():
    """And the general fit shows it was the model, not the sweep."""
    from indepensense.sensors.tests.manual.magnetometer_calibrate import (
        corrected_magnitudes, general_fit_spread,
    )

    points = _tilted_sweep()
    offsets, scales, _spans = calibration_from_samples(points)
    magnitudes = corrected_magnitudes(points, offsets, scales)
    per_axis = (max(magnitudes) - min(magnitudes)) / statistics.fmean(magnitudes) * 100

    assert per_axis > 20.0, "this sweep should defeat a per-axis correction"
    assert general_fit_spread(points)[0] < 1.0, "a 3x3 correction should fix it"


def test_the_general_fit_declines_on_data_that_is_not_an_ellipsoid():
    """It must not answer "a wider model would fix it" when nothing would
    — that would send somebody rewriting the calibration for nothing."""
    from indepensense.sensors.tests.manual.magnetometer_calibrate import (
        fit_general_ellipsoid, general_fit_spread,
    )

    flat = [(x, y, 3.0) for x, y, _z in _sphere(count=600)]

    assert fit_general_ellipsoid(flat) is None
    assert general_fit_spread(flat) is None


def test_the_general_fit_needs_enough_samples():
    from indepensense.sensors.tests.manual.magnetometer_calibrate import (
        fit_general_ellipsoid,
    )

    assert fit_general_ellipsoid(_sphere(count=40)) is None
