# Remote TTS API (gpuer)

Two TTS models run on the `gpuer` server (RTX 6000 Ada, 48 GB) and are exposed publicly over HTTPS:

| `model` | Checkpoint | Notes |
|---|---|---|
| `omnivoice` (default) | [`mazodan/Omnivoice-filipino-RSLoRA-Merged`](https://huggingface.co/mazodan/Omnivoice-filipino-RSLoRA-Merged) | OmniVoice fine-tuned on Tagalog/Filipino speech. Fast. |
| `moss` | [`OpenMOSS-Team/MOSS-TTS-v1.5`](https://huggingface.co/OpenMOSS-Team/MOSS-TTS-v1.5) | 8B, 31 languages including Tagalog. Takes a `language` tag. |

The endpoint is **public with no authentication**, so anyone who knows the URL can use the GPU.

## Endpoint

```
https://gpuer.techco.fi:8700
```

### `POST /tts`

JSON body:

| Field | Type | Default | Meaning |
|---|---|---|---|
| `text` | string, 1–2000 chars | required | Text to speak |
| `model` | `"omnivoice"` \| `"moss"` | `"omnivoice"` | Which model synthesises |
| `language` | string | `"Tagalog"` | MOSS only: language name, e.g. `Tagalog`, `English`. Ignored by OmniVoice |

Returns `audio/wav`: 16-bit mono PCM, 24 kHz. An invalid body gives `422`; a synthesis failure gives `500`.

```bash
curl -X POST https://gpuer.techco.fi:8700/tts -H 'Content-Type: application/json' -d '{"text":"Magandang umaga po. Mag-ingat po kayo, may hagdan sa harap.","model":"omnivoice"}' -o out.wav
```

```bash
curl -X POST https://gpuer.techco.fi:8700/tts -H 'Content-Type: application/json' -d '{"text":"Careful, there are stairs ahead.","model":"moss","language":"English"}' -o out.wav
```

### `GET /health`

Returns `{"status":"ok","models":["moss","omnivoice"]}` once both models are loaded.

## Benchmark: which model is faster

**OmniVoice is faster: about 2.75× on the median, and on every single sentence tested (90 of 90).** MOSS also produced one runaway generation in an earlier run. OmniVoice never did.

The benchmark is in the repo, so these numbers can be reproduced:

```bash
python -m indepensense.voice.tests.manual.tts_api_bench --csv
```

Run on 2026-10-12, from a laptop in Finland over the public endpoint, with the script's defaults.

### Method

- **Corpus:** the wearable's own static responses from `intents/messages.py`, the sentences it actually speaks. 15 English and 15 Tagalog, sampled with seed 0, mean length 51 and 54 characters.
- **Repeats:** each sentence was sent 3 times to each model, so n = 45 per model per language.
- **Order:** the two models alternate on every sentence, and the order flips each repeat. Any drift, such as load from other tenants on the GPU, therefore hits both equally.
- **Warmup:** one warmup request per model is sent first and discarded.
- **Stats:** computed with `summarise` from `voice/tests/manual/latency_bench.py`, the same median/p95 code as the on-device benchmark.
- **Request time:** full HTTPS round trip, including network. The network alone (`GET /health`) had a median of 0.22 s, the same for both models.
- **Real-time factor:** request time ÷ length of the returned audio. Below 1× means the clip is generated faster than it plays back.

### Results

| Language | Model | Request median | Request p95 | Request max | Audio median | RTF median | RTF p95 |
|---|---|---|---|---|---|---|---|
| English | `omnivoice` | **0.93 s** | 1.37 s | 1.42 s | 2.92 s | **0.32×** | 0.55× |
| English | `moss` | 2.69 s | 4.43 s | 4.85 s | 2.96 s | 0.92× | 1.80× |
| Tagalog | `omnivoice` | **0.92 s** | 1.61 s | 3.45 s | 3.12 s | **0.33×** | 0.67× |
| Tagalog | `moss` | 2.82 s | 5.07 s | 5.94 s | 3.44 s | 0.83× | 1.66× |

Paired per sentence and repeat, OmniVoice was faster in all 45 of 45 English and all 45 of 45 Tagalog cases. The median MOSS/OmniVoice time ratio was 2.76× in English and 2.75× in Tagalog.

**OmniVoice stays below real time even at p95. MOSS goes above it at p95:** its p95 RTF is 1.7–1.8×, so a long sentence can take nearly twice its spoken length to arrive. That is the difference between a cue that arrives before it is needed and one that arrives late.

**MOSS can fail to stop.** An earlier run of the same benchmark, with a slightly different Tagalog sample, gave the same ranking (2.5–2.65× median). In that run, on one of its three repeats of "I can't change the volume right now.", MOSS produced 101.5 s of audio and took 42 s to answer. The other two repeats of the same sentence were normal. MOSS is an autoregressive 8B model with `max_new_tokens=4096`, and it occasionally misses its end-of-speech token. One case in 180 requests is too few to give a rate, but it is a failure mode OmniVoice did not show in either run.

These numbers measure speed only. No listening test has been done, so they say nothing about which voice sounds better in Tagalog.

## Deployment on gpuer

| What | Where |
|---|---|
| Server code | `~/tts/server.py` (FastAPI, both models resident on the GPU, one lock per model) |
| Python env | `~/tts/.venv` (torch 2.9.1+cu128, transformers ≥5.3, `omnivoice`) |
| Weights | `~/tts/models/{moss-tts-v1.5,moss-audio-tokenizer,omnivoice-fil}` |
| Service | `tts-api.service`: uvicorn on `127.0.0.1:8701`, `HF_HUB_OFFLINE=1` |
| Public proxy | nginx site `tts-api`: TLS on `:8700` with the existing `gpuer.techco.fi` Let's Encrypt certificate |

The two models share one venv because the disk had no room for a second torch install. OmniVoice requires transformers ≥5.3. On that version, `AutoProcessor` passes a `revision` argument into MOSS's bundled processor code, which rejects it. The server therefore loads `MossTTSDelayProcessor` directly with `get_class_from_dynamic_module` rather than patching the downloaded files.

```bash
ssh gpuer 'sudo systemctl restart tts-api && journalctl -u tts-api -f'
```
