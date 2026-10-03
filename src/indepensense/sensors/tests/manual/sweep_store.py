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
  * each face reports its own mean field strength. The ambient field does
    not change between faces, so one face reading far from the others is
    either interference or a changed setup. `odd_faces` finds them.

A sweep is read back as one flat list of samples, exactly as the
all-in-one run produces, so the calibration maths does not know or care
which mode was used.
"""
import json
import statistics
import time
from pathlib import Path

FACES = ("front", "back", "left", "right", "top", "bottom")

# How far a face's mean field may sit from the median of the other faces
# before it is called out. The ambient field is the same for all six, so
# a deviation this large is something riding on the vest for that face
# alone — or a setup that changed between runs.
_ODD_FACE_TOLERANCE = 0.15

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

    def face_means(self) -> dict[str, float]:
        """Mean field strength per recorded face, in μT."""
        means = {}
        for face in self.recorded():
            samples = self.data["faces"][face]["samples"]
            if samples:
                means[face] = statistics.fmean(_magnitude(s) for s in samples)
        return means

    def odd_faces(self, tolerance: float = _ODD_FACE_TOLERANCE) -> list[tuple[str, float, float]]:
        """Faces whose mean field is out of line with the rest.

        Returns `(face, its mean, the median)` for each. The ambient field
        is the same whichever way the vest points, so a face that reads
        far from the others saw something the others did not — which is
        the one failure this split mode makes easier to cause and harder
        to notice.

        Needs at least three faces to have a median worth comparing to.
        """
        means = self.face_means()
        if len(means) < 3:
            return []
        median = statistics.median(means.values())
        if median <= 0:
            return []
        return [
            (face, mean, median)
            for face, mean in means.items()
            if abs(mean - median) / median > tolerance
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
