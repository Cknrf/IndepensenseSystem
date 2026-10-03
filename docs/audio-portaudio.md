# Short audio cues are silently discarded — open problem

**Status:** worked around, not solved. The remedy works; the mechanism is
unidentified and one experiment contradicts the current explanation.

This document is written for someone with no prior context on the
project. It is the handover brief for a second opinion.

---

## 1. The system, in one paragraph

A wearable assistive device on a **Raspberry Pi 5** (Raspberry Pi OS
Trixie, Python 3.13). Audio in and out goes through a **USB headset**
(NEWMSNR, single device providing both microphone and speaker) via
**PipeWire / WirePlumber**. Python talks to it through
**`sounddevice`** (a PortAudio binding), with `soundfile` for WAV I/O and
`numpy` for tone synthesis. All audio code lives in one module,
`src/indepensense/voice/audio.py`.

The device is used by someone who cannot see it, so **every short
non-speech cue is load-bearing**: a chime acknowledging a button press, a
tone saying "I stopped talking", a tone saying "that press was refused",
and a soft blip repeating while the device thinks. A silent cue is
indistinguishable from broken hardware.

---

## 2. The symptom

**Short sounds do not play. Long sounds do.**

Within a single Python process, playing a 200 ms cue five times with a
3-second gap between them:

```python
from indepensense.voice.audio import play_stop_cue
import time
for n in range(5):
    play_stop_cue(); time.sleep(3)
```

Result: **the first one is audible, the rest are silent.**

Speech (2–5 s utterances) always worked, which is why this went unnoticed
for a long time — an utterance that loses its opening still conveys its
meaning, and the listener's context fills the gap.

---

## 3. What was measured

All on the device. Nothing in this table is inferred.

| Experiment | Result |
|---|---|
| One process, 200 ms cues 3 s apart | #1 audible, #2 **silent**, 1 s tone audible, #3 **silent** |
| Five *separate* processes, same cue | audible **5/5** |
| `aplay` with the same file, 3 s apart | audible every time |
| 200 ms cue played 0.3 s after a long tone | **audible** |
| `Pa_Terminate()` + `Pa_Initialize()` before each stream | audible every time |
| Deferring that re-init to stream *close* | **silent again** |
| Re-init, then sleep 0–3 s, then open and play | **audible at every gap** |

Instrumentation of the stream itself (`audio_probe`, in-repo) showed the
output path behaving correctly in every case: the stream negotiated the
requested 22050 Hz, reported 23 ms of latency, and consumed 1.0 s of
audio in 0.96 s on the first attempt and the fiftieth alike. **The audio
is always produced correctly and discarded somewhere downstream.**

The amount discarded is roughly **0.8 s** — which erases a 200 ms cue
entirely and merely clips the opening off a sentence.

---

## 4. What did *not* fix it

Each of these was implemented, tested on the device, and rejected:

- **PipeWire / WirePlumber suspend settings.**
  `session.suspend-timeout-seconds = 0` and `node.pause-on-idle = false`
  on the ALSA sink. Verified accepted — `pw-dump` showed the node state
  change from `suspended` to `running` — and the cues stayed silent. The
  config file is still in `deploy/pipewire/51-no-suspend.conf`; it is
  retained, not credited.
- **Leading silence.** Opening each stream with 0.2 s of silence, on the
  theory that start-up underrun was eating the beginning. It made things
  *worse*: it pushed the real sound further into whatever window is being
  discarded, turning a clipped cue into a wholly silent one.
- **Stream parameters.** `blocksize`, `latency`, an explicit `stop()`
  before `close()`, and `sd.play()` itself — all failed identically.
- **An amplifier keep-alive thread** writing continuous silence to keep
  the headset's amplifier awake. It **segfaulted** (see §6).

---

## 5. The current workaround

`sd._terminate()` followed by `sd._initialize()` — i.e. `Pa_Terminate` /
`Pa_Initialize` — immediately before constructing **each output stream**.
See `_reinitialise_portaudio` and `_claim_portaudio` in
`src/indepensense/voice/audio.py`.

Three things are known about it:

1. **It works.** Five cues, five sounds, reproducibly.
2. **It must be adjacent.** Doing the same re-init when the *previous*
   stream closes — so the next stream opens on an already-re-initialised
   context — passed every unit test and failed on the device within a
   minute. See §7, because this is the part that does not add up.
3. **It costs 69–96 ms per sound on the Pi** (2 ms on macOS/CoreAudio),
   because it re-enumerates every ALSA device. It cannot be moved off the
   critical path, since being on the critical path appears to be what
   makes it work.

**Input streams are unaffected.** Measured with `mic_onset_test`
(in-repo): a recording opened with no re-init captured 2.004 s of a
2.000 s window, identical to one opened with. Only short *output* needs
the adjacency, so the recording path no longer pays the cost.

---

## 6. Two constraints anyone touching this must know

**Terminating PortAudio while a stream is live is a C-level double
free.** The project has already hit this once, from a different cause:
`double free or corruption (out)`, process aborted, no Python traceback.
A re-init is therefore guarded by a count of open streams — input and
output alike — and is skipped entirely if anything is open. A clipped cue
is a bad outcome; a crash is not an outcome at all.

**`Pa_Initialize` / `Pa_Terminate` are reference counted**, and
`sounddevice` mirrors the count in the private `sd._initialized`.
Importing `sounddevice` leaves it at 1. Two consequences, both found by
experiment:

