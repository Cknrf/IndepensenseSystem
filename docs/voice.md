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
| Active language | English (see `SYSTEM_LANGUAGE` in config; Tagalog voice + model loaded but not yet wired to a switch) |
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

Synthesises a sample sentence in the current `SYSTEM_LANGUAGE` and writes
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

## Language switching (not yet wired)

`PIPER_VOICES` in `indepensense.config` is a `dict[str, Path]` mapping
language codes to ONNX voice paths. `PiperTTS` loads all configured voices
at construction. Callers pick a voice per synthesis call:

```python
tts.synthesize("Hello", out_path, language="en")
tts.synthesize("Kumusta", out_path, language="tl")
```

The active language at build time is `SYSTEM_LANGUAGE` in config. Runtime
switching (via the guardian dashboard) is planned but not yet implemented —
when it lands, only the application layer needs to change, not this driver.

## Updating voices or models

For a different Piper voice for an existing language, edit the path in
`PIPER_VOICES` and download the matching `.onnx` + `.onnx.json` pair.

To add a new language, add an entry to both `PIPER_VOICES` and
`WHISPER_MODELS` in `indepensense.config`, and download the Piper voice.
The new Whisper model auto-downloads on next run.

To upgrade a Whisper model (`tiny` → `base` → `small` → `medium` → `large-v3`),
edit the value in `WHISPER_MODELS` for the target language. The new model
auto-downloads on next run.
