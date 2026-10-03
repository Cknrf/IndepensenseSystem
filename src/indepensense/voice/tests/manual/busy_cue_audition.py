"""Manual test: choose a busy cue that cannot be mistaken for the stop cue.

The two were reported as sounding alike on the headset, and the reason is
not pitch. The stop cue falls (660 → 440 Hz) and the busy cue is flat at
350 Hz, which looks like a clear difference written down — but both are
two short beeps 30 ms apart, and at 60 ms a tone barely has a pitch to
hear. Rhythm and count are what the ear actually uses at this duration,
and on those two dimensions the cues were identical.

So every candidate below changes the *rhythm*, not just the frequency.
Each is played immediately after the stop cue, because that pairing is
the real failure case: a press that interrupts speech and a press that is
refused can happen seconds apart in one exchange, and the wearer has no
screen to check which they got.

Judge by one question only: **could I tell these apart without being told
which was which?** A cue that is merely pleasant is no use.

Runs on the Mac
---------------

Unlike most tests in this directory this one needs no hardware — it
synthesises everything through `sounddevice`, which is installed on the
dev machine. Iterate here; it costs a command rather than a commit.

Two things a laptop will lie to you about, so confirm the winner on the
Pi through the real headset before it ships:

  * **Bass.** Laptop speakers roll off hard below ~300 Hz. The 200 Hz
    buzz (C) may sound thin or absent here and perfectly solid on the
    headset — judging it on a MacBook would reject it for the wrong
    reason.
  * **Level.** These are meant to be heard outdoors over traffic, next to
    a head, not across a desk.

Usage
-----

    # every candidate, each played against the stop cue
    python -m indepensense.voice.tests.manual.busy_cue_audition

    # just the ones you are still deciding between
    python -m indepensense.voice.tests.manual.busy_cue_audition B C

    # anything at all: freq:seconds, comma separated
    python -m indepensense.voice.tests.manual.busy_cue_audition \\
        --cue 300:0.07,300:0.07,300:0.07 --gap 0.05

    # hear it on its own, without the stop cue in front
    python -m indepensense.voice.tests.manual.busy_cue_audition C --solo

Nothing here changes the running system — `audio._BUSY_CUE` is what the
wearable uses, and it is only edited once a candidate has won by ear.

Why generated tones rather than downloaded sounds: every sample library
worth using is CC-BY or similar, which means attribution obligations in
the thesis, WAV files to ship, and a licence to audit. Tones cost none of
that and can be retuned in a line — including from this command line.
"""
import argparse
import sys
import time

from indepensense.voice.audio import play_cue

# (letter, description, steps, gap_s)
#
# Amplitude is left at the default for all of them so the comparison is
# about shape. Loudness is a separate decision and a louder cue is not a
# more distinct one.
CANDIDATES = [
    ("A", "two flat low beeps (CURRENT — the one being replaced)",
     [(350.0, 0.06), (350.0, 0.06)], 0.03),

    ("B", "three quick low beeps — counts differently from the stop cue",
     [(300.0, 0.07), (300.0, 0.07), (300.0, 0.07)], 0.05),

    ("C", "one long low buzz — the only single-tone cue in the set",
     [(200.0, 0.28)], 0.03),

    ("D", "slow low double, telephone-busy tempo",
     [(400.0, 0.18), (400.0, 0.18)], 0.12),

    ("E", "rising pair — opposite contour to the falling stop cue",
     [(330.0, 0.09), (494.0, 0.09)], 0.03),
]

# What the candidate has to be distinguished FROM.
STOP_STEPS = [(660.0, 0.07), (440.0, 0.10)]
STOP_GAP = 0.03

NOTES = """\
Notes worth having before you choose:

  * E rises, and the rising chime already means 'recording started'.
    Those two are seconds apart in a normal exchange, so a win for E here
    may become a different confusion later.
  * C is the only single-tone cue in the whole set, which makes it the
    hardest to confuse with anything — but it is also the longest, and a
    refusal taking 280 ms to say may feel like the device is doing
    something rather than declining. Judge it on the headset, not here.
  * B and D stay within the existing two-or-three-beep family, so they
    are the least surprising if you already know the current cues.

Say which letter you want and it goes into `_BUSY_CUE`."""


