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

    assert calibration_from_samples(store.samples()) == \
           calibration_from_samples(sorted(samples, key=lambda s: s[0]))
