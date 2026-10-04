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


@pytest.mark.parametrize("pool_name", ("CANDIDATES", "LOUDNESS_CANDIDATES"))
def test_every_candidate_is_a_valid_cue(pool_name):
    """The letters are hand-written in the module and never parsed, so
    nothing else would catch a malformed one until it was played."""
    import indepensense.voice.tests.manual.busy_cue_audition as audition

    pool = getattr(audition, pool_name)
    letters = [entry[0] for entry in pool]
    assert len(set(letters)) == len(letters), "duplicate candidate letter"

    for letter, description, steps, gap_s, amplitude in pool:
        assert steps, f"{letter}: no tones"
        assert description.strip(), f"{letter}: no description to read out"
        assert gap_s >= 0.0
        # None means "use the default"; a real value has to be playable.
        # Above 1.0 the sine clips, which is heard as a buzz rather than
        # as a louder tone — the opposite of what the loudness round is
        # trying to buy.
        assert amplitude is None or 0.0 < amplitude <= 1.0, (
            f"{letter}: amplitude {amplitude}"
        )
        for frequency, seconds in steps:
            # Audible band, and long enough to have a pitch rather than
            # being heard as a click.
            assert 100.0 <= frequency <= 4000.0, f"{letter}: {frequency} Hz"
            assert seconds >= 0.05, f"{letter}: {seconds * 1000:.0f} ms tone"


def test_no_letter_is_used_by_both_rounds():
    """They are selected by letter on one command line, so a letter in
    both pools would play whichever round happened to be chosen — and
    silently audition the wrong cue."""
    import indepensense.voice.tests.manual.busy_cue_audition as audition

    shape = {entry[0] for entry in audition.CANDIDATES}
    loud = {entry[0] for entry in audition.LOUDNESS_CANDIDATES}
    assert not (shape & loud), f"letters in both rounds: {sorted(shape & loud)}"


def test_the_loudness_candidates_respect_the_octave_rule():
    """`test_audio_playback` requires an octave between the two
    single-tone cues, so a candidate between 260 and 1040 Hz would win by
    ear and then fail the suite when it was adopted. Catching it here
    keeps the audition from offering a choice that cannot be taken."""
    import math

    import indepensense.voice.tests.manual.busy_cue_audition as audition

    (blip_hz, _), = audition.WAITING_STEPS
    for letter, _d, steps, _g, _a in audition.LOUDNESS_CANDIDATES:
        if len(steps) != 1:
            continue        # told apart by tone count instead
        (frequency, _), = steps
        octaves = abs(math.log2(frequency / blip_hz))
        assert octaves >= 1.0, (
            f"{letter}: {frequency:.0f} Hz is {octaves:.2f} octaves from the "
            f"{blip_hz:.0f} Hz waiting blip — adopting it would fail "
            f"test_the_two_single_tone_cues_are_kept_apart"
        )
