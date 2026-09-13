"""Places the user has named and saved, resolved without a geocoder.

The destinations a person actually walks to most — home, work, a
relative's house — are frequently not in OpenStreetMap at all, so no
amount of geocoder tuning reaches them. And the moment someone most needs
"take me home" is a moment they may well have no data connection. Both
problems have the same answer: let the user name the place while standing
in it, store the coordinate, and look it up locally.

That makes a saved place the *fastest* destination the wearable has. It
skips Photon entirely, so it resolves with no network, no round trip, and
nothing to rank.

The label is the user's own word
--------------------------------

Nothing here decides what a place is or what to call it. The NLU extracts
the label from what the user said — "save this as home" gives `home`,
"save this as my sister's house" gives `my sister's house` — exactly as it
already extracts `location` for `navigation.start`. Storage keys off a
normalised form (via `routing.ranking.normalise_name`, the same folding
used to match geocoder candidates) so "Mom's House" and "moms house"
resolve to the same entry, while the original spelling is kept for
speaking back.

Durability
----------

Writes go to a temporary file and are renamed over the target, because
this is a battery-powered device that can lose power mid-write and a
half-written JSON file would take every saved place with it. `os.replace`
is atomic within a filesystem, so a reader sees either the old file or the
new one.
"""
import json
import os
import sys
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from indepensense.routing.base import Coordinate
from indepensense.routing.ranking import normalise_name


@dataclass(frozen=True)
class SavedPlace:
    """One place the user named, with the words they used to name it."""
    label: str              # as spoken, for saying back
    coordinate: Coordinate
    saved_at: str           # ISO 8601 UTC


class SavedPlaces:
    """A label-to-coordinate store backed by one JSON file.

    Loaded once at construction and held in memory — the file is a handful
    of entries and every lookup sits on the voice thread's critical path,
    where a disk read per navigation command would be wasted latency.

    A lock guards the map because saving and resolving can both arrive off
    the voice thread while a button handler is running.
    """

    def __init__(self, path: Path):
        self._path = path
        self._lock = threading.Lock()
        self._places: dict[str, SavedPlace] = self._load()

    # ------------------------------------------------------------------ API

    def find(self, label: str) -> SavedPlace | None:
        """Resolve a spoken label, or None if nothing matches."""
        key = normalise_name(label)
        if not key:
            return None
        with self._lock:
            return self._places.get(key)

    def save(self, label: str, coordinate: Coordinate) -> bool:
        """Store `coordinate` under `label`. True if it replaced an entry.

        Replacing is silent and deliberate — people move house, and the
        alternative would be a user unable to correct a place they saved
        while standing in the wrong spot. The return value lets the caller
        say "updated" rather than "saved", which is the only signal they
        get that something was overwritten.
        """
        key = normalise_name(label)
        if not key:
            return False
        entry = SavedPlace(
            label=label.strip(),
            coordinate=coordinate,
            saved_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
        with self._lock:
            replaced = key in self._places
            self._places[key] = entry
            self._write_locked()
        return replaced

    def delete(self, label: str) -> bool:
        """Forget a place. True if there was one to forget.

        Exists because a blind user who saved "home" at the wrong corner
        has no other way to correct it — no file to edit, no screen to
        tap. Without this a mistake is permanent.
        """
        key = normalise_name(label)
        with self._lock:
            if key not in self._places:
                return False
            del self._places[key]
            self._write_locked()
        return True

    def labels(self) -> list[str]:
        """Every saved label as spoken, alphabetical."""
        with self._lock:
            return sorted(place.label for place in self._places.values())

    def __len__(self) -> int:
        with self._lock:
            return len(self._places)

    # ------------------------------------------------------------ internals

    def _load(self) -> dict[str, SavedPlace]:
        """Read the file, or start empty.

        A missing file is the normal first-boot case. A corrupt or
        unreadable one is logged loudly and treated as empty: refusing to
        start would take down navigation, fall detection and everything
        else over a list of shortcuts.
        """
        try:
            raw = json.loads(self._path.read_text())
        except FileNotFoundError:
            return {}
        except (OSError, json.JSONDecodeError) as exc:
            print(
                f"[places] could not read {self._path}: {exc}. "
                f"Starting with no saved places.",
                file=sys.stderr, flush=True,
            )
            return {}

        if not isinstance(raw, dict):
            print(f"[places] {self._path} is not an object — ignoring.",
                  file=sys.stderr, flush=True)
            return {}

        places: dict[str, SavedPlace] = {}
        for key, value in raw.items():
            try:
                places[key] = SavedPlace(
                    label=value["label"],
                    coordinate=Coordinate(lat=value["lat"], lon=value["lon"]),
                    saved_at=value.get("saved_at", ""),
                )
            except (TypeError, KeyError) as exc:
                # One malformed entry must not discard the rest — the
                # others are still somewhere the user needs to get to.
                print(f"[places] skipping malformed entry {key!r}: {exc}",
                      file=sys.stderr, flush=True)
        return places

    def _write_locked(self) -> None:
        """Persist the map. Caller holds `_lock`.

        Temp file plus `os.replace` so a power cut cannot leave a
        half-written file behind. Failure is logged, not raised: the save
        still holds for this session, and the user has already been told
        it worked — telling them otherwise mid-sentence helps nobody.
        """
        payload = {
            key: {
                "label": place.label,
                "lat": place.coordinate.lat,
                "lon": place.coordinate.lon,
                "saved_at": place.saved_at,
            }
            for key, place in self._places.items()
        }
        temp = self._path.with_suffix(self._path.suffix + ".tmp")
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            temp.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
            os.replace(temp, self._path)
        except OSError as exc:
            print(f"[places] could not persist to {self._path}: {exc}",
                  file=sys.stderr, flush=True)
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass
