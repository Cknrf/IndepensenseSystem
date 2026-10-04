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

    # round two: is it LOUD enough? (F-J, with the waiting blip as a
    # second reference, since these move pitch)
    python -m indepensense.voice.tests.manual.busy_cue_audition --loudness

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

# (letter, description, steps, gap_s, amplitude or None for the default)
#
# Amplitude is left at the default for all of these so the comparison is
# about shape. Loudness is a separate decision and a louder cue is not a
# more distinct one — see LOUDNESS_CANDIDATES below, which is that
# decision, run after C won here and turned out to be too quiet in use.
CANDIDATES = [
    ("A", "two flat low beeps (CURRENT — the one being replaced)",
     [(350.0, 0.06), (350.0, 0.06)], 0.03, None),

    ("B", "three quick low beeps — counts differently from the stop cue",
     [(300.0, 0.07), (300.0, 0.07), (300.0, 0.07)], 0.05, None),

    ("C", "one long low buzz — the only single-tone cue in the set",
     [(200.0, 0.28)], 0.03, None),

    ("D", "slow low double, telephone-busy tempo",
     [(400.0, 0.18), (400.0, 0.18)], 0.12, None),

    ("E", "rising pair — opposite contour to the falling stop cue",
     [(330.0, 0.09), (494.0, 0.09)], 0.03, None),
]

# Round two: C won on distinctness and was then reported as too quiet to
# hear on the headset.
#
# The cause is where it sits, not how loud it is asked to be. 200 Hz is
# the worst band available for this: the ear needs roughly 10-15 dB more
# level there than at 1 kHz to perceive the same loudness, and a small
# earbud driver is rolling off underneath that. The cue is fighting both
# at once.
#
# The obvious fix — nudge it up to 300-400 Hz — is not available. The
# waiting blip is a single tone at 520 Hz, and `test_audio_playback`
# requires a full octave between the only two single-tone cues, so the
# busy cue must be **at or below 260 Hz, or at or above 1040 Hz**. There
# is no middle. That is what makes this a real choice rather than a knob:
#
#   F, G  stay low and buy level with amplitude alone
#   H     goes as high as the octave rule permits and adds amplitude
#   I     jumps the blip entirely — loud and unmistakable, but a high
#         refusal contradicts the convention that low means "no"
#   J     keeps the pitch and leans on duration instead
#
# Judge F-J on *audibility*, having already decided shape. The question
# is "could I miss this in a noisy street", not "is it pleasant".
LOUDNESS_CANDIDATES = [
    ("F", "CURRENT — 200 Hz at the default level",
     [(200.0, 0.28)], 0.03, 0.30),

    ("G", "same pitch, half again as loud",
     [(200.0, 0.28)], 0.03, 0.45),

    ("H", "250 Hz — the ceiling the octave rule allows — and louder",
     [(250.0, 0.30)], 0.03, 0.55),

    ("I", "1100 Hz, above the blip: the most audible option by far",
     [(1100.0, 0.26)], 0.03, 0.32),

    ("J", "200 Hz held longer, loud — length instead of pitch",
     [(200.0, 0.45)], 0.03, 0.55),
]

# What the candidate has to be distinguished FROM.
STOP_STEPS = [(660.0, 0.07), (440.0, 0.10)]
STOP_GAP = 0.03

# The other single-tone cue, and the one the octave rule is protecting.
# Played as a reference in the loudness round because that round moves
# pitch, which is most of what keeps these two apart.
WAITING_STEPS = [(520.0, 0.12)]
WAITING_AMPLITUDE = 0.26

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

LOUDNESS_NOTES = """\
Notes worth having before you choose:

  * A laptop is the wrong judge of F, G and J. Built-in speakers roll off
    below ~300 Hz, so all three will sound thinner here than on the
    headset. What the Mac CAN answer is the comparison this round exists
    for: whether any low option gets close to I, and whether H still
    reads as a different sound from the 520 Hz blip. Confirm the winner
    on the Pi.
  * I is the one that will win on a laptop and may still be right — but
    it inverts the convention that a low sound means "no", and it sits
    nearer the rising chime's territory. If you pick it, pick it knowing
    that.
  * H is the compromise, and 250 Hz is not an arbitrary number: it is the
    highest pitch the octave rule allows against the 520 Hz blip, with a
    little margin. Anything between 260 and 1040 Hz fails the unit test
    rather than merely sounding worse.
  * J buys loudness with duration instead of level. The ear integrates
    over about 200 ms, so a 450 ms tone is no louder than a 280 ms one —
    it is only more *likely to be noticed*, which for a refusal that must
    not be missed may be the same thing in practice.

Whichever wins, it goes into `_BUSY_CUE` in voice/audio.py, and any
amplitude other than the 0.3 default needs `play_busy_cue` to pass it —
`play_waiting_tick` already does exactly that for the blip."""


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
             solo: bool, with_blip: bool = False) -> None:
    print(f"  {label}")
    print(f"     {describe(steps, gap_s)} at amplitude {amplitude:.2f}",
          flush=True)

    if solo:
        play_cue(steps, gap_s=gap_s, amplitude=amplitude)
        time.sleep(1.2)
        return

    # The loudness round moves pitch, and pitch is most of what keeps the
    # busy cue apart from the waiting blip — so that one is played as a
    # reference too, or a candidate could win on volume and collide.
    if with_blip:
        print("     waiting blip (the other single-tone cue)", flush=True)
        play_cue(WAITING_STEPS, amplitude=WAITING_AMPLITUDE)
        time.sleep(0.9)

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
    parser.add_argument("--amp", type=float, default=None,
                        help="override every candidate's amplitude, 0-1 "
                             "(default: the candidate's own, or 0.3)")
    parser.add_argument("--solo", action="store_true",
                        help="play the candidate alone, without the stop cue")
    parser.add_argument("--loudness", action="store_true",
                        help="audition the loudness candidates (F-J) instead "
                             "of the shape ones (A-E), with the waiting blip "
                             "played as a reference")
    parser.add_argument("--repeat", type=int, default=1, metavar="N",
                        help="play the whole run N times (default 1)")
    args = parser.parse_args(argv)

    if args.cue:
        try:
            steps = parse_cue(args.cue)
        except ValueError as exc:
            print(f"bad --cue: {exc}", file=sys.stderr)
            return 2
        chosen = [("custom", args.cue, steps,
                   args.gap if args.gap else 0.03, args.amp)]
    else:
        pool = LOUDNESS_CANDIDATES if args.loudness else CANDIDATES
        wanted = {letter.upper() for letter in args.letters}
        chosen = [c for c in pool if not wanted or c[0] in wanted]
        if not chosen:
            print(f"no such candidate: {', '.join(sorted(wanted))}. "
                  f"Known: {', '.join(c[0] for c in pool)}",
                  file=sys.stderr)
            return 2
        if args.gap is not None:
            chosen = [(a, b, steps, args.gap, amp)
                      for a, b, steps, _, amp in chosen]

    print(__doc__.split("Runs on the Mac")[0].rstrip())
    print("=" * 68)
    if not args.solo:
        print("\nEach candidate plays as:  STOP cue ... then the candidate.")
        print("Listen for whether the second is obviously a different sound.\n")
    else:
        print("\nCandidate only, no reference.\n")

    for _ in range(max(1, args.repeat)):
        for letter, description, steps, gap_s, amplitude in chosen:
            # A candidate's own amplitude wins unless --amp was typed:
            # in the loudness round the level IS the candidate, so a
            # shared default would compare every entry at the same volume
            # and answer nothing.
            level = args.amp if args.amp is not None else (amplitude or 0.3)
            audition(f"{letter}. {description}", steps, gap_s, level,
                     args.solo, with_blip=args.loudness)

    if not args.cue:
        print(LOUDNESS_NOTES if args.loudness else NOTES)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
