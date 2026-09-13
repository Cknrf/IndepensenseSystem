"""Unit tests for the latency benchmark's statistics and reporting.

The benchmark itself needs Whisper, Piper and Ollama, so it is a manual
test. But the arithmetic it reports is pure, and getting a percentile
subtly wrong would quietly misstate a number the thesis quotes — which is
exactly the kind of error nobody catches by eye.

Imports the manual module directly. That works because every heavy
dependency inside it is imported lazily, the same property that lets the
real drivers be introspected on a Mac.
"""
import csv

import pytest

from indepensense.voice.tests.manual.latency_bench import (
    Sample,
    _stage_line,
    format_stats,
    percentile,
    summarise,
    write_csv,
)


# --- percentile --------------------------------------------------------------

def test_the_median_of_an_odd_sample_is_the_middle_value():
    assert percentile([1.0, 2.0, 3.0], 0.5) == 2.0


def test_the_median_of_an_even_sample_interpolates():
    assert percentile([1.0, 2.0, 3.0, 4.0], 0.5) == 2.5


def test_the_hundredth_percentile_is_the_maximum():
    assert percentile([1.0, 5.0, 3.0], 1.0) == 5.0


def test_the_zeroth_percentile_is_the_minimum():
    assert percentile([4.0, 1.0, 3.0], 0.0) == 1.0


def test_input_order_does_not_matter():
    assert percentile([3.0, 1.0, 2.0], 0.5) == percentile([1.0, 2.0, 3.0], 0.5)


def test_a_single_sample_is_its_own_percentile():
    """A run that produced one measurement should still print, not raise."""
    assert percentile([2.5], 0.95) == 2.5


def test_p95_interpolates_rather_than_snapping_to_a_rank():
    """Twenty evenly spaced values: position 0.95*19 = 18.05, so the answer
    sits just past the 19th value rather than landing on the maximum."""
    values = [float(i) for i in range(20)]
    assert percentile(values, 0.95) == pytest.approx(18.05)


def test_no_values_is_an_error_not_a_zero():
    """Returning 0.0 would read as "instantaneous" in a latency report."""
    with pytest.raises(ValueError):
        percentile([], 0.5)


# --- summarise ---------------------------------------------------------------

def test_summarise_reports_every_figure():
    stats = summarise([1.0, 2.0, 3.0, 4.0])

    assert stats.n == 4
    assert stats.median == 2.5
    assert stats.minimum == 1.0
    assert stats.maximum == 4.0
    assert stats.mean == 2.5


def test_summarising_nothing_gives_none():
    """A stage that was skipped has no statistics — distinct from a stage
    that ran and took no time."""
    assert summarise([]) is None


def test_a_skipped_stage_is_reported_as_such():
    assert "not measured" in format_stats("NLU (classify)", None)


def test_a_measured_stage_shows_its_figures():
    line = format_stats("STT (transcribe)", summarise([1.0, 2.0, 3.0]))

    assert "n=3" in line
    assert "median" in line and "p95" in line


# --- per-measurement progress line -------------------------------------------

def test_the_progress_line_omits_skipped_stages():
    """Printing a skipped stage as 0.00 s would read as "instant" rather
    than "did not run"."""
    sample = Sample(language="en", clip="a.wav", audio_s=1.0, repetition=0,
                    stt_s=1.5, nlu_s=None, tts_s=None)

    line = _stage_line(sample)

    assert "stt" in line
    assert "nlu" not in line and "tts" not in line


def test_the_progress_line_shows_every_stage_that_ran():
    sample = Sample(language="tl", clip="a.wav", audio_s=1.0, repetition=0,
                    stt_s=2.0, nlu_s=1.0, tts_s=0.5)

    line = _stage_line(sample)

    assert all(stage in line for stage in ("stt", "nlu", "tts"))


# --- totals ------------------------------------------------------------------

def test_the_total_sums_the_stages_that_ran():
    sample = Sample(language="en", clip="a.wav", audio_s=1.0, repetition=0,
                    stt_s=2.0, nlu_s=1.0, tts_s=0.5)

    assert sample.total_s == pytest.approx(3.5)


def test_a_skipped_stage_does_not_inflate_the_total():
    """`--no-nlu` should give a smaller total, not the same total with a
    hole silently counted as zero somewhere else."""
    sample = Sample(language="en", clip="a.wav", audio_s=1.0, repetition=0,
                    stt_s=2.0, nlu_s=None, tts_s=0.5)

    assert sample.total_s == pytest.approx(2.5)


# --- CSV ---------------------------------------------------------------------

def test_the_csv_has_one_row_per_measurement(tmp_path):
    samples = [
        Sample("en", "a.wav", 1.2, 0, stt_s=1.0, nlu_s=0.5, tts_s=0.3,
               transcript="what time is it", intent="system.time"),
        Sample("tl", "a.wav", 1.2, 0, stt_s=2.4, nlu_s=0.6, tts_s=0.4,
               transcript="anong oras na", intent="system.time"),
    ]
    path = tmp_path / "bench.csv"

    write_csv(samples, path)

    rows = list(csv.DictReader(path.open()))
    assert len(rows) == 2
    assert rows[0]["language"] == "en"
    assert rows[1]["language"] == "tl"


def test_the_csv_keeps_the_transcript_and_intent(tmp_path):
    """Latency alongside what was actually recognised — a fast wrong
    answer is not a good result, and the thesis needs both columns."""
    path = tmp_path / "bench.csv"
    write_csv(
        [Sample("en", "a.wav", 1.0, 0, stt_s=1.0, transcript="take me home",
                intent="navigation.start")],
        path,
    )

    row = next(csv.DictReader(path.open()))
    assert row["transcript"] == "take me home"
    assert row["intent"] == "navigation.start"


def test_a_skipped_stage_is_blank_in_the_csv_not_zero(tmp_path):
    """A zero would be indistinguishable from a stage that ran instantly,
    and would drag any average computed from the column."""
    path = tmp_path / "bench.csv"
    write_csv([Sample("en", "a.wav", 1.0, 0, stt_s=1.0, nlu_s=None)], path)

    row = next(csv.DictReader(path.open()))
    assert row["nlu_s"] == ""
    assert row["stt_s"] == "1.0000"


def test_the_csv_directory_is_created(tmp_path):
    """`data/performance/` does not exist on a fresh checkout, and the run
    that finally produces evaluation data must not fail on that."""
    path = tmp_path / "nested" / "deeper" / "bench.csv"

    write_csv([Sample("en", "a.wav", 1.0, 0, stt_s=1.0)], path)

    assert path.exists()
