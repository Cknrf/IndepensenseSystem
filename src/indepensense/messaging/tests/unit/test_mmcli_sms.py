"""Unit tests for the mmcli SMS driver's parsing and command building.

`MMCLISMSSender.__init__` requires the real `mmcli` binary, so these tests
exercise the parts that own protocol knowledge — output parsing and text
escaping — without constructing the driver. The end-to-end send is
verified by `tests/manual/send_sms_test.py` on the Pi.
"""
from indepensense.messaging.mmcli_sms import _SMS_PATH_RE, MMCLISMSSender


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
