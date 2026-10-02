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
  3. **Busy cue** answers a press that was refused. It should sound like
     a refusal, flat rather than falling, in the way a telephone busy
     signal does.

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
]


def main() -> None:
    print("\nPlaying each cue with a pause between. Listen for whether the")
    print("stop cue and the falling chime can be told apart.\n")

    for label, cue in CUES:
        print(f"  {label}", flush=True)
        cue()
        time.sleep(_GAP_S)

    print("\nNow the pair that is easiest to confuse, back to back:\n")
    for _ in range(2):
        print("  falling chime", flush=True)
        play_chime(rising=False)
        time.sleep(0.6)
        print("  stop cue", flush=True)
        play_stop_cue()
        time.sleep(_GAP_S)

    print("\nIf those two are hard to separate, change `_STOP_CUE` in")
    print("voice/audio.py — the pitches and durations are right there.\n")


if __name__ == "__main__":
    main()
