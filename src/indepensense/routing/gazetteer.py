"""Correct a misheard destination to the nearest real place name.

Whisper can only write words it has learned. A barangay, a town or a
local landmark it has never seen comes back spelled by sound — "Sambaht"
for Sambat, "Bauwan" for Bauan — and Photon, matching text, either finds
nothing or finds something else. The user said the name correctly; the
transcript is what is wrong.

So the wearable keeps a list of the names that actually exist in its
deployment area (`tools/build_gazetteer.py` builds it from the same dump
the Photon index comes from) and, when a destination misses, asks which
real name the transcript is closest to. That turns "what did they say?",
which has no fixed answer, into "which of these ~16,000 names is it?",
which does.

Spelling similarity, not meaning
--------------------------------

The comparison is RapidFuzz's `fuzz.ratio` — normalised edit distance
over the whole string — on names folded by `ranking.normalise_name`.
`WRatio` was tried first, being RapidFuzz's general-purpose default, and
rejected: it scores partial matches, so on this list "sambaht" tied with
a place named "s" at 90 and "school" matched any school at all. A
correction has to account for everything the user said, not a fragment
of it.

No AI model is involved, which is the point: an LLM asked for "the right
name" of a place it has never heard of invents a plausible one, and a
blind user cannot see that it did. This can only ever answer with a name
that is on the list.

A correction is a guess, so it is gated twice
---------------------------------------------

Below `min_score` there is no correction: the transcript was not close
to anything, and the nearest name is merely the least bad. And when the
two best *different* names tie — "tanawan" is equally far from Tanauan
and Tanagan — there is no correction either, because choosing between
them would be a coin toss presented as an answer.

What passes is still only a candidate. The executor geocodes it and then
reads the result back for confirmation, so a wrong correction costs the
user one "no", never a walk.
"""
from dataclasses import dataclass
from pathlib import Path

from rapidfuzz import fuzz, process

from indepensense.routing.ranking import normalise_name

# Lines the build tool writes for provenance. A space after the hash, so
# a real place named "#42" is still a name.
_COMMENT_PREFIX = "# "


@dataclass(frozen=True)
class Correction:
    name: str     # as spelled in the list, which is how Photon indexes it
    score: float  # 0-100, `fuzz.ratio` against the normalised transcript


class Gazetteer:
    def __init__(self, names: list[str], min_score: float):
        # One entry per normalised form. Sorted input makes the kept
        # spelling deterministic when two differ only in case or
        # punctuation ("JOLLIBEE", "Jollibee") — and Photon matches
        # either, so which survives does not change the answer.
        self._names: dict[str, str] = {}
        for name in names:
            key = normalise_name(name)
            if key:
                self._names.setdefault(key, name)
        self._keys = list(self._names)
        self._min_score = min_score

    @classmethod
    def load(cls, path: Path, min_score: float) -> "Gazetteer":
        """Read the list written by `tools/build_gazetteer.py`.

        Raises `FileNotFoundError` when it has not been built; the caller
        decides whether that is fatal.
        """
        lines = path.read_text(encoding="utf-8").splitlines()
        return cls(
            sorted(line for line in lines if line and not line.startswith(_COMMENT_PREFIX)),
            min_score,
        )

    def __len__(self) -> int:
        return len(self._keys)

    def correct(self, text: str) -> Correction | None:
        """The real name `text` most plausibly is, or None if none is close.

        Returns the name even when it equals `text` — the caller compares,
        because "already correct" and "corrected" are different outcomes
        only to it.
        """
        query = normalise_name(text)
        if not query:
            return None
        best_two = process.extract(
            query, self._keys, scorer=fuzz.ratio,
            score_cutoff=self._min_score, limit=2,
        )
        if not best_two:
            return None
        (key, score, _), *rest = best_two
        if rest and rest[0][1] == score:
            return None
        return Correction(name=self._names[key], score=score)
