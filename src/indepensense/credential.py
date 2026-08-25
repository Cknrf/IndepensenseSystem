"""The device's credential for authenticating to the backend.

Provisioning writes one line to `config.DEVICE_KEY_PATH`:

    <device-uuid>.<secret>

The whole line is the bearer token. The backend derives which device is
calling from the token alone — no `deviceID` is sent in any request body
or URL any more, because a claimed identifier is a claim anyone can make.

Handling the secret
-------------------

This value is the device's password. Two rules follow, both enforced here
rather than left to callers:

  - **It is never printed.** `DeviceCredential.__repr__` redacts the
    token, so the object is safe inside a log line, an f-string, or a
    traceback — the places a secret actually leaks from, because nobody
    writes `print(credential.token)` on purpose.
  - **It is read once.** `app.py` loads it at startup and holds it in
    memory. Re-reading per request would put a root-owned file in the
    path of every heartbeat.

The UUID half is *not* secret — it identifies the unit in logs and is
what a human quotes when asking for a device to be re-provisioned. It is
exposed as `device_id` for exactly that.

File permissions
----------------

The file must be readable by the user the service runs as
(`User=` in `deploy/systemd/indepensense.service`). Root-owned and mode
0600 makes it readable by root only, which is *not* the service user —
see `deploy/systemd/README.md` for the fix.
"""
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

# `<uuid>.<secret>`. The UUID is matched properly rather than as "anything
# before a dot", so a truncated or reordered file is rejected here instead
# of becoming a 401 that looks like a revoked device.
_CREDENTIAL_RE = re.compile(
    r"^(?P<device_id>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}"
    r"-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})\.(?P<secret>[A-Za-z0-9_\-]{16,})$"
)


@dataclass(frozen=True)
class DeviceCredential:
    """A loaded device credential.

    `token` is the full `<uuid>.<secret>` line, sent verbatim as
    `Authorization: Bearer <token>`. `device_id` is the UUID half, safe to
    log.
    """
    device_id: str
    token: str = field(repr=False)

    def __repr__(self) -> str:
        # Explicit rather than relying on `field(repr=False)` alone, so the
        # redaction is visible to anyone reading a log and obvious to
        # anyone editing this class.
        return f"DeviceCredential(device_id={self.device_id!r}, token=<redacted>)"

    def authorization_header(self) -> str:
        return f"Bearer {self.token}"


def load_device_credential(path: Path) -> DeviceCredential | None:
    """Read and validate the credential file. None if unusable.

    Returns None rather than raising, for every failure mode: absent (a
    development machine, or a unit not yet provisioned), unreadable
    (wrong owner — the common one), or malformed. The caller decides what
    to do about it, which is to run without backend telemetry rather than
    refuse to boot. A wearable that will not start is worse than one that
    cannot reach its guardian dashboard: fall detection, obstacle
    warnings and SMS all still work.

    Error messages deliberately name the likely cause. This fails on a
    freshly provisioned unit far more often than in normal operation, and
    the failure is nearly always file permissions.
    """
    try:
        raw = path.read_text()
    except FileNotFoundError:
        print(
            f"[credential] {path} not found — the backend will reject "
            f"telemetry until this unit is provisioned.",
            file=sys.stderr,
        )
        return None
    except PermissionError:
        print(
            f"[credential] {path} exists but is not readable by this user. "
            f"It must be owned by the account the service runs as — see "
            f"deploy/systemd/README.md.",
            file=sys.stderr,
        )
        return None
    except OSError as exc:
        print(f"[credential] could not read {path}: {exc}", file=sys.stderr)
        return None

    # Strip trailing newline/whitespace, as specified. A trailing newline
    # in a bearer token produces a 401 that looks exactly like a wrong key.
    line = raw.strip()
    if not line:
        print(f"[credential] {path} is empty.", file=sys.stderr)
        return None

    match = _CREDENTIAL_RE.match(line)
    if match is None:
        # Deliberately does not echo the content — it is a secret even
        # when malformed, and a partially-correct one is still worth
        # protecting.
        print(
            f"[credential] {path} is not in the expected "
            f"<device-uuid>.<secret> form. Re-provision this unit.",
            file=sys.stderr,
        )
        return None

    return DeviceCredential(device_id=match.group("device_id"), token=line)
