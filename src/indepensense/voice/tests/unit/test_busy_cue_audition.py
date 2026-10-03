"""Unit tests for the busy-cue audition's hand-typed input.

The script itself is judged by ear and cannot be tested here. Its cue
parser can be: it reads a spec typed at a prompt, and a fragment silently
dropped would be heard as "that cue does not work" rather than as a typo,
which is the slowest possible way to discover a mistake.
"""
import pytest

from indepensense.voice.tests.manual.busy_cue_audition import (
    CANDIDATES,
    describe,
    parse_cue,
)


def test_parses_a_sequence_of_tones():
    assert parse_cue("300:0.07,440:0.1") == [(300.0, 0.07), (440.0, 0.1)]


def test_tolerates_the_spaces_a_shell_user_leaves():
    assert parse_cue(" 300:0.07 , 440:0.1 ,") == [(300.0, 0.07), (440.0, 0.1)]


@pytest.mark.parametrize("spec", ["oops", "300", "300:", ":0.07", "x:0.07",
                                  "300:y", "", " , "])
def test_a_malformed_spec_is_rejected_rather_than_half_played(spec):
    with pytest.raises(ValueError):
        parse_cue(spec)


def test_the_error_names_the_offending_fragment():
    """So the fix is obvious from the message alone."""
    with pytest.raises(ValueError, match="440x"):
        parse_cue("300:0.07,440x0.1")


def test_describe_reports_the_total_including_the_gaps():
    # Two 100 ms tones with a 50 ms gap is 250 ms, not 200.
    assert "250 ms" in describe([(300.0, 0.1), (300.0, 0.1)], 0.05)


def test_every_candidate_is_a_valid_cue():
    """The letters are hand-written in the module and never parsed, so
    nothing else would catch a malformed one until it was played."""
    letters = [letter for letter, _d, _s, _g in CANDIDATES]
    assert len(set(letters)) == len(letters), "duplicate candidate letter"

    for letter, description, steps, gap_s in CANDIDATES:
        assert steps, f"{letter}: no tones"
        assert description.strip(), f"{letter}: no description to read out"
        assert gap_s >= 0.0
        for frequency, seconds in steps:
            # Audible band, and long enough to have a pitch rather than
            # being heard as a click.
            assert 100.0 <= frequency <= 4000.0, f"{letter}: {frequency} Hz"
            assert seconds >= 0.05, f"{letter}: {seconds * 1000:.0f} ms tone"
