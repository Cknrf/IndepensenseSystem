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


# --- the cross-face check ----------------------------------------------------

def test_a_face_with_a_different_field_is_flagged(store):
    """The ambient field is the same whichever way the vest points, so a
    face reading far from the others saw something they did not —
    interference, or a setup that changed between runs."""
    for face in ("front", "back", "left", "right", "top"):
        store.record(face, [(45.0, 0.0, 0.0)] * 10)
    store.record("bottom", [(90.0, 0.0, 0.0)] * 10)

    odd = store.odd_faces()

    assert [face for face, _m, _med in odd] == ["bottom"]


def test_a_consistent_sweep_flags_nothing(store):
    for face in FACES:
        store.record(face, [(45.0, 0.0, 0.0)] * 10)

    assert store.odd_faces() == []


def test_too_few_faces_to_judge_flags_nothing(store):
    """Two faces have no median worth comparing against, and a false
    alarm here would send somebody outside to redo a good face."""
    store.record("front", [(45.0, 0.0, 0.0)] * 10)
    store.record("back", [(90.0, 0.0, 0.0)] * 10)

    assert store.odd_faces() == []


def test_a_session_left_open_for_hours_is_called_out(store):
    store.record("front", [(45.0, 0.0, 0.0)], now=0.0)
    store.record("back", [(45.0, 0.0, 0.0)], now=5 * 60 * 60)

    assert store.is_stale()


def test_a_session_done_in_one_go_is_not(store):
    store.record("front", [(45.0, 0.0, 0.0)], now=0.0)
    store.record("back", [(45.0, 0.0, 0.0)], now=120.0)

    assert not store.is_stale()


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
