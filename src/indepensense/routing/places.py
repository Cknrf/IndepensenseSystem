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

Possessives do not count as part of the name
--------------------------------------------

That folding alone was not enough, and the gap was found in the field.
A user said "Save this place as my home", which stored the key `my home`,
then said "Can you help me go home?", which the NLU resolved to `home` —
a different key. The saved place was never consulted. The wearable
geocoded "home", found an unrelated business, asked for confirmation, and
cancelled. Three times in one session.

Nobody thinks of the possessive as part of a place's name: "my home" and
"home" are the same place, as are "bahay ko", "aking bahay" and "bahay".
So `_place_key` drops determiners and possessive particles from both
sides before comparing, in English and Tagalog alike, and what remains is
matched exactly.

**Exactly** — not by word overlap. `ranking.name_match_score` is right
there and scores "house" against "my sister's house" at 1.0, which is the
problem: a user with both "my house" and "my sister's house" saved would
be walked to whichever sorted first, with nothing to tell them it had
guessed. Partial matching is the correct tool for ranking geocoder
candidates, where the alternative is no result at all. Here the
alternative is a clean miss, an honest "I don't have a place saved as
that", and a geocoder lookup — all of which beat walking someone to the
wrong door.

The key is derived on load, not trusted from the file, so a places.json
written before this existed re-keys itself the first time it is read.

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


# Words that carry no part of a place's identity, so "my home", "ang
# bahay ko" and "home"/"bahay" are the same place. English determiners and
# possessives, plus the Tagalog linkers and enclitic pronouns that do the
# same job.
#
# Deliberately short. Every word added here is a word the user can no
# longer use to tell two of their own places apart, so this holds only
# words that cannot distinguish anything: `ko` ("my") is here, `nanay`
# ("mother") is emphatically not.
_FILLER_WORDS = frozenset({
    # English
    "my", "the", "a", "an", "our",
    # Tagalog determiners, linkers and possessive enclitics
    "ang", "ng", "sa", "na", "yung", "iyong", "ko", "akin", "aking",
    "amin", "aming", "natin", "namin",
})


def _place_key(label: str) -> str:
    """Fold a spoken label to the key two phrasings must share.

    Falls back to the plain normalised form when a label is *entirely*
    filler — "my", "ang akin" — because a key of `""` would silently
    collide with every other such label and quietly overwrite them. A
    useless key is still better than a colliding one; `save` rejects an
    empty one separately.
    """
    normalised = normalise_name(label)
    kept = [word for word in normalised.split() if word not in _FILLER_WORDS]
    return " ".join(kept) or normalised


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
        if not normalise_name(label):
            return None
        with self._lock:
            return self._places.get(_place_key(label))

    def save(self, label: str, coordinate: Coordinate) -> bool:
        """Store `coordinate` under `label`. True if it replaced an entry.

        Replacing is silent and deliberate — people move house, and the
        alternative would be a user unable to correct a place they saved
        while standing in the wrong spot. The return value lets the caller
        say "updated" rather than "saved", which is the only signal they
        get that something was overwritten.
        """
        if not normalise_name(label):
            return False
        key = _place_key(label)
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
        key = _place_key(label)
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
        for stored_key, value in raw.items():
            try:
                label = value["label"]
                # Re-derive rather than trusting the file's key. A
                # places.json written before `_place_key` existed holds
                # `my home`, which no lookup would ever produce again —
                # the entry would be unreachable and invisible, which is
                # worse than absent. Deriving on load re-keys it silently
                # and correctly, and the next write persists the new form.
                places[_place_key(label)] = SavedPlace(
                    label=label,
                    coordinate=Coordinate(lat=value["lat"], lon=value["lon"]),
                    saved_at=value.get("saved_at", ""),
                )
            except (TypeError, KeyError) as exc:
                # One malformed entry must not discard the rest — the
                # others are still somewhere the user needs to get to.
                print(f"[places] skipping malformed entry {stored_key!r}: {exc}",
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
