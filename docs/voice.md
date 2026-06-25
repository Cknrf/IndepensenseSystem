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
| TTS voice | `en_US-lessac-medium` (~70 MB) |
| STT engine | faster-whisper (CTranslate2 backend) |
| STT model | `tiny` (~75 MB), `int8` quantized for CPU |
| STT compute type | `int8` (halves memory + roughly doubles CPU throughput vs `float16`) |
| Models stored at | `models/voices/`, `models/whisper/` (gitignored, downloaded on demand) |
| Test artifacts at | `data/test/voice/` |

## Why these choices

- **Piper over eSpeak/Festival.** Piper sounds genuinely natural; eSpeak/
  Festival are robotic and would weaken a thesis demo.
- **`en_US-lessac-medium`.** Reliable English voice, medium quality, ~70 MB.
  Other voices at https://github.com/rhasspy/piper/blob/master/VOICES.md.
- **faster-whisper over the original Whisper.** ~4× faster on CPU and ~50% less
  memory for the same accuracy. Same model weights via HuggingFace.
- **`tiny` over `base`.** `tiny` transcribes a short utterance in 1-2 s on Pi 5
  CPU; `base` is ~3× slower. Bump to `base` only if `tiny` accuracy proves
  inadequate.
- **`int8` quantization.** Pi 5 has no GPU; `int8` is the right CPU profile.

## Install Python dependencies

```bash
# On Mac (dev) and Pi (deploy) both:
pip install -r requirements.txt
```

This installs `piper-tts` and `faster-whisper` plus their dependencies.

## Download the Piper voice

Piper voice files are not pip-installed; they're downloaded from HuggingFace
and dropped on disk.

```bash
cd <project-root>
mkdir -p models/voices
cd models/voices

# ONNX weights
wget https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx

# JSON config (must sit next to the .onnx file with matching name)
wget https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json
```

After download:

```
models/voices/
├── en_US-lessac-medium.onnx        # ~63 MB
└── en_US-lessac-medium.onnx.json   # ~5 KB
```

## Whisper model — automatic on first use

`faster-whisper` downloads its model on first instantiation. Our driver passes
`download_root=models/whisper/` so the weights land in the project's models
directory (gitignored) rather than `~/.cache/`.

First run of `stt_test.py` will pause for ~30-60 s while it downloads the
`tiny` model. Subsequent runs are instant.

## Test it

**TTS:**

```bash
python -m indepensense.voice.tests.manual.tts_test
```

Synthesizes a sample sentence and writes
`data/test/voice/<timestamp>_tts.wav`. Copy to your Mac (`scp ...`) or play
locally (`aplay data/test/voice/*_tts.wav` on the Pi if audio output is
configured).

**STT (TTS → STT roundtrip):**

```bash
python -m indepensense.voice.tests.manual.stt_test
```

Without arguments, transcribes the most recent file in `data/test/voice/` —
giving you a synth-then-transcribe roundtrip check.

You can also pass an explicit WAV path:

```bash
python -m indepensense.voice.tests.manual.stt_test path/to/your/recording.wav
```

## Updating voices or models

For a different Piper voice, change `PIPER_VOICE_PATH` in `indepensense.config`
and download the matching `.onnx` + `.onnx.json` pair.

For a larger Whisper model (`base`, `small`, ...), change `WHISPER_MODEL_SIZE`
in `indepensense.config`. The new model is downloaded on next run.
