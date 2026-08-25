"""Unit tests for device credential loading and the HTTPS guard.

Two things are load-bearing here. The credential must never appear in a
log or a repr, because that is how secrets actually leak — not through
someone printing it deliberately. And a malformed file must be rejected
locally rather than becoming a 401, which looks identical to a revoked
device and sends whoever is debugging to the wrong place.
"""
import pytest

from indepensense.conftest import FAKE_DEVICE_ID, FAKE_SECRET, make_credential
from indepensense.credential import DeviceCredential, load_device_credential
from indepensense.net import require_https

VALID_LINE = f"{FAKE_DEVICE_ID}.{FAKE_SECRET}"


def _write(tmp_path, text):
    path = tmp_path / "device.key"
    path.write_text(text)
    return path


# --- loading -----------------------------------------------------------------

def test_a_valid_credential_loads(tmp_path):
    credential = load_device_credential(_write(tmp_path, VALID_LINE))
    assert credential is not None
    assert credential.device_id == FAKE_DEVICE_ID
    assert credential.token == VALID_LINE


def test_a_trailing_newline_is_stripped(tmp_path):
    """A newline inside a bearer token produces a 401 indistinguishable
    from a wrong key — and every text editor adds one."""
    credential = load_device_credential(_write(tmp_path, VALID_LINE + "\n"))
    assert credential.token == VALID_LINE


def test_surrounding_whitespace_is_stripped(tmp_path):
    credential = load_device_credential(_write(tmp_path, f"  {VALID_LINE}  \n\n"))
    assert credential.token == VALID_LINE


# --- the secret must not leak -------------------------------------------------

def test_repr_redacts_the_token():
    """The object may end up in a log line, an f-string or a traceback.
    None of those should print the device's password."""
    credential = make_credential()
    rendered = repr(credential)

    assert FAKE_SECRET not in rendered
    assert "redacted" in rendered
    # The UUID is not secret and is what a human quotes when asking for a
    # unit to be re-provisioned, so it stays visible.
    assert FAKE_DEVICE_ID in rendered


def test_str_also_redacts():
    """`str()` falls back to `__repr__` for dataclasses, but assert it —
    f-strings use `str`, and that is the likeliest leak path."""
    assert FAKE_SECRET not in f"{make_credential()}"


def test_the_token_is_still_available_for_the_header():
    credential = make_credential()
    assert credential.authorization_header() == f"Bearer {credential.token}"


# --- rejection ---------------------------------------------------------------

def test_a_missing_file_returns_none(tmp_path):
    """A dev machine, or a unit not yet provisioned. Not fatal — the
    wearable still does fall detection, obstacles, navigation and SMS."""
    assert load_device_credential(tmp_path / "absent") is None


def test_an_empty_file_returns_none(tmp_path):
    assert load_device_credential(_write(tmp_path, "\n")) is None


def test_an_unreadable_path_returns_none(tmp_path):
    """A directory where the file should be. Also the shape of the common
    real failure: root-owned mode 0600, unreadable by the service user."""
    path = tmp_path / "device.key"
    path.mkdir()
    assert load_device_credential(path) is None


@pytest.mark.parametrize("content,why", [
    ("not-a-credential", "no separator"),
    (f"{FAKE_DEVICE_ID}", "uuid only, no secret"),
    (f".{FAKE_SECRET}", "secret only, no uuid"),
    (f"not-a-uuid.{FAKE_SECRET}", "uuid is not a uuid"),
    (f"{FAKE_DEVICE_ID[:-4]}.{FAKE_SECRET}", "truncated uuid"),
    (f"{FAKE_DEVICE_ID}.short", "secret too short to be real"),
    (f"{FAKE_SECRET}.{FAKE_DEVICE_ID}", "halves swapped"),
])
def test_malformed_content_is_rejected(tmp_path, content, why):
    """Rejected here rather than sent and 401'd. A 401 looks exactly like
    a revoked device, which sends the next person debugging the wrong
    way entirely."""
    assert load_device_credential(_write(tmp_path, content)) is None, why


def test_a_rejection_does_not_echo_the_content(tmp_path, capsys):
    """A malformed credential is still a secret — possibly a nearly
    correct one."""
    secretish = f"{FAKE_DEVICE_ID}.{FAKE_SECRET}trailing-garbage!!!"
    load_device_credential(_write(tmp_path, secretish))
    captured = capsys.readouterr()
    assert FAKE_SECRET not in captured.out + captured.err


# --- the HTTPS guard ---------------------------------------------------------

def test_https_is_accepted():
    require_https("https://backend.example.com", "BACKEND_URL")


@pytest.mark.parametrize("url", [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
])
def test_plaintext_loopback_is_accepted(url):
    """Loopback traffic never reaches a network, so there is no hop that
    could read the token. Same carve-out browsers make."""
    require_https(url, "BACKEND_URL")


@pytest.mark.parametrize("url", [
    "http://backend.example.com",
    "http://192.168.1.50:3000",
    "http://100.104.82.110:3000",     # a Tailscale address
    "http://10.0.0.5:3000",
])
def test_plaintext_elsewhere_is_refused(url):
    """Including private and VPN ranges. "It's on our internal network" is
    how plaintext credentials usually get justified, and this code cannot
    verify the hops in between."""
    with pytest.raises(ValueError, match="https"):
        require_https(url, "BACKEND_URL")


def test_the_refusal_names_the_setting():
    """So the error says which config value to change, not just that
    something is wrong."""
    with pytest.raises(ValueError, match="BACKEND_URL"):
        require_https("http://backend.example.com", "BACKEND_URL")
