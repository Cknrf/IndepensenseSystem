# Voice — speech-to-text and text-to-speech

IndepenSense uses two local neural models for its voice assistant:

- **Piper** for English text-to-speech (announcing obstacles, navigation
  guidance, responding to queries).
- **Meta MMS-TTS** for Tagalog text-to-speech.
- **faster-whisper** for speech-to-text (transcribing user commands).

Both run entirely on the Pi 5 CPU — no cloud, no internet. This matches the
"offline-capable assistive wearable" thesis goal.

## Status reference

| Item | Value |
|---|---|
| TTS engine (English) | Piper, ONNX runtime |
| TTS engine (Tagalog) | MMS-TTS (VITS, 36.3M params), transformers + torch |
| TTS voice (English) | `en_US-lessac-medium` (~70 MB) |
| TTS voice (Tagalog) | `facebook/mms-tts-tgl` (~145 MB), natively trained |
| TTS voice (Tagalog) licence | CC-BY-NC 4.0 — academic use only |
| STT engine | faster-whisper (CTranslate2 backend) |
| STT model (English) | `tiny` (~75 MB), `int8` quantized |
| STT model (Tagalog) | `small` (~460 MB), `int8` quantized |
| Active language | Tagalog by default (`DEFAULT_LANGUAGE`), switchable at runtime by voice — see below |
| Models stored at | `models/voices/`, `models/whisper/` (gitignored, downloaded on demand) |
| Test artifacts at | `data/test/voice/` |
| Speaker volume | `wpctl` on the default PipeWire sink, 20-100%, persisted to `var/volume` |
| Output ownership | one announcer thread for all main-loop speech; see below |
| Engine selection | `MultiEngineTTS` (`voice/router.py`), one engine per language |

## Why these choices

- **Piper over eSpeak/Festival.** Piper sounds genuinely natural; eSpeak/
  Festival are robotic and would weaken a thesis demo.
- **`en_US-lessac-medium`.** Reliable English voice, medium quality, ~70 MB.
  Other voices at https://github.com/rhasspy/piper/blob/master/VOICES.md.
- **MMS-TTS for Tagalog, replacing the Indonesian stand-in.** Piper
  publishes no Filipino/Tagalog voice. Until 2026-09-17 the `tl` slot held
  `id_ID-news_tts-medium`, picked after A/B testing against Spanish
  (`es_MX`, `es_ES`) voices because Indonesian and Filipino are both
  Austronesian with matching 5-vowel systems. It was intelligible, but two
  things were wrong with it:

  1. The accent was audibly Indonesian, not Filipino.
  2. Worse, Piper phonemises through espeak-ng using the *voice's*
     language, so digits in a message were expanded with Indonesian number
     rules — "90 metro" was spoken "sembilan puluh metro". That is not an
     accent, it is the wrong language on the most safety-relevant word in
     a navigation cue.

  `facebook/mms-tts-tgl` is trained on Tagalog itself. The second problem
  is fixed independently, by spelling numbers out before synthesis — see
  **Tagalog numerals** below.

- **Two engines behind one interface.** English stays on Piper (better
  quality, permissive licence) and Tagalog moves to MMS, so the
  per-language map moved out of `PiperTTS` and up into `MultiEngineTTS`
  (`voice/router.py`). Callers still see the plain `TTSEngine` protocol.
  Both engines load at startup rather than on demand: loading either takes
  seconds, and a lazy load would put that in front of the user on every
  language switch. Cost is ~215 MB resident.

- **The CC-BY-NC licence is a real constraint.** Piper's voices are
  permissively licensed; MMS-TTS is CC-BY-NC 4.0. Non-commercial academic
  use is squarely within it, and it is attributed here and in the thesis,
  but a commercial build of IndepenSense would need a different Tagalog
  voice. Recorded rather than glossed over.

- **transformers/torch rather than an ONNX export.** MMS is a VITS model
  and could be exported to ONNX to run on the onnxruntime Piper already
  pulls in (~1.3x faster, per the sherpa-onnx project). We did not: torch
  is already installed for YOLO, so the transformers path costs one new
  package and no conversion step. sherpa-onnx publishes pre-converted
  `vits-mms` models for only eight languages and Tagalog is not among
  them, so the export would have to be maintained by us. Worth revisiting
  only if measured TTS latency turns out to matter.
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

## Download the TTS voices

Neither voice is pip-installed. Both live under `models/voices/`, which is
gitignored.

### English — Piper

Use Piper's built-in downloader (handles URL resolution and redirects
reliably):

```bash
cd <project-root>
mkdir -p models/voices
cd models/voices

python3 -m piper.download_voices en_US-lessac-medium
```

To browse other available voices: `python3 -m piper.download_voices --list`.

### Tagalog — MMS-TTS

Downloaded as a local snapshot rather than resolved from the Hub at
runtime, so a Pi with no network still starts and the model in use is the
one that was tested:

