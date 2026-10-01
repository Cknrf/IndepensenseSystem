"""Unit tests for the mmcli SMS driver's parsing and command building.

`MMCLISMSSender.__init__` requires the real `mmcli` binary, so the parsing
and escaping tests exercise protocol knowledge without constructing the
driver. The re-binding tests below do construct it, against a scriptable
fake `mmcli` — no modem, no ModemManager, no subprocess. The end-to-end
send is verified by `tests/manual/send_sms_test.py` on the Pi.
"""
import subprocess

import pytest

from indepensense.messaging import mmcli_sms
from indepensense.messaging.mmcli_sms import (
    _SMS_PATH_RE,
    MMCLISMSSender,
    _is_stale_modem,
)


# --- parsing mmcli output ----------------------------------------------------

def test_extracts_sms_index_from_create_output():
    """`--sms N --send` needs the trailing index from the D-Bus path that
    `--messaging-create-sms` prints."""
    output = (
        "Successfully created new SMS: "
        "/org/freedesktop/ModemManager1/SMS/7\n"
    )
    match = _SMS_PATH_RE.search(output)
    assert match is not None
    assert match.group(1) == "7"


def test_extracts_multi_digit_index():
    """The index keeps climbing across a session; it is not single-digit."""
    output = "Successfully created new SMS: /org/freedesktop/ModemManager1/SMS/142"
    assert _SMS_PATH_RE.search(output).group(1) == "142"


def test_no_index_in_unexpected_output():
    """Garbage must not parse into a plausible-looking index — sending to
    the wrong stored message is worse than reporting failure."""
    assert _SMS_PATH_RE.search("error: could not create SMS") is None


# --- text escaping -----------------------------------------------------------

def test_apostrophe_is_neutralised():
    """mmcli takes the body inside single quotes, so an apostrophe in a
    place name would close the quoting and mangle the command."""
    escaped = MMCLISMSSender._escape("Near St. Luke's Medical Center")
    assert "'" not in escaped
    assert "Luke" in escaped


def test_escaping_leaves_ordinary_text_alone():
    text = "IndepenSense Fall Detection: https://maps.google.com/?q=14.5,120.9"
    assert MMCLISMSSender._escape(text) == text


# --- re-binding to a moved modem ---------------------------------------------
#
# ModemManager hands out a new index every time it enumerates a modem, so a
# wearable that has been up for hours can hold a stale one and fail every
# emergency SMS for the rest of the session — with the backend alert still
# succeeding, so nothing else looks wrong.

def _completed(returncode, stdout="", stderr=""):
    return subprocess.CompletedProcess(
        args=[], returncode=returncode, stdout=stdout, stderr=stderr,
    )


class _FakeMmcli:
    """Scriptable stand-in for the mmcli binary.

    `live_index` is where the modem actually is right now; None means it
    is gone entirely. Any call against a different index answers the way
    real mmcli does — exit 1 with "couldn't find modem".
    """

    def __init__(self, live_index):
        self.live_index = live_index
        self.calls: list[list[str]] = []

    @property
    def list_calls(self) -> int:
        return sum(1 for c in self.calls if c[:2] == ["mmcli", "-L"])

    def __call__(self, command, **_kwargs):
        self.calls.append(list(command))

        if command[:2] == ["mmcli", "-L"]:
            if self.live_index is None:
                return _completed(0, stdout="No modems were found\n")
            return _completed(0, stdout=(
                f"    /org/freedesktop/ModemManager1/Modem/{self.live_index} "
                f"[QUALCOMM INCORPORATED] SIMCOM_SIM7600G-H\n"
            ))

        if self.live_index is None or command[2] != str(self.live_index):
            return _completed(1, stderr="error: couldn't find modem\n")

        argument = command[3]
        if argument.startswith("--messaging-create-sms"):
            return _completed(0, stdout=(
                "Successfully created new SMS: "
                "/org/freedesktop/ModemManager1/SMS/5\n"
            ))
        return _completed(0, stdout="")


@pytest.fixture
def fake_mmcli(monkeypatch):
    """Install a fake mmcli and hand back a factory bound to it."""
    monkeypatch.setattr(mmcli_sms.shutil, "which", lambda _name: "/usr/bin/mmcli")

    def _install(live_index):
        fake = _FakeMmcli(live_index)
        monkeypatch.setattr(mmcli_sms.subprocess, "run", fake)
        return fake

    return _install


def test_stale_modem_error_is_recognised():
    assert _is_stale_modem("error: couldn't find modem")


def test_an_ordinary_send_failure_is_not_a_stale_modem():
    """A plan rejection or an unregistered modem is not an index problem.
    Re-binding on those would turn one honest failure into two."""
    assert not _is_stale_modem("error: couldn't send the SMS: 'Operation not allowed'")
    assert not _is_stale_modem("timed out after 30.0s")


def test_a_moved_modem_is_rediscovered_and_the_send_succeeds(fake_mmcli):
    """The whole point: the modem moved from 0 to 3 while we were running,
    and the message still goes out."""
    fake = fake_mmcli(live_index=0)
    sender = MMCLISMSSender()
    assert sender._modem_index == 0

    fake.live_index = 3                     # a USB glitch re-enumerated it
    result = sender.send("+639171234567", "test")

    assert result.sent is True
    assert sender._modem_index == 3


def test_rediscovery_is_not_attempted_when_nothing_is_stale(fake_mmcli):
    """A healthy send must cost exactly the three mmcli calls it always
    did — no speculative `mmcli -L` on the emergency path."""
    fake = fake_mmcli(live_index=0)
    sender = MMCLISMSSender()
    before = fake.list_calls

    assert sender.send("+639171234567", "test").sent is True
    assert fake.list_calls == before


def test_a_missing_modem_gives_up_instead_of_looping(fake_mmcli):
    """The unplugged case. One extra `mmcli -L`, then a failed result —
    not a retry storm on a device whose battery has to last a day."""
    fake = fake_mmcli(live_index=0)
    sender = MMCLISMSSender()

    fake.live_index = None                  # dongle pulled out
    before = fake.list_calls
    result = sender.send("+639171234567", "test")

    assert result.sent is False
    assert fake.list_calls - before == 1


def test_send_never_raises_when_the_modem_vanishes(fake_mmcli):
    """`SMSSender.send` promises a result, not an exception — it runs on
    the fan-out thread behind an emergency alert."""
    fake = fake_mmcli(live_index=0)
    sender = MMCLISMSSender()

    fake.live_index = None
    result = sender.send("+639171234567", "test")
    assert result.number == "+639171234567"
    assert result.sent is False


def test_an_explicit_modem_index_is_still_rebound(fake_mmcli):
    """`config.SMS_MODEM_INDEX` pins the index for a multi-modem setup. It
    picks the modem; it does not promise that index survives a reset."""
    fake = fake_mmcli(live_index=1)
    sender = MMCLISMSSender(modem_index=1)

    fake.live_index = 4
    assert sender.send("+639171234567", "test").sent is True
    assert sender._modem_index == 4
