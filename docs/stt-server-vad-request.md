# Request: enable voice-activity detection on the STT endpoint

Context for whoever maintains `gpuer`. Self-contained — no knowledge of
the client project needed.

## The endpoint

```
POST https://gpuer.techco.fi:8710/stt
model: whisper-large-v3-turbo
default language: tl
default prompt: a Batangas place-name list
```

## The problem

The endpoint transcribes silence and background noise into invented
text instead of returning an empty string. Whisper does this by
default — it has learned that audio produces words — and the usual
mitigation, voice-activity detection, does not appear to be enabled.

Reproduced against the live endpoint on 2026-10-13:

```
4 s of digital silence, 16 kHz mono PCM
  -> {"text": "Thank you.", "duration_s": 4.0}

4 s of quiet gaussian hiss (sigma 300, about -40 dBFS), same format
  -> {"text": "Matapet Jurgenio, Ramawoy, Diversion City, Avenida Hino,
       Betangas, Trival Astra, Otlova, Daytona, Matanakas, Jumbo,
       De La Salle, Mayatik Marawoy, Slee, Tessar, Orovo, ...",
      "duration_s": 4.0}
```

To reproduce:

```python
import wave, struct, random
def write(path, kind, seconds=4.0, rate=16000):
    n = int(seconds * rate)
    if kind == "silence":
        frames = [0] * n
    else:
        random.seed(0)
        frames = [int(random.gauss(0, 300)) for _ in range(n)]
    with wave.open(path, "wb") as h:
        h.setnchannels(1); h.setsampwidth(2); h.setframerate(rate)
        h.writeframes(b"".join(
            struct.pack("<h", max(-32768, min(32767, f))) for f in frames))
write("silence.wav", "silence")
write("noise.wav", "noise")
```

```bash
curl -s -X POST https://gpuer.techco.fi:8710/stt -F file=@silence.wav -F language=tl
curl -s -X POST https://gpuer.techco.fi:8710/stt -F file=@noise.wav   -F language=tl
```

## The part worth noticing

The noise output is **the default Batangas place-name prompt coming back
as a transcript**. With nothing real to transcribe, the model falls back
on the prompt and emits those place names.

That prompt is valuable — it raised exact place-name matches from 66 to
87 of 120 in the endpoint's own testing, and the client keeps it for
that reason. The request is not to remove it. But it does mean the
failure mode is not harmless noise: on a bad recording the endpoint
produces **place names specifically**, and the client is a navigation
device, so place names are exactly what it acts on.

## Why it matters to the caller

The client is a wearable for blind and low-vision users. Its pipeline is
`transcript -> intent classification -> action`, where actions include
starting navigation to a destination. A fabricated transcript can
therefore become a fabricated command. The client's intent classifier
will probably reject a bare list of place names — there is no command
verb in it — but "the next stage will probably catch it" is a weak place
to put the only defence.

The caller's own on-device Whisper runs with `vad_filter=True` and does
not have this behaviour: silence there produces an empty transcript, and
the device answers "I didn't hear anything". The remote path is the one
that differs.

## The ask

Enable voice-activity detection so that audio containing no speech
returns an empty `text` rather than invented words.

If the service is built on `faster-whisper`, this is the same flag the
client already uses locally:

```python
segments, info = model.transcribe(
    audio,
    vad_filter=True,
    # optional, tightens it further:
    # vad_parameters=dict(min_silence_duration_ms=500),
)
```

Other stacks have an equivalent — `whisper.cpp` has `--vad`, and most
serving wrappers expose it. If VAD is impractical, the standard
anti-hallucination parameters help on their own and are worth setting
regardless:

```
temperature=0                      # no sampling fallback
condition_on_previous_text=False   # stops a hallucination feeding itself
no_speech_threshold=0.6            # default; make sure it is applied
compression_ratio_threshold=2.4    # catches repetitive output
logprob_threshold=-1.0
```

The repetition in the noise example above (`Semi, Tessar, Orovo,` eight
times) is the signature `compression_ratio_threshold` is meant to catch,
which suggests that filter may not be active either.

## What "fixed" looks like

```
silence.wav -> {"text": ""}
noise.wav   -> {"text": ""}
```

Real speech should be unchanged. The client has 12 recorded Tagalog
command clips it measured at p50 0.72 s and p95 1.23 s round-trip
before this change; the same clips should still transcribe correctly and
at the same speed afterwards.

Two things to confirm when it is done:

1. Both reproduction files return an empty string.
2. Place-name accuracy is unchanged — the Batangas prompt should keep
   working for real speech. If VAD and the prompt interact badly, say
   so, because that trade matters to the caller and they would want to
   decide it rather than have it decided.
