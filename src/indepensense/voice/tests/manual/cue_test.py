"""Manual test: play every non-speech cue, in the order a user meets them.

The wearable answers four button presses with a sound rather than a
sentence. Whether those four are *distinguishable* cannot be unit tested —
the assertions can only check that distinct audio was generated, not that
an ear separates them — and getting it wrong is not a crash. It is a user
who cannot tell "I stopped" from "I cannot do that", on a device whose
whole premise is that they are not looking at it.

So this is the test that matters for them, and it is run by listening.

What to check, in this order:

  1. **Rising and falling chime** bracket a recording, seconds apart. They
     should read as a matched pair opening and closing.
  2. **Stop cue** answers a press that interrupted speech. It should sound
     final — something being set down — and must NOT be mistakable for the
     falling chime, which already means "recording ended". The two can
     occur within seconds of each other in one exchange.
  3. **Busy cue** answers a press that was refused — two short buzzes,
     like a phone rejecting a wrong passcode. It must not be mistakable
     for the **stop cue**: both are two pulses, which is the exact
     collision the original busy cue had. Pitch, timbre and a longer gap
     are meant to keep them apart; this is where to check that they do.
     It must also carry over the waiting blip, which it often plays on
     top of.
  4. **Waiting blip** must be *audible but not demanding*. It repeats
     every ~1.2 s while the device thinks, so it should sit under the
     other cues without disappearing. It originally did disappear — 45 ms
     at 0.12 amplitude put it about 14 dB below the stop cue, which reads
     as a dead feature rather than a quiet one. If it is inaudible again,
     that is this number, not a fault in the code.

Run on the Pi, through the actual headset, at the volume the device
normally uses — a cue that is clear on a laptop speaker can disappear
under traffic noise:

    python -m indepensense.voice.tests.manual.cue_test

Judge them in sequence as well as one at a time. The failure that matters
is confusion between two cues, not any one of them being unpleasant.
"""
import time

from indepensense.voice.audio import (
    play_busy_cue,
    play_chime,
    play_stop_cue,
    play_waiting_tick,
)

# Long enough to hear each cue as its own event rather than as one run-on
# pattern, short enough to still judge them against each other.
_GAP_S = 1.2

CUES = [
    ("rising chime  (PTT pressed, recording starts)",
     lambda: play_chime(rising=True)),
    ("falling chime (PTT pressed again, recording ends)",
     lambda: play_chime(rising=False)),
    ("STOP cue      (repeat button — interrupted speech or cancelled a command)",
     play_stop_cue),
    ("BUSY cue      (press refused — a command is already running)",
     play_busy_cue),
    ("waiting blip  (still working — repeats every ~1.2 s)",
     play_waiting_tick),
]


def main() -> None:
    print("\nPlaying each cue with a pause between. Listen for whether the")
    print("stop cue and the falling chime can be told apart.\n")

    for label, cue in CUES:
        print(f"  {label}", flush=True)
        cue()
        time.sleep(_GAP_S)

    # Two pairs, not one. The stop/falling-chime pair share a falling
    # contour; the stop/busy pair share a count of two pulses.
    for first_label, first, second_label, second in (
        ("falling chime", lambda: play_chime(rising=False),
         "stop cue", play_stop_cue),
        ("stop cue", play_stop_cue,
         "busy cue", play_busy_cue),
    ):
        print(f"\nThe {first_label} and the {second_label}, back to back —")
        print("they share a shape, so this is where confusion would show:\n")
        for _ in range(2):
            print(f"  {first_label}", flush=True)
            first()
            time.sleep(0.6)
            print(f"  {second_label}", flush=True)
            second()
            time.sleep(_GAP_S)

    print("\nAnd the waiting blip as it is actually heard — five seconds")
    print("of it, which is a realistic wait for a cloud question:\n")
    for _ in range(4):
        play_waiting_tick()
        time.sleep(1.2)

    print("\nJudge that one for *intrusiveness*, not clarity. It should sit")
    print("under conversation, not demand attention — if it is irritating")
    print("after five seconds it will be unbearable after a long OCR read.")
    print("`_WAITING_AMPLITUDE` and `_WAITING_TICK` in voice/audio.py.")
    print("\nIf the stop cue and falling chime are hard to separate, change")
    print("`_STOP_CUE` there too — the pitches and durations are right there.\n")


if __name__ == "__main__":
    main()
