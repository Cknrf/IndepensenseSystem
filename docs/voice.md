# Voice — speech-to-text and text-to-speech

IndepenSense uses two local neural models for its voice assistant:

- **Piper** for text-to-speech (announcing obstacles, navigation guidance,
  responding to queries).
- **faster-whisper** for speech-to-text (transcribing user commands).

Both run entirely on the Pi 5 CPU — no cloud, no internet. This matches the
"offline-capable assistive wearable" thesis goal.

## Status reference

| Item | Value |
|---|---|
| TTS engine | Piper, ONNX runtime |
| TTS voice (English) | `en_US-lessac-medium` (~70 MB) |
| TTS voice (Tagalog) | `id_ID-news_tts-medium` (~60 MB), used as phonetic substitute |
| STT engine | faster-whisper (CTranslate2 backend) |
| STT model (English) | `tiny` (~75 MB), `int8` quantized |
| STT model (Tagalog) | `small` (~460 MB), `int8` quantized |
| Active language | Tagalog by default (`DEFAULT_LANGUAGE`), switchable at runtime by voice — see below |
| Models stored at | `models/voices/`, `models/whisper/` (gitignored, downloaded on demand) |
| Test artifacts at | `data/test/voice/` |

## Why these choices

- **Piper over eSpeak/Festival.** Piper sounds genuinely natural; eSpeak/
  Festival are robotic and would weaken a thesis demo.
- **`en_US-lessac-medium`.** Reliable English voice, medium quality, ~70 MB.
  Other voices at https://github.com/rhasspy/piper/blob/master/VOICES.md.
- **Indonesian voice as Tagalog substitute.** Piper does not currently
  provide a native Filipino/Tagalog voice. `id_ID-news_tts-medium` was
  chosen after A/B testing against Spanish (`es_MX` and `es_ES`) voices
  because Indonesian and Filipino are both Austronesian languages with
  matching 5-vowel systems, producing intelligible Tagalog output despite
  the audible Indonesian accent. Tagalog TTS via a natively-trained model
  is deferred to future work using Meta MMS-TTS.
- **Multi-voice `PiperTTS`.** The driver loads one Piper voice per
  configured language at construction time and picks per call. Loading a
  voice takes several seconds; loading both upfront removes latency at the
  cost of ~140 MB extra RAM.
- **faster-whisper over the original Whisper.** ~4× faster on CPU and ~50% less
  memory for the same accuracy. Same model weights via HuggingFace.
- **Per-language Whisper model size.** Whisper's non-English performance
  drops sharply at smaller model sizes — validated empirically on
  2026-07-19, where a spoken Tagalog paragraph produced heavily mangled
  transcripts on both `tiny` ("Kumusta ka na" → "kama stawana") and
  `base`. English on `tiny` transcribes the same paragraph
  near-perfectly. We therefore load `tiny` for English (~1.4 s STT
  latency) and `small` for Tagalog (~8-10 s for a 25 s clip; ~2-3 s for a
  short 5 s command — real-time boundary). Both instances live under
  `FasterWhisperSTT` and are picked per call — same design as the
  multi-voice `PiperTTS`.
- **`int8` quantization.** Pi 5 has no GPU; `int8` roughly halves memory
  and doubles CPU throughput vs `float16` with negligible accuracy cost
  at these model sizes.
## Install Python dependencies

```bash
# On Mac (dev) and Pi (deploy) both:
pip install -r requirements.txt
```

This installs `piper-tts`, `faster-whisper`, `sounddevice`, and `soundfile`
plus their transitive dependencies.

### System libraries required on the Pi

`sounddevice` and `soundfile` are thin wrappers around C libraries that pip
does not install. Add them via apt (one-time per Pi):

```bash
sudo apt install -y libportaudio2 libsndfile1
```

Without `libportaudio2` you will see `OSError: PortAudio library not found`
when importing `sounddevice`. Without `libsndfile1` most WAV reads/writes
will fail.

## Download the Piper voices

Piper voice files are not pip-installed. Use Piper's built-in downloader
(handles URL resolution and redirects reliably):

```bash
cd <project-root>
mkdir -p models/voices
cd models/voices

# English (default)
python3 -m piper.download_voices en_US-lessac-medium

# Indonesian (used as Tagalog substitute)
python3 -m piper.download_voices id_ID-news_tts-medium
```

After download:

```
models/voices/
├── en_US-lessac-medium.onnx           # ~63 MB
├── en_US-lessac-medium.onnx.json      # ~5 KB
├── id_ID-news_tts-medium.onnx         # ~60 MB
└── id_ID-news_tts-medium.onnx.json    # ~5 KB
```

To browse other available voices:

```bash
python3 -m piper.download_voices --list
```

## Whisper models — automatic on first use

`faster-whisper` downloads its models on first instantiation. Our driver
passes `download_root=models/whisper/` so the weights land in the project's
models directory (gitignored) rather than `~/.cache/`.

First run of any voice test will pause for ~2-4 minutes while it downloads
both configured models (~75 MB `tiny` + ~460 MB `small`). Subsequent runs
are instant — models are loaded from local disk.

