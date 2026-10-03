"""Accumulated magnetometer samples, one face at a time.

The calibration sweep asks for six orientations of the vest. Doing all
six in one 90-second run means a single bad face — somebody walked past
with a phone, the vest was tilted wrong — costs the whole sweep, and the
previous attempt came back BAD with no way to redo just the offending
part.

So each face can be recorded on its own and the samples kept here between
runs.

The thing that makes this risky, and what most of this module is for
-------------------------------------------------------------------

**Every face must come from the same physical setup.** The offsets being
computed are the *device's own* magnetic field, so they are only valid
for the arrangement that produced them. Re-seat the battery, mount a
motor differently, or walk to a different spot between faces, and the
samples no longer describe one object — but they will still average into
six numbers that look entirely reasonable.

Nothing can detect a re-seated battery. Two things narrow it:

  * the session is stamped, so a face recorded hours after the others is
    visible rather than silent, and
  * each face reports whether it actually *moved* — a face recorded
    without rotating contributes nothing and is the easy mistake to make
    when the faces are separate commands.

**What this module deliberately does NOT do** is compare faces by their
raw mean field strength. The first version did, on the reasoning that the
ambient field is the same whichever way the vest points. That is true of
the *corrected* field and false of the raw one: a raw reading is Earth's
field plus the hard-iron offset, and the offset is fixed in the sensor's
frame while Earth's field rotates through it. Raw magnitude therefore
swings with orientation by twice the offset — on the first real sweep,
22 to 50 uT — so a face's mean says only how its operator happened to
rotate. It flagged a different innocent face on every run and sent
somebody outside to re-record good data three times.

Comparing faces is still worth doing; it just cannot be done until the
calibration exists. `magnetometer_calibrate.residual_by_face` does it on
*corrected* magnitudes, where constant-in-every-orientation is actually
the property being relied on.

A sweep is read back as one flat list of samples, exactly as the
all-in-one run produces, so the calibration maths does not know or care
which mode was used.
"""
import json
import statistics
import time
from pathlib import Path

FACES = ("front", "back", "left", "right", "top", "bottom")

# Smallest axis swing that counts as "this face was actually rotated".
#
# Rotating through any orientation moves at least one axis across a large
# part of the field; a face held still moves none of them. Well below the
# ~40 uT of a real rotation and well above sensor noise, so it separates
# "barely moved" from "moved a bit less than the others" without
# pretending to judge the latter.
_MIN_FACE_SWING_UT = 12.0

# Beyond this, "the same session" stops being a safe assumption. Not an
# error — a careful operator may take their time — but worth saying.
_STALE_SESSION_S = 2 * 60 * 60


def _magnitude(field) -> float:
    x, y, z = field
    return (x * x + y * y + z * z) ** 0.5


class SweepStore:
    """Per-face samples on disk, with the session bookkeeping around them."""

    def __init__(self, path: Path):
        self.path = path
        self.data = self._load()

    def _load(self) -> dict:
        if not self.path.exists():
            return {"started_at": None, "faces": {}}
        try:
            data = json.loads(self.path.read_text())
        except (OSError, ValueError):
            # A corrupt store must not strand somebody mid-sweep with an
            # exception they have to read the source to understand.
            return {"started_at": None, "faces": {}}
        data.setdefault("started_at", None)
        data.setdefault("faces", {})
        return data

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=1))

    # -- recording ---------------------------------------------------------

    def record(self, face: str, samples, now: float | None = None) -> None:
        """Store `samples` as `face`, replacing anything already there.

        Replacing rather than appending: re-running a face means the
        first attempt was bad, and keeping both would let the bad one go
        on poisoning the result.
        """
        if face not in FACES:
            raise ValueError(f"unknown face {face!r}; expected one of "
                             f"{', '.join(FACES)}")
        stamp = time.time() if now is None else now
        if self.data["started_at"] is None:
            self.data["started_at"] = stamp
        self.data["faces"][face] = {
            "at": stamp,
            "samples": [list(s) for s in samples],
        }

    def reset(self) -> None:
        self.data = {"started_at": None, "faces": {}}

    # -- reading back ------------------------------------------------------

    def recorded(self) -> list[str]:
        """Faces captured so far, in the canonical order."""
        return [face for face in FACES if face in self.data["faces"]]

    def missing(self) -> list[str]:
        return [face for face in FACES if face not in self.data["faces"]]

    def samples(self) -> list[tuple[float, float, float]]:
        """Every face's samples as one flat list, face order."""
        flat = []
        for face in self.recorded():
            flat.extend(tuple(s) for s in self.data["faces"][face]["samples"])
        return flat

    def face_samples(self, face: str) -> list[tuple[float, float, float]]:
        return [tuple(s) for s in self.data["faces"].get(face, {}).get("samples", [])]

    def face_stats(self) -> dict[str, dict]:
        """Per face: how many samples, the raw field range, the axis swing.

        The raw range is shown rather than a mean because a mean invites
        exactly the comparison that turned out to be meaningless — see
        the module docstring. The range at least says honestly that raw
        magnitude varies a lot, which it does and should.
        """
        stats = {}
        for face in self.recorded():
            samples = self.face_samples(face)
            if not samples:
                continue
            magnitudes = [_magnitude(s) for s in samples]
            swing = max(
                max(s[axis] for s in samples) - min(s[axis] for s in samples)
                for axis in (0, 1, 2)
            )
            stats[face] = {
                "count": len(samples),
                "low": min(magnitudes),
                "high": max(magnitudes),
                "swing": swing,
            }
        return stats

    def still_faces(self, minimum: float = _MIN_FACE_SWING_UT) -> list[tuple[str, float]]:
        """Faces that were not actually rotated, with their largest swing.

        The one per-face mistake that can be caught without the
        calibration: a face held still adds samples but no new
        orientations, so it pads the count while contributing nothing to
        the sphere the derivation is looking for.
        """
        return [
            (face, stat["swing"])
            for face, stat in self.face_stats().items()
            if stat["swing"] < minimum
        ]

    def span_seconds(self) -> float:
        """How long the session has been open, in seconds."""
        # `is not None`, not truthiness — a timestamp of 0.0 is falsy and
        # would silently drop that face from the span.
        times = [f["at"] for f in self.data["faces"].values()
                 if f.get("at") is not None]
        if not times:
            return 0.0
        return max(times) - min(times)

    def is_stale(self) -> bool:
        return self.span_seconds() > _STALE_SESSION_S