def parse_cue(spec: str) -> list[tuple[float, float]]:
    """`"300:0.07,300:0.07"` → `[(300.0, 0.07), (300.0, 0.07)]`.

    Raises `ValueError` with the offending fragment named, because this is
    typed by hand at a prompt and a silently-dropped tone would be heard
    as the cue simply not working.
    """
    steps = []
    for fragment in spec.split(","):
        fragment = fragment.strip()
        if not fragment:
            continue
        if ":" not in fragment:
            raise ValueError(f"expected freq:seconds, got {fragment!r}")
        frequency, _, duration = fragment.partition(":")
        try:
            steps.append((float(frequency), float(duration)))
        except ValueError:
            raise ValueError(f"not a number in {fragment!r}") from None
    if not steps:
        raise ValueError("no tones in the spec")
    return steps


def describe(steps: list[tuple[float, float]], gap_s: float) -> str:
    total = sum(d for _, d in steps) + gap_s * (len(steps) - 1)
    pitches = " ".join(f"{f:.0f}Hz" for f, _ in steps)
    return f"{len(steps)} tone(s), {total * 1000:.0f} ms total — {pitches}"


def audition(label: str, steps, gap_s: float, amplitude: float,
             solo: bool) -> None:
    print(f"  {label}")
    print(f"     {describe(steps, gap_s)}", flush=True)

    if solo:
        play_cue(steps, gap_s=gap_s, amplitude=amplitude)
        time.sleep(1.2)
        return

    print("     stop cue", flush=True)
    play_cue(STOP_STEPS, gap_s=STOP_GAP)
    time.sleep(0.9)

    print("     candidate", flush=True)
    play_cue(steps, gap_s=gap_s, amplitude=amplitude)
    time.sleep(2.0)

    # Again, closer together — the realistic worst case is two presses a
    # second apart, not two sounds with a pause to think in between.
    print("     both again, back to back", flush=True)
    play_cue(STOP_STEPS, gap_s=STOP_GAP)
    time.sleep(0.35)
    play_cue(steps, gap_s=gap_s, amplitude=amplitude)
    print()
    time.sleep(2.0)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Audition busy-cue candidates against the stop cue.")
    parser.add_argument("letters", nargs="*", metavar="LETTER",
                        help="which candidates to play (default: all)")
    parser.add_argument("--cue", metavar="SPEC",
                        help="a cue of your own: freq:seconds, comma separated")
    parser.add_argument("--gap", type=float, default=None,
                        help="silence between tones in seconds (default 0.03, "
                             "or the candidate's own)")
    parser.add_argument("--amp", type=float, default=0.3,
                        help="amplitude 0-1 (default 0.3, as the other cues)")
    parser.add_argument("--solo", action="store_true",
                        help="play the candidate alone, without the stop cue")
    parser.add_argument("--repeat", type=int, default=1, metavar="N",
                        help="play the whole run N times (default 1)")
    args = parser.parse_args(argv)

    if args.cue:
        try:
            steps = parse_cue(args.cue)
        except ValueError as exc:
            print(f"bad --cue: {exc}", file=sys.stderr)
            return 2
        chosen = [("custom", args.cue, steps, args.gap if args.gap else 0.03)]
    else:
        wanted = {letter.upper() for letter in args.letters}
        chosen = [c for c in CANDIDATES if not wanted or c[0] in wanted]
        if not chosen:
            print(f"no such candidate: {', '.join(sorted(wanted))}. "
                  f"Known: {', '.join(c[0] for c in CANDIDATES)}",
                  file=sys.stderr)
            return 2
        if args.gap is not None:
            chosen = [(a, b, steps, args.gap) for a, b, steps, _ in chosen]

    print(__doc__.split("Runs on the Mac")[0].rstrip())
    print("=" * 68)
    if not args.solo:
        print("\nEach candidate plays as:  STOP cue ... then the candidate.")
        print("Listen for whether the second is obviously a different sound.\n")
    else:
        print("\nCandidate only, no reference.\n")

    for _ in range(max(1, args.repeat)):
        for letter, description, steps, gap_s in chosen:
            audition(f"{letter}. {description}", steps, gap_s, args.amp,
                     args.solo)

    if not args.cue:
        print(NOTES)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
