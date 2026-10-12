# Speech-to-text on gpuer: evaluation and deployed API

The wearable transcribes on the Pi, and only Tagalog speech is offloaded to a server. This doc covers the evaluation and the API that came out of it.

Three self-hosted candidates were scored on the same recordings on the `gpuer` server (RTX 6000 Ada, 48 GB): Whisper large-v3-turbo, Whisper large-v3, and NCSpeech's Tagalog FastConformer. Run on 2026-10-12. The test set includes English, but English is not required, so the decision below rests on the Tagalog and Taglish clips. Taglish is in scope because it is spoken in Tagalog mode.

## Deployed API

**Whisper large-v3-turbo on faster-whisper, public, no authentication:**

```
https://gpuer.techco.fi:8710
```

### `POST /stt`

`multipart/form-data`:

| Field | Default | Meaning |
|---|---|---|
| `file` | required | Audio in any common format (WAV, FLAC, MP3, M4A, OGG). It is decoded and resampled to 16 kHz mono on the server |
| `language` | `tl` | Whisper language code. Leave it at `tl` for Tagalog and Taglish; an invalid code gives `400` |
| `prompt` | the Batangas place list | Replaces the default `initial_prompt`. Send an empty value for no prompt |

The response is JSON:

```json
{"text": "Panavigate naman sa SM City Batangas.", "language": "tl", "duration_s": 3.12, "processing_s": 0.146}
```

`processing_s` is decode plus transcription on the server; network time is extra. Undecodable or empty audio gives `400`. Uploads are capped at 25 MB.

```bash
curl -F file=@command.wav https://gpuer.techco.fi:8710/stt
```

```bash
curl -F file=@command.wav -F prompt= https://gpuer.techco.fi:8710/stt
```

`GET /health` returns `{"status":"ok","model":"whisper-large-v3-turbo","default_language":"tl"}`.

### Configuration, and the measurement behind each setting