## Test it

**TTS (file-based):**

```bash
python -m indepensense.voice.tests.manual.tts_test
```

Synthesises a sample sentence in `DEFAULT_LANGUAGE` and writes
`data/test/voice/<timestamp>_tts_<lang>.wav`. Copy to your Mac (`scp ...`) or
play locally (`aplay data/test/voice/*_tts.wav` on the Pi if audio output is
configured).

**STT (file-based, TTS → STT roundtrip):**

```bash
python -m indepensense.voice.tests.manual.stt_test
```

Without arguments, transcribes the most recent file in `data/test/voice/` —
giving you a synth-then-transcribe roundtrip check without needing a
microphone.

**End-to-end live audio (mic → STT → TTS → speaker):**

```bash
python -m indepensense.voice.tests.manual.echo_test
```

Prompts you to press Enter, records 10 seconds from the OS default input
device, transcribes it, synthesises the transcript back through Piper, and
plays the echo through the default output. Whatever audio device PipeWire
currently routes to (built-in audio, USB headset, paired Bluetooth
headphones) will be used automatically.

### Bluetooth audio troubleshooting

If echo playback goes to the wrong device, check the PipeWire default:

```bash
wpctl status
```

Look at the `Sinks` (output) and `Sources` (input) sections. The default is
marked with `*`. To change the default output:

```bash
wpctl set-default <ID>     # ID column from `wpctl status`
```

**AirPods and other Bluetooth headsets** appear as one device with two
possible profiles: A2DP (high-quality stereo output, no mic) and HSP/HFP
(mono mic + tinny mono output). Linux picks HSP automatically when a mic is
needed. If the mic returns silence in the echo test, force HSP explicitly:

```bash
wpctl set-profile <device-id> handsfree_head_unit
```

Device ID is from the `Devices` section of `wpctl status`.

## Per-language voices

`PIPER_VOICES` in `indepensense.config` is a `dict[str, Path]` mapping
language codes to ONNX voice paths. `PiperTTS` loads all configured voices
at construction. Callers pick a voice per synthesis call:

```python
tts.synthesize("Hello", out_path, language="en")
tts.synthesize("Kumusta", out_path, language="tl")
```

All configured voices load at construction, so switching language costs
nothing at switch time — no model reload, no delay. The active language is
runtime state (see the next section); this driver only ever sees an
explicit `language=` argument, so switching required no change here.

## Language switching

The wearable starts in `config.DEFAULT_LANGUAGE` (Tagalog) and switches on
a voice command. The choice persists to `var/language`, so it survives a
reboot — a user who chose English is not greeted in Tagalog after a power
cycle.

```
"Lumipat sa Ingles"        -> switches to English
"Switch to Tagalog"        -> switches to Tagalog
```

### The switch phrase must be in the language currently active

Whisper is **pinned** per language (`whisper.py` passes `language=`)
rather than auto-detecting. Two reasons, both practical:

- Detection on a two-second command is unreliable. Voice commands are
  short, which is very little signal to identify a language from, and a
  misdetection corrupts the entire transcription rather than just
  degrading it.
- Each language loads a *different model size* — `tiny` for English,
  `small` for Tagalog. Auto-detecting would mean choosing a model before
  knowing the language, then re-transcribing with the other one if the
  guess was wrong. Two passes on a CPU-only Pi.

So the user says "lumipat sa Ingles" *in Tagalog* to get English. This
trades a small interaction constraint for accuracy and latency.

### How the user knows which language is active

Two audible cues, since the user cannot read a screen:

1. **On boot**, the wearable greets in the active language.
2. **On switch**, the confirmation is spoken in the language being
   switched *to*. Asking for English and hearing Tagalog means the switch
   failed — the confirmation verifies itself.

`device.status` also reports the active language on request.

### Where the strings live

No response text is in Python. Every spoken string is in
`intents/messages.py`, keyed by message then language, and the executor
only ever calls `messages.get(key, language)`. Unit tests enforce that
every key covers every language and that placeholders match across
translations — a missing translation is a test failure, not a runtime
surprise.

Sentence *structure* can differ per language, not just wording. Tagalog
does not inflect nouns for number ("2 upuan", not "2 upuans"), so the
scene description takes a different code path per language. See
`messages.count_label`.

Object labels from YOLO stay in English unless `_TL_LABELS` translates
them. That is deliberate: Manila speech code-switches, so "Nakikita ko
ang 2 tao at isang chair" sounds natural while forcing a Tagalog coinage
for every COCO class would not.

## Cloud LLM fallback

The local NLU is deliberately biased toward `unknown` — a wearable that
guesses is worse than one that admits it did not understand. That leaves a
gap: "how many days until Christmas" is a reasonable thing to ask and is
not an intent.

So `unknown` is the trigger rather than a dead end. When the local parser
returns `unknown` and a cloud answerer is configured, the transcript goes
to a cloud LLM.

### Why not a dedicated `cloud.ask` intent