- A count above 1 means a single `_terminate()` tears nothing down, and
  the workaround silently stops working with no symptom but the cues
  going quiet again.
- The obvious `try: _terminate(); _initialize()` is **wrong**. Tearing
  down an already-down PortAudio raises `paNotInitialized`, which skips
  the initialise and leaves the library terminated *permanently* — every
  later stream dies with `Error querying device -1` and the device is
  mute until restart. One transient `Pa_Initialize` failure, which a USB
  re-enumeration can cause, was enough to reach that state.

The current code targets the invariant `sd._initialized == 1` rather than
issuing a fixed pair of calls.

---

## 7. The open contradiction

This is the part a fresh pair of eyes is most wanted on.

The working explanation is **adjacency**: a stream plays a short sound
only if `Pa_Initialize` ran immediately before it. That fits rows 1–5 of
the table in §3, including why separate processes and `aplay` work —
import-then-play is adjacent.

It is contradicted by the last two rows:

- **Deferred re-init failed.** Re-initialising when stream *N* closes,
  then opening stream *N+1* three seconds later: silent.
- **Explicit gap test passed.** Re-initialise, `sleep(gap)`, open a
  stream, play — **audible at gap = 0, 0.5, 1, 2 and 3 seconds.**

Those two are structurally the same thing: a re-init, then a delay, then
a stream. One failed on the device and one succeeded. Either there is a
difference between them nobody has spotted, or one of the observations is
contaminated.

Candidate differences not yet ruled out: the deferred version ran inside
the application (threads, locks, a `finally` block) while the gap test
was a flat script; the deferred version's first sound deliberately
skipped the re-init; the application sets `blocksize=512` on its streams
and writes in blocks, the gap test used defaults and a single write.

---

## 8. What has not been tried

Listed roughly in order of how promising they look.

- **One long-lived output stream.** Keep a single `OutputStream` open for
  the life of the process and write every sound into it, instead of
  opening and closing one per sound. If the fault is in per-stream
  start-up, this sidesteps it completely, and it is the conventional
  design for a process that makes frequent short sounds. The current
  one-stream-per-call model exists for a different reason — it is what
  makes stream ownership unambiguous after the double-free crash — but
  that is a solvable constraint, not a requirement.
- **Bypass ALSA.** Everything so far goes PortAudio → ALSA → PipeWire's
  ALSA compatibility layer. Testing with `pw-cat` or PipeWire's native
  API would say whether the fault is in that compatibility path.
- **A different USB audio device**, to establish whether the headset is
  implicated at all.
- **USB autosuspend** (`usbcore.autosuspend`, `/sys/bus/usb/.../power/control`)
  and `dmesg` around a silent cue.
- **PortAudio built against a different backend**, or a newer PortAudio
  than the distribution's.

---

## 9. How to reproduce in fifteen seconds

On the Pi, in the project venv:

```bash
# A — re-init AFTER each stream. Expected: only the first is audible.
python -c "
import sounddevice as sd, numpy as np, time
t=np.linspace(0,0.2,int(22050*0.2),False)
cue=(0.3*np.sin(2*np.pi*880*t)).astype(np.float32).reshape(-1,1)
for n in range(5):
    print(' ',n+1,flush=True)
    s=sd.OutputStream(samplerate=22050,channels=1,dtype='float32')
    with s: s.write(cue)
    sd._terminate(); sd._initialize()
    time.sleep(3)
"

# B — re-init BEFORE each stream. Expected: all five audible.
python -c "
import sounddevice as sd, numpy as np, time
t=np.linspace(0,0.2,int(22050*0.2),False)
cue=(0.3*np.sin(2*np.pi*880*t)).astype(np.float32).reshape(-1,1)
for n in range(5):
    sd._terminate(); sd._initialize()
    print(' ',n+1,flush=True)
    s=sd.OutputStream(samplerate=22050,channels=1,dtype='float32')
    with s: s.write(cue)
    time.sleep(3)
"
```

**A and B have not actually been run side by side.** They are the test
that would settle §7 and they are the first thing to do.

To hear the application's own cues:

```bash
python -m indepensense.voice.tests.manual.cue_test
```

To disable the workaround entirely and confirm the fault is still there,
change the single call at `src/indepensense/voice/audio.py:503`:

```python
_claim_portaudio(refresh=False)   # was: _claim_portaudio()
```

---

## 10. A separate bug, already fixed, that produced similar reports

Worth knowing because it muddied the field reports. The application holds
a mutex (`_warning_lock`) to serialise vibration-motor and buzzer
patterns. One code path held it across a *blocking audio call* — the
button-press chime — and the audio layer's own lock is held by the
announcer for a whole utterance, up to thirty seconds on an OCR read.

A button press during a long utterance therefore froze the button
callback thread, every obstacle warning, and the **emergency buzzer**,
for the length of that utterance. It presented as "the whole program gets
stuck and the button stops working", which is easy to misattribute to the
audio problem above.

Fixed in `app.py:_play_press_feedback`; the chime now runs outside the
mutex. Regression tests in
`src/indepensense/tests/unit/test_app_feedback_locks.py`, including one
that reproduces the deadlock with a deliberately stalled chime.

---

## 11. Summary for the reader

- A working remedy exists and is in place.
- Its mechanism is **not** understood, and this is documented as an
  empirical remedy rather than a fix.
- One experiment contradicts the current explanation, and the decisive
  A/B in §9 has not been run.
- The most promising untried direction is a **single long-lived output
  stream** (§8).
- Any change must respect the two constraints in §6.
