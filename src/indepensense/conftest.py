"""Shared test fixtures for the whole package.

Kept out of production modules on purpose: `credential.py` ships to the
device and should not carry test scaffolding.
"""
import pytest

from indepensense.credential import DeviceCredential

# A syntactically valid credential — `credential.load_device_credential`
# validates the UUID shape and a minimum secret length, so tests that need
# a credential need one that would actually parse.
FAKE_DEVICE_ID = "08b7e9b6-d601-446a-b708-7dafc65e4cc2"
FAKE_SECRET = "wpBVy5n_tMgSiW_WQ0yZTl1DAgCOvl-sQjRo8AYx5Qo"

# https, because `net.require_https` refuses to send a bearer token over
# plaintext to anything but localhost — including in tests.
TEST_BACKEND_URL = "https://backend.test"


def make_credential(
    device_id: str = FAKE_DEVICE_ID,
    secret: str = FAKE_SECRET,
) -> DeviceCredential:
    """Build a credential without touching the filesystem."""
    return DeviceCredential(device_id=device_id, token=f"{device_id}.{secret}")


@pytest.fixture
def credential() -> DeviceCredential:
    return make_credential()
