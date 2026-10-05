"""Fixtures shared by every runtime-wide unit test."""
import pytest

from indepensense import app as app_module


@pytest.fixture(autouse=True)
def _pending_alerts_path(tmp_path, monkeypatch):
    """Give each test its own store of undelivered alerts.

    Any test that runs `start()` builds the real `BufferedTelemetryClient`,
    which reloads and re-sends whatever the store holds. Left pointing at
    `var/`, an alert one test shut down before delivering was replayed
    into the next test's recording client, and that test counted two
    alerts where it fired one.

    Patched on `app` rather than `config`: `app.py` imports the constant by
    value, so only the module attribute matters.
    """
    monkeypatch.setattr(
        app_module, "PENDING_ALERTS_PATH", tmp_path / "pending_alerts.json",
    )
