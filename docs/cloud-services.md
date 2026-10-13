# Cloud services, and what happens without them

Three stages of the voice pipeline can run off-device. Each has a local
fallback, and the device degrades rather than failing: with no network
at all it still hears, classifies and speaks, only slower and less
accurately.

| stage | remote | local fallback | languages sent |
|---|---|---|---|
| speech-to-text | Whisper large-v3-turbo on `gpuer` | faster-whisper `tiny`/`small` | Tagalog only |
| intent parsing | `mistral-small-2603` | Qwen 3 1.7B via Ollama | both |
| speech synthesis | OmniVoice Filipino on `gpuer` | Piper (en) / MMS (tl) | Tagalog only |
| open questions | `mistral-small-2603` | none — says it needs internet | both |

Switches: `REMOTE_STT_ENABLED`, `NLU_CLOUD_ENABLED`, `REMOTE_TTS_ENABLED`,
`CLOUD_LLM_ENABLED`. Each off returns the device to the purely local
behaviour it had before.

## Why Tagalog and not English

Both speech exceptions are bounded to the one language whose local
quality was the measured problem. That keeps English audio on the device
entirely and is a far easier position to defend than moving speech
wholesale. Measured on the Pi with `latency_bench`, 2026-10-12:

```
STT   en, Whisper tiny     1.13 s
STT   tl, Whisper small    5.29 s    real-time factor 2.23x
TTS   en, Piper            0.07-0.30 s
TTS   tl, MMS              2.23 s
```

Tagalog transcription is slower than the speech it transcribes — a five
second command costs about eleven — and `config.WHISPER_MODELS` already
records that `tiny` and `base` were too mangled to use for it at all.

## What the cloud is actually buying

**Intent parsing: accuracy.** Measured over the modem on the same 226
`llm_probe` cases:

```
                    combined   english   tagalog   adversarial
local Qwen 1.7B        82.3%     88.8%     85.1%       66.7%
cloud, shared prompt   92.5%     89.8%     93.2%       96.3%
cloud, own prompt      98.7%     99.0%    100.0%      100.0%
```

The gap is concentrated in the adversarial group, which is the set where
a misclassification acts on the user rather than merely annoying them.
It is also ~6x faster: 0.76 s against a local 4.80 s first-exposure
median.

**Speech-to-text: both.** 0.72 s median over cellular against 5.29 s.

**Speech synthesis: pronunciation only.** Cloud TTS is *not* faster than
local MMS over cellular — 1.6-3.4 s against 2.23 s is a wash. Its value
is that the Filipino fine-tune sounds markedly better, which is why
`tools/render_messages.py` renders the static catalogue ahead of time.
A pre-rendered clip costs a file read forever after, so only the 35
templated messages with open slots ever reach the network at runtime.

## Measured latency over the SIM7600

Everything below is `wwan0`, not bench WiFi. Both interfaces hold a
default route and `wlan0` wins on metric, so an unbound measurement is
not the field case — `llm_probe --modem` exists for this reason.

```
NLU   p50 0.76 s   worst 1.55 s    0 of 226 over the 2.5 s deadline
STT   p50 0.72 s   p95   1.23 s    server processing 0.10-0.12 s
TTS   warm 1.33-1.84 s for a ~100 KB reply, 4.22 s cold for ~152 KB
```

Deadlines are split into a connect and a read budget, because `requests`
applies a scalar timeout to each phase independently rather than to
total elapsed time — one number would mean double the ceiling the config
appears to set.

| path | connect | read | ceiling | then |
|---|---|---|---|---|
| STT | 2 s | 4 s | 6 s | local Whisper, 5.29 s |
| NLU | 2 s | 2.5 s | 4.5 s | Ollama, ~4.8 s |
| TTS runtime | 2 s | 6 s | 8 s | local MMS, 2.23 s |
| TTS render | 2 s | 120 s | — | batch tool, nobody waiting |

## Data

Per escalated utterance, measured:

```
NLU   11.3 KB up,  1.8 KB down    (prompt cache 96-97%, so prefill is near-free)
STT    5-13 KB up,  <1 KB down    (Opus; the same clip is 46 KB as WAV)
TTS   ~100 bytes up, 100-152 KB down
```

STT reverses the direction that matters: the audio *is* the request, and
uplink is the modem's weaker side, so clips are transcoded to Opus
first — 8.4x smaller, 94 ms to encode. It falls back to sending WAV where
`libsndfile` cannot write Opus, since losing the compression is a cost
and must not cost the user their command.

Prompt caching makes NLU cheap but not small: the system prompt is still
uploaded every call, so prompt size is a bandwidth question rather than a
latency one.

## Offline

See architecture decision 10 in `CLAUDE.md` for the full reasoning. The
short version is that the thing which breaks offline is DNS, not the
network timeouts: `socket.create_connection` resolves before it applies
any timeout, measured at **20 s per lookup** on a blackholed link, three
lookups per command.

Three mechanisms cover it, and every path out must pass all three:

- `net.has_network_route()` — no packets, ~0.2 ms, catches *no route at
  all*. No cooldown, so a reconnect is used on the very next command.
- `net.HostBreaker` — remembers the first failure, skips that host for
  30 s. Per host, so a Mistral outage does not stop the device using its
  own server. Opens on a connection error, a read timeout, a 429 and
  other 4xx; **not** on 5xx or a malformed body, where the host answered
  quickly and the next utterance may well succeed.
  `net.breaker_reason_for` is the one policy all four drivers share.

  It also records *why*, because `intents/cloud.py` turns that into a
  spoken sentence. `cloud.offline` says "I need an internet connection",
  which a blind user answers by walking somewhere else to find signal,
  and the answerer shares a breaker with the intent parser — same host.
  So only `UNREACHABLE` is spoken as offline; a rate limit, a rejected
  key or a slow reply are `cloud.error` instead. A message the user acts
  on has to be true.
- `RES_OPTIONS=timeout:1 attempts:1` in `indepensense.service` — bounds
  the lookup to 2 s. In the unit rather than `/etc/resolv.conf`, which
  Tailscale owns and rewrites.

**A wobbling modem is the realistic failure, and it is the harder one.**
Pulling a SIM makes ModemManager tear the bearer down and the default
route disappears, which the route check sees instantly. A carrier drop
often leaves the bearer up and the route in place while packets vanish —
so the route check says yes and the breaker plus the DNS bound are what
actually protect the user.

## The endpoints

```
TTS   https://gpuer.techco.fi:8700/tts     see docs/tts-api.md
STT   https://gpuer.techco.fi:8710/stt
NLU   https://api.mistral.ai/v1/chat/completions
```

`gpuer` is an RTX 6000 Ada under the project's control, which is why
sending audio there is a different proposition from sending it to a
third party: no external processor, and the recordings stay in hand.

**Neither `gpuer` endpoint requires authentication.** For TTS the request
body is text the device is about to say out loud anyway. For STT it is a
recording of a blind user's voice, and that deserves a token before this
runs anywhere but a test bench. Recorded here because it belongs in the
ethics chapter either way.

Mistral's key comes from `INDEPENSENSE_CLOUD_API_KEY` in the
environment, never a committed file, and `NLU_CLOUD_MODEL` is pinned to
a dated ID rather than `-latest` so a thesis figure stays reproducible.
