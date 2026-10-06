"""Shared test fixtures for the whole package.

Kept out of production modules on purpose: `credential.py` ships to the
device and should not carry test scaffolding.
"""
import sys

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


@pytest.fixture(autouse=True)
def _isolate_clip_directories(tmp_path, monkeypatch):
    """Keep rendered speech out of the developer's `data/` directory.

    Anything that builds an `Announcer` or calls `_play_clip` writes a
    WAV, and the paths come from module-level config constants — so a
    test that forgets to redirect them silently deposits mock audio in
    the real clip store. Harmless to the suite, but it then looks like
    real content: `render_messages` reported "4 already present" on a
    machine that had never rendered anything, and those four files would
    have been played by a device that read from this checkout.

    Autouse for the same reason the `requests` stubs are: correctness
    here must not depend on each new test file remembering. Patching
    both the `config` originals and the `app` import of them, since
    `app.py` binds them at import time.
    """
    from indepensense import config
    messages_dir = tmp_path / "clips" / "messages"
    cache_dir = tmp_path / "clips" / "cache"
    monkeypatch.setattr(config, "MESSAGE_AUDIO_DIR", messages_dir, raising=False)
    monkeypatch.setattr(config, "CLIP_CACHE_DIR", cache_dir, raising=False)

    app = sys.modules.get("indepensense.app")
    if app is not None:
        monkeypatch.setattr(app, "MESSAGE_AUDIO_DIR", messages_dir, raising=False)
        monkeypatch.setattr(app, "CLIP_CACHE_DIR", cache_dir, raising=False)
