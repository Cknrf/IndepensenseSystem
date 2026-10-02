"""Unit tests for the spoken cellular-signal answer.

This handler shells out to `mmcli -m any -K` and parses key=value lines.
It had no coverage at all, which is how two gaps survived: it never read
the access technology the modem reports, and it treated `registered` and
`connected` as the same thing — so "is there internet right now", a
phrasing in the example bank, could be answered "signal is strong" while
no data bearer existed.

`subprocess` is imported inside the function, so patching the real module
reaches it: the local import resolves to the same module object.
"""
import subprocess

import pytest

from indepensense.intents.base import Intent, IntentResult
from indepensense.intents.executor import IntentExecutor
from indepensense.language import LanguageState
from indepensense.routing.mock import MockGeocoder, MockRouter


def _mmcli_output(state="connected", quality=72, technology="lte"):
    """A realistic `mmcli -m any -K` block, colons padded as mmcli pads them."""
    lines = [
        ("modem.dbus-path", "/org/freedesktop/ModemManager1/Modem/0"),
        ("modem.generic.device-identifier", "abc123"),
        ("modem.generic.state", state),
        ("modem.generic.state-failed-reason", "--"),
        ("modem.generic.signal-quality.value", str(quality)),
        ("modem.generic.signal-quality.recent", "yes"),
    ]
    if technology is not None:
        lines.append(("modem.generic.access-technologies.value[1]", technology))
    return "\n".join(f"{key:<50}: {value}" for key, value in lines) + "\n"


@pytest.fixture
def ask(monkeypatch):
    """Returns a callable that scripts mmcli and asks for signal status."""
    def _ask(stdout="", returncode=0, raises=None, language="en"):
        def _run(command, **_kwargs):
            if raises is not None:
                raise raises
            return subprocess.CompletedProcess(
                args=command, returncode=returncode, stdout=stdout, stderr="",
            )

        monkeypatch.setattr(subprocess, "run", _run)
        executor = IntentExecutor(
            router=MockRouter(),
            geocoder=MockGeocoder(),
            language=LanguageState(language, ("en", "tl")),
        )
        return executor.execute(
            IntentResult(Intent.DEVICE_STATUS, {"status_field": "signal"})
        )

    return _ask


# --- strength ----------------------------------------------------------------

@pytest.mark.parametrize("quality,word", [
    (95, "strong"),
    (60, "strong"),      # the boundary belongs to the better tier
    (59, "medium"),
    (30, "medium"),
    (29, "weak"),
    (3, "weak"),
])
def test_strength_tiers(ask, quality, word):
    assert word in ask(_mmcli_output(quality=quality)).lower()


def test_the_percentage_is_spoken(ask):
    assert "72" in ask(_mmcli_output(quality=72))


# --- network generation ------------------------------------------------------

@pytest.mark.parametrize("technology,generation", [
    ("lte", "4G"),
    ("5gnr", "5G"),
    ("umts", "3G"),
    ("hspa", "3G"),
    ("gsm", "2G"),
    ("edge", "2G"),
])
def test_the_generation_is_named(ask, technology, generation):
    """mmcli reports the radio standard; nobody asks whether they are on
    UMTS."""
    assert generation in ask(_mmcli_output(technology=technology))


def test_an_unknown_radio_standard_is_left_unsaid(ask):
    """A wrong generation is worse than no generation, and new standards
    keep arriving."""
    response = ask(_mmcli_output(technology="6gsomething"))

    assert "strong" in response.lower()
    assert "G," not in response and "on " not in response


def test_a_missing_technology_line_still_answers(ask):
    response = ask(_mmcli_output(technology=None))
    assert "strong" in response.lower()


def test_a_placeholder_technology_is_ignored(ask):
    """mmcli prints `--` for fields it has no value for."""
    response = ask(_mmcli_output(technology="--"))
    assert "strong" in response.lower()


# --- registered is not connected ---------------------------------------------

def test_registered_without_a_bearer_says_there_is_no_data(ask):
    """The gap this closes: a modem on the network with no data session
    used to be reported as "signal is strong"."""
    response = ask(_mmcli_output(state="registered")).lower()

    assert "no data" in response


def test_registered_still_reports_the_strength(ask):
    """It is why the connection may be failing, so it is worth saying —
    it just cannot be the headline."""
    assert "41" in ask(_mmcli_output(state="registered", quality=41))


def test_connected_does_not_claim_there_is_no_data(ask):
    assert "no data" not in ask(_mmcli_output(state="connected")).lower()


# --- failure modes -----------------------------------------------------------

def test_a_failed_modem_points_at_the_sim(ask):
    response = ask(_mmcli_output(state="failed")).lower()
    assert "sim" in response


def test_a_disabled_modem_says_so(ask):
    assert "disabled" in ask(_mmcli_output(state="disabled")).lower()


def test_a_searching_modem_says_it_is_connecting(ask):
    assert "connecting" in ask(_mmcli_output(state="searching")).lower()


def test_no_modem_is_reported_distinctly(ask):
    """`mmcli` exits non-zero when it cannot find one — a different
    problem from a modem that is present and struggling."""
    assert "modem" in ask("", returncode=1).lower()


def test_mmcli_missing_degrades(ask):
    assert ask(raises=FileNotFoundError("mmcli")).strip() != ""


def test_a_hanging_mmcli_degrades(ask):
    """It runs on the voice thread; a modem wedged mid-scan must not hold
    the answer open."""
    assert ask(raises=subprocess.TimeoutExpired("mmcli", 3.0)).strip() != ""


def test_a_quality_line_that_is_not_a_number_degrades(ask):
    broken = _mmcli_output().replace(": 72", ": n/a")
    assert ask(broken).strip() != ""


# --- language ----------------------------------------------------------------

def test_the_answer_follows_the_active_language(ask):
    english = ask(_mmcli_output(), language="en")
    tagalog = ask(_mmcli_output(), language="tl")

    assert english != tagalog
    # Digits are effectively untrained in the MMS Tagalog voice.
    assert not any(c.isdigit() for c in tagalog.replace("4G", "")), tagalog
