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

## Measured latency

Measured end to end from a laptop over the internet, one request at a time, for a ~4–8 s sentence:

| Model | Request time |
|---|---|
| `omnivoice` | ~2.5 s |
| `moss` (Tagalog) | ~5.7 s |
| `moss` (English, short) | ~2.7 s |

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