```bash
cd <project-root>/models/voices
pip install huggingface_hub          # if not already present
python3 -c "
from huggingface_hub import snapshot_download
snapshot_download('facebook/mms-tts-tgl', local_dir='mms-tts-tgl')
"
```

After both downloads:

```
models/voices/
├── en_US-lessac-medium.onnx           # ~63 MB
├── en_US-lessac-medium.onnx.json      # ~5 KB
└── mms-tts-tgl/                       # ~145 MB
    ├── config.json
    ├── model.safetensors
    ├── tokenizer_config.json
    └── vocab.json
```

If `models/voices/mms-tts-tgl/` is missing, startup aborts with a
`FileNotFoundError` naming the path — the same failure mode as a missing
Piper voice.

## Tagalog numerals

MMS is a **character-level** model: its vocabulary is 43 characters and it
has no text frontend at all. Two consequences shape how messages are
written.

**Numbers must already be words.** Piper expands "90" via espeak-ng; MMS
does not. Digits are technically in the vocabulary, but the MMS-lab corpus
spells numbers out, so they are effectively untrained and their
pronunciation is unpredictable. `intents/messages.py` therefore spells
every Tagalog numeral out before it reaches the engine —
`tagalog_number(90)` is `"siyamnapu"`. English keeps its digits, because
espeak-ng handles them correctly for the English voice.

**Native numerals, not Spanish-derived.** Filipinos commonly use the
Spanish-derived set for measurements ("nobenta metro", "dos"). Both are
idiomatic; native was chosen so the catalogue stays in one register rather
than mixing two.

**Tagalog links numerals to nouns.** "dalawa upuan" is ungrammatical — it
must be "dalawang upuan". The linker has three forms selected by the
numeral's final sound (`-ng` after a vowel, `-g` after `-n`, separate word
`na` otherwise), so the number changes the shape of the sentence around
it. `tagalog_counter` produces the linked form that templates interpolate.
`intents/tests/unit/test_tagalog_numbers.py` asserts the spelling of every
rule, including the `daan`/`raan` alternation in the hundreds.

**Sentence punctuation is dropped.** No period, comma or question mark is
in the vocabulary, so a three-sentence message would render as one
run-on breath. `MmsTTS` splits on sentence boundaries and inserts 250 ms
of real silence between them, which is the phrasing espeak-ng gives Piper
for free.

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


## Who is allowed to speak

Every piece of audio the wearable produces goes out through one output
device, and more than one part of the runtime wants to use it. The rules
that keep that from becoming a mess:

**The main loop never speaks directly.** It calls `App._announce(text)`,
which appends to a queue and returns. A single long-lived worker — the
announcer — does the synthesis and playback. This is not tidiness: before
it existed, navigation cues synthesised and played inline on the 100 Hz
loop, so fall detection and obstacle polling stopped for ~3-4 seconds
during every turn instruction. The loop sat inside `sd.play(blocking=True)`
while the user walked.

**Critical announcements preempt.** `_announce(..., critical=True)` aborts
whatever is playing, discards pending non-critical items, and goes to the
front. Used for detected falls and the critical battery tier. It also
abandons anything caught mid-*synthesis* — Piper takes about a second, which
is long enough for a fall to happen inside it, and making the alert wait out
an instruction the user no longer needs would defeat the point.

**The voice pipeline keeps its own playback.** It plays its response
synchronously because the PTT cycle is inherently sequential, and
`_voice_active` stops the main loop talking over it. Two sub-steps also run
there and block only that thread: destination confirmation and turn-to-face
orientation.

**Anything can be stopped.** `voice/audio.py` tracks whether speech is on
the speaker (`is_playing()`) and can abort it from any thread
(`stop_playback()`), which is what makes the repeat button dual-purpose —
stop while talking, repeat while silent. Without it, `vision.read` on a menu
was thirty seconds the user had to wait out.

## Volume

`system.volume` sets the PipeWire sink level by voice: "louder", "quieter",
or a number. Steps are 10%, the range is 20-100%, and the choice persists to
`var/volume` and is re-applied at startup — the OS keeps whatever it last
had, which after a reboot is not necessarily what the user chose.

**The 20% floor is a hard clamp, not a default.** Speech is this device's
only channel to its user, so a volume low enough to be inaudible on a busy
road is a trap with no way out: they cannot hear the response that would let
them turn it back up, and there is no screen to fall back on. Asking for less
gets the floor *and an explanation*, because silently clamping would read as
being misheard.

**The buzzer is unaffected.** It is driven straight from GPIO
(`feedback/gpio_buzzer.py`) and never passes through the audio sink, so
obstacle warnings and the emergency acknowledgement keep their loudness
whatever the user sets. Volume control structurally cannot silence a safety
alert — that is a property of the wiring, not a rule someone has to remember.

`wpctl` rather than `amixer`: Trixie runs PipeWire, and `amixer` talks to
ALSA underneath, which on a PipeWire system adjusts a different mixer than
applications actually play through. The classic symptom is a volume change
that appears to work and changes nothing audible.