Because it would fight the bias that makes the local model trustworthy. A
catch-all intent gives the classifier a tempting bucket for anything it is
unsure about, and the failure mode is severe — "take me to the hospital"
routed to a chatbot instead of navigation. With `unknown` as the sole
entry point, the cloud only ever sees utterances the local model already
declined, so it cannot intercept a real command.

It also gives an honest metric for the thesis: how often the local model
defers, read straight off the `unknown` rate.

### What the user hears

Cloud answers take seconds. A sighted user watches a spinner; this user
hears nothing and cannot tell whether the wearable is thinking or dead. So
the pipeline speaks "let me think about that" before the call — spoken
rather than a tone, because it conveys both that the wearable heard them
and that an answer is coming.

Offline and provider-failure are reported differently on purpose. "No
internet connection" is actionable — move somewhere with signal — while a
provider error is not, and telling the user the wrong one sends them
looking for a problem that was never there.

### Privacy

Only the **transcript** is sent, never the recorded audio. STT already runs
on-device, so there is no reason to ship a voice recording to a third
party. The words a user spoke still leave the device, which belongs in the
ethics chapter, but that is a materially smaller disclosure than their
voice.

### Provider: Mistral

`intents/mistral.py` implements `CloudAnswerer` against Mistral's
OpenAI-shaped chat API. `CLOUD_LLM_ENABLED` is `True`; all it needs is a
key.

### Where the key lives

In a `.env` at the project root, which `config.py` loads into the
environment on import:

```bash
cp .env.example .env
nano .env                 # paste INDEPENSENSE_CLOUD_API_KEY
chmod 600 .env
```

A file rather than `export` in a shell, because neither of the two ways
this code runs inherits your login environment: systemd starts the
service with its own, and you run manual tests in fresh SSH sessions. A
file works for both and survives a reboot. **No `EnvironmentFile=` is
needed in the systemd unit** — `config.py` resolves the path from its own
location, so it behaves identically either way.

A variable already set in the real environment takes precedence over the
file, so a one-off override still works without editing anything:

```bash
INDEPENSENSE_CLOUD_API_KEY=other-key python -m indepensense.app
```

`.env` is gitignored; `.env.example` is the committed template. A missing
or empty key is a supported configuration — the wearable answers unknown
utterances locally and logs that the fallback is unconfigured once at
startup. The variable name is deliberately provider-neutral: the driver is
one implementation of a protocol, and swapping it should not mean renaming
a secret.

### Verifying it works

```bash
python -m indepensense.intents.tests.manual.cloud_probe
```

Makes real calls in both languages and reports cold vs warm latency,
answer length, and whether any markdown leaked into the output. Read the
Tagalog answers rather than just checking they arrived.

### Latency, and why the EU hop is not the problem

Mistral is EU-hosted, so round-trip from the Philippines is roughly
250 ms versus ~40 ms to Singapore. That is not a reason to switch
providers. Generation time dominates — a short answer takes 0.5–1 s to
produce wherever you are — and this call already sits on top of a 4–6 s
chain (Tagalog STT, local NLU, Piper). An extra 0.2 s of RTT is noise in
that budget.

Two things do matter, and both are handled in the driver:

- **`max_tokens` is capped at 100.** Generation time scales with output
  length, making this the largest single lever. The system prompt also
  asks for at most 40 words, because `max_tokens` truncates mid-sentence
  while an instruction produces a complete short answer.
- **The HTTP connection is reused.** A cold TLS handshake is about three
  round trips before the request is even sent — ~0.75 s at this distance.
  A per-instance `Session` means only the first call after startup pays
  it.

Streaming is deliberately unused: Piper needs the complete text before it
can synthesise, so there is nothing to overlap.

`CLOUD_LLM_TIMEOUT_S` is 10 s. The constraint is the user's patience, not
the provider's — by 20 s a blind user has been standing on a corner
hearing only the thinking cue.

### The system prompt is written for speech

The answer goes straight to Piper, which drives every constraint in
`_SYSTEM_PROMPT`: no markdown (asterisks and bullets get read aloud as
literal characters), numbers written the way they should be said, and an
explicit instruction to admit ignorance rather than invent. That last one
matters more here than for a chat product — a user who cannot see cannot
cross-check an invented answer.

### Tagalog is unverified

Tagalog is low-resource for most providers and Mistral's quality there has
not been measured. Test it before trusting it. If answers come back poor,
requesting English regardless is a defensible fallback: a correct English
answer beats a garbled Tagalog one, and the wearable already speaks
English well.

## Updating voices or models

For a different Piper voice for an existing language, edit the path in
`PIPER_VOICES` and download the matching `.onnx` + `.onnx.json` pair.

To add a new language, add an entry to both `PIPER_VOICES` and
`WHISPER_MODELS` in `indepensense.config`, and download the Piper voice.
The new Whisper model auto-downloads on next run.

To upgrade a Whisper model (`tiny` → `base` → `small` → `medium` → `large-v3`),
edit the value in `WHISPER_MODELS` for the target language. The new model
auto-downloads on next run.