| Setting | Value | Why |
|---|---|---|
| Language | Given (`tl`), never detected | Whisper's language ID follows the accent: it labelled correctly transcribed, Filipino-accented English as Tagalog in up to 58 of 60 clips. Detection also cost +0.3 WER and ~50 ms ([Language detection](#language-detection)) |
| `initial_prompt` | `Destinations in Batangas: ` + 40 municipalities and landmarks | On Tagalog/Taglish destination requests, exact place-name matches went from 66 to 87 of 120 and WER fell 2.5 points (significant). It cost +0.5 WER on pure Tagalog, also significant ([Tagalog results](#tagalog-and-taglish-results)) |
| `num_workers` | 2 | Throughput levels off by 4 concurrent requests. At 2, one instance sustains ~12 requests/s with p95 under 300 ms ([Concurrent requests](#concurrent-requests)) |
| Beam size, VAD | 5, off | As evaluated. Commands are single short utterances, so VAD has nothing to trim |

On the public endpoint, tested from a laptop in Finland:
- **Clean Tagalog:** a real FLEURS clip (13.9 s) came back word for word apart from "September" for *Setyembre* and one misspelling, in 0.49 s of server time.
- **Noisy Taglish destination:** at 5 dB SNR, "Pa-navigate naman sa SM City Batangas" was correct, in 0.15 s.

The model uses 2.5 GB of GPU memory.

### Model choice

**Deployed: large-v3-turbo.** On the Tagalog and Taglish clips, **large-v3 with the prompt was more accurate**:
- 13.1% against 14.6% WER overall, −1.5 points [−2.2, −0.8].
- It was significantly better on every subset tested: pure Tagalog, Taglish, 0 dB noise and place names.

Turbo costs about half as much to run:

| | Turbo | Large-v3 |
|---|---|---|
| Median latency | 85 ms | 177 ms |
| p95 latency | 151 ms | 471 ms |
| Throughput | 12.6 requests/s | 7.3 requests/s |
| GPU memory | 2.4 GB | 4.0 GB |

Switching models is a one-line change: `MODEL_PATH` in `~/stt/server.py`. The converted large-v3 weights are kept in `~/stt-eval/models/ct2-whisper-large-v3`.

NCSpeech FastConformer was level with turbo on pure Tagalog and was the fastest model (32 ms, 1.4 GB). It is not used, for two reasons:
- **Taglish:** it was significantly worse, +6.1 WER [+3.5, +8.7].
- **Place names:** it was significantly worse on destination requests (+4.9 WER), and it cannot take a place-name prompt.

The tokenizer has only Filipino letters, and English words inside Tagalog sentences are where it fails.

## Tagalog and Taglish results

These come from the same runs as the full tables below, restricted to Tagalog and Taglish clips: 180 clips × 4 noise conditions. Language was forced to `tl`.

| Model | Overall WER | clean | 10 dB | 5 dB | 0 dB | Pure Tagalog | Taglish | Place names exact / near (of 120) | Median | p95 |
|---|---|---|---|---|---|---|---|---|---|---|
| large-v3-turbo | 14.3 | 12.0 | 12.1 | 13.7 | 19.5 | 14.3 | 14.3 | 66 / 90 | 81 ms | 162 ms |
| **large-v3-turbo + prompt** (deployed) | 14.6 | 11.8 | 12.6 | 13.9 | 19.9 | 14.8 | 12.8 | 87 / 101 | 85 ms | 151 ms |
| large-v3 | 14.3 | 12.1 | 12.7 | 14.2 | 18.2 | 14.5 | 12.8 | 68 / 89 | 158 ms | 428 ms |
| large-v3 + prompt | **13.1** | **11.2** | **11.3** | **12.9** | **16.9** | **13.5** | **9.9** | **94 / 102** | 177 ms | 471 ms |
| NCSpeech FastConformer | 14.9 | 13.0 | 13.5 | 14.8 | 18.3 | 14.4 | 18.8 | 56 / 76 | 32 ms | 59 ms |

Paired bootstrap (B − A; negative means B is better):

| A → B | Subset | WER A → B | Difference [95% CI] | |
|---|---|---|---|---|
| turbo + prompt → large-v3 + prompt | all | 14.6 → 13.1 | −1.5 [−2.2, −0.8] | significant |
| | pure Tagalog | 14.8 → 13.5 | −1.3 [−2.1, −0.5] | significant |
| | Taglish | 12.8 → 9.9 | −2.9 [−4.9, −1.1] | significant |
| | 0 dB | 19.9 → 16.9 | −3.0 [−5.1, −1.2] | significant |
| | destination requests | 10.3 → 7.0 | −3.4 [−5.5, −1.4] | significant |
| turbo + prompt → NCSpeech | all | 14.6 → 14.9 | +0.3 [−0.8, +1.5] | not significant |
| | pure Tagalog | 14.8 → 14.4 | −0.4 [−1.7, +0.8] | not significant |
| | Taglish | 12.8 → 18.8 | +6.1 [+3.5, +8.7] | significant |
| | 0 dB | 19.9 → 18.3 | −1.6 [−4.4, +0.9] | not significant |
| | destination requests | 10.3 → 15.2 | +4.9 [+2.2, +7.9] | significant |
| turbo → turbo + prompt | all | 14.3 → 14.6 | +0.2 [−0.2, +0.7] | not significant |
| | pure Tagalog | 14.3 → 14.8 | +0.5 [+0.0, +0.9] | significant |
| | Taglish | 14.3 → 12.8 | −1.6 [−3.3, +0.1] | not significant |
| | destination requests | 12.8 → 10.3 | −2.5 [−4.5, −0.6] | significant |

The prompt is an English sentence followed by the place list. A Tagalog-phrased prompt was not tested and might avoid the small cost on pure Tagalog.

## Test set

Every model transcribed exactly the same 1,056 files: 264 clips in 4 noise conditions.

| Set | Clips | Source | What it tests |
|---|---|---|---|
| FLEURS English | 60 | Real read speech, FLEURS `en_us` test split | General English accuracy on real voices |
| FLEURS Tagalog | 60 | Real read speech, FLEURS `fil_ph` test split | General Tagalog accuracy on real voices |
| Commands, English / Tagalog / Taglish | 45 / 33 / 21 | The NLU dev set (`intents/tests/manual/cases/dev.jsonl`), synthesised | What users actually say to the cane |
| Batangas destinations | 15 / 15 / 15 (en / tl / Taglish) | Written for this test, synthesised | Local place names |

- **Synthesis:** the command and destination sentences were voiced by the OmniVoice Filipino model, cloning six real Filipino FLEURS speakers. FLEURS `fil_ph` test has only male speakers, so the three female voices came from the train split, which is never scored.
- **Noise:** each clean clip was also mixed with real recorded noise from DEMAND (street traffic, public square, bus, cafeteria) at 10, 5 and 0 dB SNR. 0 dB means the noise is as loud as the speech.
- **Place names in the prompt:** 30 of the 45 destination sentences name a place in the prompt list. The other 15 use places deliberately left out of it (Alangilan, Bolbok, Pallocan, Calatagan, Taysan and others), to measure what the prompt does for names it was not told about.

### Limitations

Read these before citing the numbers:

- **The domain speech is synthetic.** It is cloned from real Filipino voices, but TTS is cleaner and more regular than a person speaking into a cane while walking. Absolute WER on those sets is probably optimistic. The *comparison* between models is fair, because every model heard identical audio.
- **The real-speech sets are read Wikipedia sentences, and the English speakers are American.** No real recordings of target users from Batangas exist yet.
- **The sets are small.** A Tagalog command set of ~180 words moves 0.5 points per word. Differences in the per-set table below are therefore only claimed where the bootstrap says they are significant.
- **Noise was added digitally**, not recorded live. Real microphone placement, wind and the user's own footsteps are not represented.
- **Latency is measured on the server only.** A request from the Pi adds the cellular round trip, ~0.7–0.8 s over the SIM7600 as measured for the other cloud services. That dwarfs the model's 80–160 ms.

The next step that would most strengthen this evaluation is 50–100 real utterances from target users, recorded on the cane's own microphone in Batangas, scored with the same scripts.

## Method

- **Runtime:** faster-whisper 1.2.1 on CTranslate2 4.8.2, float16, beam size 5, no VAD (the clips are short single utterances).
- **Weights:** both Whisper models were converted by us from the exact `openai/*` repositories, not third-party conversions. NCSpeech ran on NeMo 3.0.0 with its default RNNT decoder.
- **WER normalisation:** corpus-level (total errors ÷ total reference words). The same normaliser is applied to both sides: lowercase, hyphens and apostrophes removed, other punctuation to spaces. Numbers are not normalised.
- **Place hit, exact:** the destination name appears verbatim.
- **Place hit, near:** fuzzy similarity ≥ 85%. This catches phonetic spellings such as "Kalatagan" for Calatagan or "Bawan" for Bauan, which a fuzzy geocoder like Photon may still resolve.
- **Significance:** paired bootstrap over clips, 2,000 resamples. A difference is called significant only when the 95% interval excludes zero.
- **Latency:** wall time per request, including reading the audio. A warmup request is discarded first.
- **GPU memory:** this process's usage, sampled through NVML every 50 ms.

## Full results, including English

These tables cover all 264 clips, English included. They were the basis of the first, bilingual recommendation and remain the evidence for the language-detection and concurrency findings.

### Accuracy: WER % (language forced, no prompt)

| Set | Model | clean | 10 dB | 5 dB | 0 dB |
|---|---|---|---|---|---|
| FLEURS English (real) | large-v3-turbo | 4.0 | 4.7 | 5.9 | 9.2 |
| | large-v3 | 4.0 | 4.0 | 4.6 | 7.8 |
| FLEURS Tagalog (real) | large-v3-turbo | 12.9 | 13.2 | 15.1 | 20.4 |
| | large-v3 | 13.6 | 14.3 | 16.0 | 20.9 |
| | NCSpeech | 13.9 | 14.3 | 15.6 | 19.0 |
| Commands, English | large-v3-turbo | 2.5 | 2.9 | 3.7 | 6.2 |
| | large-v3 | 4.1 | 4.5 | 4.5 | 6.2 |
| Commands, Tagalog | large-v3-turbo | 7.2 | 7.2 | 8.3 | 16.6 |
| | large-v3 | 6.6 | 6.6 | 7.7 | 7.7 |
| | NCSpeech | 8.3 | 7.7 | 8.8 | 12.2 |
| Commands, Taglish | large-v3-turbo | 11.9 | 10.9 | 11.9 | 15.8 |
| | large-v3 | 9.9 | 10.9 | 9.9 | 11.9 |
| | NCSpeech | 13.9 | 15.8 | 13.9 | 15.8 |
| Batangas places, English | large-v3-turbo | 6.5 | 4.3 | 8.7 | 6.5 |
| | large-v3 | 4.3 | 4.3 | 7.6 | 7.6 |
| Batangas places, Tagalog | large-v3-turbo | 7.8 | 7.8 | 7.8 | 14.4 |
| | large-v3 | 4.4 | 4.4 | 6.7 | 10.0 |
| | NCSpeech | 5.6 | 5.6 | 6.7 | 11.1 |
| Batangas places, Taglish | large-v3-turbo | 13.5 | 13.5 | 14.6 | 23.6 |
| | large-v3 | 13.5 | 13.5 | 15.7 | 18.0 |
| | NCSpeech | 16.9 | 19.1 | 25.8 | 31.5 |

NCSpeech is not run on English. Its overall WER including English is 24–35% and is not meaningful.

Turbo vs large-v3, paired bootstrap (negative = large-v3 better):

| Subset | turbo | large-v3 | Difference [95% CI] | |
|---|---|---|---|---|
| All 1,056 files | 10.0 | 9.7 | −0.3 [−0.7, +0.1] | not significant |
| Clean only | 7.9 | 8.0 | +0.1 [−0.5, +0.7] | not significant |
| 5 dB only | 9.7 | 9.5 | −0.2 [−1.0, +0.6] | not significant |
| 0 dB only | 14.1 | 12.9 | −1.2 [−2.4, −0.2] | **large-v3 better** |
| FLEURS English | 6.0 | 5.1 | −0.9 [−1.4, −0.4] | **large-v3 better** |
| FLEURS Tagalog | 15.4 | 16.2 | +0.8 [+0.1, +1.5] | **turbo better** |
| Commands, Tagalog | 9.8 | 7.2 | −2.6 [−5.0, −0.7] | **large-v3 better** |
| Commands, Taglish | 12.6 | 10.6 | −2.0 [−4.8, +0.3] | not significant |
| Batangas destinations | 10.7 | 9.1 | −1.6 [−3.4, +0.3] | not significant |

NCSpeech vs turbo was not significantly different on FLEURS Tagalog, Tagalog commands, Tagalog destinations or Tagalog at 0 dB. It was significantly worse on Taglish destinations: 23.3% against 16.3%, +7.0 [+2.0, +12.5]. The 13.9% FLEURS Tagalog WER here is higher than the 9.34% on the NCSpeech model card. The card normalises numbers and scores the full test split; this test does neither.

### Location prompt

The prompt is `Destinations in Batangas: ` followed by a list of 40 municipalities and landmarks. The table gives place names recognised as exact / near matches, out of 45 destination clips:

| Model | Prompt | clean | in prompt (30) | not in prompt (15) | 5 dB | 0 dB |
|---|---|---|---|---|---|---|
| large-v3-turbo | none | 28 / 37 | 22 / 26 | 6 / 11 | 27 / 37 | 25 / 34 |
| large-v3-turbo | places | **35 / 41** | **28 / 29** | 7 / 12 | **34 / 41** | **30 / 37** |
| large-v3 | none | 31 / 38 | 24 / 27 | 7 / 11 | 26 / 34 | 24 / 34 |
| large-v3 | places | **36 / 40** | **29 / 29** | 7 / 11 | **36 / 40** | **34 / 38** |
| NCSpeech | (not supported) | 24 / 31 | 19 / 23 | 5 / 8 | 19 / 30 | 16 / 23 |

- **Destination WER:** the prompt lowered it from 10.7 to 8.3 for turbo (−2.4 [−4.1, −0.8]) and from 9.1 to 6.1 for large-v3 (−3.0 [−4.2, −2.0]).
- **Other speech:** across all languages it did no measurable harm. Turbo's FLEURS and command WER were unchanged within noise, and large-v3 even improved slightly overall (−0.6, significant). Restricted to pure Tagalog, turbo's WER rose by 0.5 points, which is significant ([Tagalog results](#tagalog-and-taglish-results)).
- **Places not in the list:** they gain little, because the prompt helps the names it contains. Typical misses are phonetic spellings ("Tyson" for Taysan, "Palocan" for Pallocan), which is why near-matches run 4–9 clips above exact ones. Growing the list toward the full set of destinations the cane can route to is the cheap next step. Whisper's prompt limit is ~224 tokens, so a long gazetteer would need to be the user's own saved places or the nearest towns rather than all of Batangas.

### Language detection

With the language left to Whisper, this was the share of clips detected as each language:

| Model | Speech | clean | 0 dB |
|---|---|---|---|
| large-v3-turbo | English | en 91/120, tl 26/120, other 3 | en 107/120, tl 12/120, other 1 |
| | Tagalog | tl 108/108 | tl 104/108, other 4 |
| | Taglish | tl 36/36 | tl 35/36, other 1 |
| large-v3 | English | en 62/120, tl 54/120, other 4 | en 72/120, tl 46/120, other 2 |
| | Tagalog | tl 108/108 | tl 106/108, other 2 |
| | Taglish | tl 36/36 | tl 36/36 |

Every one of the 120 real US-English FLEURS clips was detected as English by both models. All the English clips labelled Tagalog were the Filipino-accented voices: 29 of 60 for turbo and 58 of 60 for large-v3. Their transcripts were still correct English. Whisper's language ID is following the **accent**, not the language.

For this user population, detection therefore cannot be used to decide which speech is Tagalog and should be offloaded, or to choose the response language: either would misroute English speakers. Auto-detection also cost a small but significant amount of accuracy against forcing the language: +0.3 WER for turbo, +0.4 for large-v3. **Force the language from the user's setting**, as the wearable already does with `language.py`. Taglish is detected as Tagalog, which is correct: Whisper's `tl` mode transcribes the English words in it normally.

### Latency and GPU memory, one request at a time

| Model | Config | median | p95 | max | RTF | VRAM loaded | VRAM peak | Load time |
|---|---|---|---|---|---|---|---|---|
| large-v3-turbo | forced, no prompt | 82 ms | 150 ms | 273 ms | 0.020 | 2.4 GB | 2.7 GB | 1.0 s |
| large-v3-turbo | forced, places | 85 ms | 142 ms | 967 ms | 0.020 | 2.4 GB | 2.7 GB | |
| large-v3-turbo | auto, no prompt | 132 ms | 185 ms | 226 ms | 0.032 | 2.4 GB | 2.6 GB | |
| large-v3 | forced, no prompt | 158 ms | 388 ms | 560 ms | 0.037 | 4.0 GB | 4.4 GB | 1.7 s |
| large-v3 | forced, places | 176 ms | 424 ms | 593 ms | 0.041 | 4.0 GB | 4.6 GB | |
| large-v3 | auto, no prompt | 219 ms | 439 ms | 616 ms | 0.051 | 4.0 GB | 4.4 GB | |
| NCSpeech | RNNT | 35 ms | 62 ms | 135 ms | 0.008 | 1.4 GB | 1.6 GB | 2.5 s |

Auto-detection adds ~50 ms because it runs an extra pass over the audio, which is one more reason to force the language. The real-time factor is processing time ÷ audio length, so 0.02 means a 4 s command takes 80 ms.

### Concurrent requests

One model instance with CTranslate2 `num_workers = K`, K clients sending all 264 clips at 5 dB as fast as they could:

| Model | K | requests/s | audio s per s | median | p95 | max | VRAM peak |
|---|---|---|---|---|---|---|---|
| large-v3-turbo | 1 | 10.2 | 66 | 82 ms | 148 ms | 187 ms | 2.6 GB |
| | 2 | 12.1 | 79 | 138 ms | 268 ms | 388 ms | 2.9 GB |
| | 4 | 12.6 | 82 | 275 ms | 534 ms | 777 ms | 3.3 GB |
| | 8 | 12.7 | 83 | 548 ms | 1.11 s | 1.73 s | 4.2 GB |
| large-v3 | 1 | 4.9 | 32 | 160 ms | 376 ms | 533 ms | 4.4 GB |
| | 2 | 6.5 | 42 | 233 ms | 563 ms | 822 ms | 4.9 GB |
| | 4 | 7.3 | 47 | 428 ms | 1.06 s | 1.45 s | 5.8 GB |
| | 8 | 7.2 | 47 | 863 ms | 2.12 s | 4.05 s | 7.5 GB |

Throughput stops growing at about K = 4. Beyond that, extra concurrent requests only queue: latency doubles while throughput stays flat. One turbo instance with `num_workers=2` sustains ~12 commands/s at under 300 ms p95. That is far more than a fleet of canes generates, since each sends one short command at a time. Both models fit beside the existing TTS service and the OCR container (17 GB when awake) with room to spare.

## Licences and compatibility

All were checked before installation. None has per-request fees.

| Component | Licence |
|---|---|
| `openai/whisper-large-v3-turbo` | MIT |
| `openai/whisper-large-v3` | Apache-2.0 (per its model card) |
| `NCSpeech/stt_tl_fastconformer_hybrid_large` | CC-BY-4.0: commercial use allowed with attribution |
| faster-whisper, CTranslate2 | MIT |
| NeMo | Apache-2.0 |
| FLEURS, DEMAND (test data only) | CC-BY-4.0 |

The driver is 580.178 and reports CUDA 13.0, which runs CUDA 12 builds. CTranslate2 4.8.2 is built against CUDA 12 and cuDNN 9; the host has CUDA 12.9 (`libcublas.so.12`) and cuDNN 9.25. CTranslate2 found the GPU and supports float16, bfloat16 and int8 on it. NeMo ran on its own `torch 2.11.0+cu128` (cuDNN 9.19).

## Where it lives on gpuer

The deployed API and the evaluation live in separate directories. Neither touched an existing service.

| Path | Contents |
|---|---|
| `~/stt/server.py` | the API (FastAPI) |
| `~/stt/.venv` | faster-whisper 1.2.1, CTranslate2 4.8.2, PyAV 15.1 (pinned `<16`: faster-whisper 1.2.1 passes an argument PyAV 19 removed, and decoding failed) |
| `~/stt/models/whisper-large-v3-turbo-ct2` | the served model (1.6 GB) |
| `stt-api.service` | uvicorn on `127.0.0.1:8711`, `HF_HUB_OFFLINE=1` |
| nginx site `stt-api` | TLS on `:8710` with the existing `gpuer.techco.fi` Let's Encrypt certificate |

```bash
ssh gpuer 'sudo systemctl restart stt-api && journalctl -u stt-api -f'
```

The evaluation is in `~/stt-eval`:

| Path | Contents |
|---|---|
| `.venv-whisper` | faster-whisper, CTranslate2, CPU-only torch (used only for model conversion) |
| `.venv-nemo` | NeMo + CUDA torch, for NCSpeech only (7.9 GB) |
| `models/` | `ct2-whisper-large-v3` (2.9 GB), the `.nemo` file (0.46 GB), and a symlink to the served turbo model in `~/stt/models` |
| `data/corpus/` | the 1,056 test files and `manifest.jsonl` (references, languages, place names) |
| `results/` | per-clip transcripts for every run, `*.meta.json`, concurrency results, `compare.md` |
| `build_corpus.py`, `destinations.py`, `common.py`, `run_whisper.py`, `run_nemo.py`, `concurrency.py`, `score.py`, `bootstrap.py`, `compare.py`, `tagalog_only.py` | the evaluation scripts |

The disk on gpuer is at 12 GB free after this work. The NeMo environment is the largest removable item if NCSpeech is not pursued.
