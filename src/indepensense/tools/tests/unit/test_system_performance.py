"""Unit tests for the performance monitor's CSV path resolution.

The monitor itself needs `psutil` and `vcgencmd`, so it can only be run on
the Pi. `_resolve_csv_path` is pure, and it is the part that had a real
failure mode: output landing wherever the operator happened to be standing.
"""
from pathlib import Path

from indepensense.config import PERF_LOG_DIR
from indepensense.tools.system_performance import _TIMESTAMPED, _resolve_csv_path


def test_no_csv_flag_means_no_file():
    assert _resolve_csv_path(None) is None


def test_a_bare_flag_gets_a_timestamped_name_in_the_log_dir():
    path = _resolve_csv_path(_TIMESTAMPED)
    assert path.parent == PERF_LOG_DIR
    assert path.name.endswith("_perf.csv")


def test_a_bare_name_lands_in_the_log_dir():
    """The bug this fixes: `--csv wearable_perf.csv` run from inside
    `src/indepensense/` used to write the CSV into the source tree."""
    assert _resolve_csv_path("wearable_perf.csv") == PERF_LOG_DIR / "wearable_perf.csv"


def test_a_relative_path_is_still_anchored_to_the_log_dir():
    """Where you run the tool from must not decide where data lands."""
    assert _resolve_csv_path("run3/sample.csv") == PERF_LOG_DIR / "run3" / "sample.csv"


def test_an_absolute_path_is_honoured_as_given():
    """The escape hatch — writing to a USB stick or outside the repo."""
    assert _resolve_csv_path("/tmp/abs.csv") == Path("/tmp/abs.csv")


def test_the_log_dir_is_under_the_gitignored_data_directory():
    """Profiling output is generated measurement data, not source. Keeping
    it under `data/` means no new `.gitignore` pattern is needed."""
    assert "data" in PERF_LOG_DIR.parts
