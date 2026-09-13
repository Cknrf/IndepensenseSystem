"""Unit tests for speaker volume state.

The floor is the point. Speech is this device's only channel to its user,
so a volume low enough to be inaudible on a busy road is a trap with no
way out — the user cannot hear the response that would let them turn it
back up, and there is no screen to fall back on.

`wpctl` is replaced with a recorder, so these run anywhere.
"""
import subprocess

import pytest

from indepensense.voice import volume as volume_module
from indepensense.voice.volume import VolumeState


@pytest.fixture
def sink(monkeypatch):
    """Capture what would have been sent to the audio sink."""
    calls: list[list[str]] = []

    def _run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, b"", b"")

    monkeypatch.setattr(volume_module.subprocess, "run", _run)
    return calls


def _volume(sink, default=80, path=None, minimum=20, maximum=100, step=10):
    return VolumeState(
        default_percent=default,
        minimum_percent=minimum,
        maximum_percent=maximum,
        step_percent=step,
        state_path=path,
    )


# --- the floor ---------------------------------------------------------------

def test_the_volume_cannot_be_set_below_the_floor(sink):
    """A user who cannot hear the device has no way to ask for it back."""
    v = _volume(sink)

    assert v.set(5) == 20
    assert v.current == 20


def test_stepping_down_stops_at_the_floor(sink):
    v = _volume(sink, default=25)

    v.quieter()
    v.quieter()
    v.quieter()

    assert v.current == 20


def test_the_floor_is_reported_as_reached(sink):
    v = _volume(sink, default=20)
    assert v.at_minimum() is True


def test_a_zero_request_still_lands_on_the_floor(sink):
    assert _volume(sink).set(0) == 20


# --- the ceiling -------------------------------------------------------------

def test_the_volume_cannot_exceed_the_maximum(sink):
    assert _volume(sink).set(150) == 100


def test_stepping_up_stops_at_the_maximum(sink):
    v = _volume(sink, default=95)
    v.louder()
    v.louder()
    assert v.current == 100
    assert v.at_maximum() is True


# --- stepping ----------------------------------------------------------------

def test_louder_moves_one_step(sink):
    assert _volume(sink, default=50).louder() == 60


def test_quieter_moves_one_step(sink):
    assert _volume(sink, default=50).quieter() == 40


def test_set_returns_what_actually_took_effect(sink):
    """Not a success flag — the caller says this number out loud. A user
    who asked for 10 and heard "20 percent" has learned the floor exists;
    one who heard "done" would think they were ignored."""
    assert _volume(sink).set(10) == 20
    assert _volume(sink).set(65) == 65


# --- the audio sink ----------------------------------------------------------

def test_setting_the_volume_reaches_the_sink(sink):
    v = _volume(sink)
    sink.clear()

    v.set(60)

    assert sink == [["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "60%"]]


def test_the_stored_value_is_pushed_at_startup(sink):
    """The sink keeps whatever the OS last had, which after a reboot is not
    necessarily what the user chose."""
    _volume(sink, default=45)

    assert sink[-1] == ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "45%"]


def test_the_sink_is_updated_even_when_the_value_is_unchanged(sink):
    """Re-asserting a level the user repeated is how they recover from the
    OS having drifted underneath us."""
    v = _volume(sink, default=60)
    sink.clear()

    v.set(60)

    assert len(sink) == 1


def test_a_missing_wpctl_does_not_raise(monkeypatch):
    """A wearable that refused to start over a missing mixer tool would be
    a worse outcome than one at the system default volume."""
    def _boom(command, **kwargs):
        raise FileNotFoundError("wpctl")

    monkeypatch.setattr(volume_module.subprocess, "run", _boom)

    v = VolumeState(80, 20, 100, 10)
    assert v.set(50) == 50          # state still tracks, audio just didn't move


def test_a_hanging_wpctl_does_not_raise(monkeypatch):
    def _hang(command, **kwargs):
        raise subprocess.TimeoutExpired(command, 3.0)

    monkeypatch.setattr(volume_module.subprocess, "run", _hang)
    assert VolumeState(80, 20, 100, 10).set(50) == 50


# --- persistence -------------------------------------------------------------

def test_the_volume_survives_a_restart(sink, tmp_path):
    path = tmp_path / "volume"
    _volume(sink, path=path).set(40)

    assert _volume(sink, path=path).current == 40


def test_a_missing_file_falls_back_to_the_default(sink, tmp_path):
    assert _volume(sink, default=70, path=tmp_path / "nothing").current == 70


def test_a_corrupt_file_falls_back_to_the_default(sink, tmp_path):
    path = tmp_path / "volume"
    path.write_text("very loud please")

    assert _volume(sink, default=70, path=path).current == 70


def test_a_stored_value_outside_the_band_is_clamped(sink, tmp_path):
    """A hand-edit or a file from before the floor existed must not put the
    device somewhere it can no longer be heard."""
    path = tmp_path / "volume"
    path.write_text("3")

    assert _volume(sink, path=path).current == 20


def test_an_unwritable_path_does_not_raise(sink, tmp_path):
    path = tmp_path / "nested"
    path.write_text("not a directory")

    v = _volume(sink, path=path / "volume")
    assert v.set(50) == 50          # session keeps it; reboot will not


# --- construction ------------------------------------------------------------

def test_an_impossible_band_is_rejected(sink):
    """A floor above the ceiling would silently pin the volume."""
    with pytest.raises(ValueError):
        VolumeState(80, minimum_percent=90, maximum_percent=50, step_percent=10)


def test_a_zero_floor_is_rejected(sink):
    """Silence is the one setting this device must never allow."""
    with pytest.raises(ValueError):
        VolumeState(80, minimum_percent=0, maximum_percent=100, step_percent=10)
