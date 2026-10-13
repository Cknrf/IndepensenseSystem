# IndepenSense — Working Agreement

How Claude collaborates on this thesis project.

`README.md` is the reference manual — architecture, hardware list, the full catalogue of manual test commands, first-boot checklist, troubleshooting. Read it for *what the system is*. **This file is how we work on it**, plus the conventions that aren't obvious from reading any single source file.

## Context

- **Thesis project.** Every decision must be defensible in writing and in the viva. Always explain *why*, not just *what*.
- **Single developer, tight timeline.** Prefer the simplest credible option that meets the requirement.
- **Develop on macOS, deploy to a Raspberry Pi 5** (Raspberry Pi OS Trixie, Python 3.13). The whole system must stay runnable on a Mac through mocks — that is what keeps iteration fast.
- The backend and guardian dashboard live in a **separate repository**. Out of scope here.

## How Claude should behave

- **Ask before structural changes.** Propose, explain the tradeoff, wait for approval. The user defends every decision in their thesis.
- **Explain tradeoffs, not just conclusions.** Name the alternative and why it was rejected.
- **No silent abstractions.** Don't introduce a class, layer, or interface unless asked or until it has earned its place. YAGNI.
- **Explain concepts when asked.** "What is X?" is a real learning question — answer with the concept, why it exists, and a concrete example. Don't be patronizing.
- **Hardware-aware suggestions.** Anything sensor-touching needs a mock, or must be guarded so the module still imports on a Mac.
- **No backwards-compat hacks.** Greenfield project. Delete cleanly; leave no commented-out code or unused stubs.
- **Say when something is untested on hardware.** Most code can only be truly verified on the Pi. Be explicit about what was verified by unit test versus what still needs a manual test on the device.

## Architecture decisions in force

1. **Concurrency: one synchronous main loop plus a fixed, named set of background threads.**
   The main thread does cheap sensor reads only — 100 Hz MPU6050 → fall detector, both DYP-A22 ultrasonics, obstacle warnings. Everything that blocks (network, LLM, STT/TTS, warning-pattern playback) runs off it:
   voice thread (one per PTT press), gpiozero button callbacks, per-event warning-pattern threads under a mutex, heartbeat sender, telemetry retry worker, the 1 Hz GPS cache thread, and the **announcer** — one long-lived worker owning every piece of speech that originates on the main loop.
   The rule is **never block the main loop**, not "never use threads". Adding a *new* long-lived thread is a structural change — propose it first. No asyncio; the thread set is small and each one has a single clear job. See the module docstring at the top of `app.py` for the authoritative description.

   **Startup is safety first.** `start()` opens only what fall detection, obstacle warnings and the emergency alert need — IMU, ultrasonics, buttons, motors, the telemetry and SMS path — and returns in a few seconds; the loop is running while the one-shot `voice-stack` thread loads Whisper, TTS, the parser and the vision stack, then warms the LLM and speaks the greeting. The models took ~200 s to load from the SD card and every second of it used to sit in front of the safety features, none of which needs a model. Consequences to keep: a PTT press before the stack is ready answers with the busy cue; the announcer exists from the first second with no voice and holds a cache miss until TTS is attached, so static messages must stay pre-rendered; and a model that fails to load still fails the process — the loader records the error, stops the loop, and `run_app` exits non-zero — because the `_open_*` contract did not move with the thread.

   The deploy side mirrors it: `indepensense.service` is `Type=notify` and reports started when the voice stack is loaded, GraphHopper and Photon are ordered after it so their graph and index stay off the SD card while the models load, and `ollama-warmup.service` runs `tools/warm_nlu.py`, which sends the parser's own warmup request so the system-prompt prefix Ollama caches is the one every query reuses. Measurements and the reasoning are in `deploy/systemd/README.md`; a change to the warmup request belongs in `OllamaIntentParser`, never in the unit.

   **Anything the main loop wants to say goes through `_announce()`.** It appends and returns. Navigation cues used to synthesise and play inline, which stopped fall detection and obstacle polling for ~3–4 s during every turn instruction — the loop sat inside `sd.play(blocking=True)`. Motor and buzzer patterns are the same hazard for a smaller amount: every driver's `pulse`/`beep` sleeps for the pattern's duration, so they go through `_spawn_haptic()`. Neither may be called inline from `run()`.

   **The vibration motors signal intensity, never direction.** All three are mounted in the one cane handle and their vibration couples through its shell, so whichever fires, the hand feels the same buzz — "left motor" and "right motor" are indistinguishable to the wearer. Navigation used to encode turn direction that way; it was a property of the wiring diagram, not a perception, and every navigation cue is now speech. What the device has is one vibrator with three intensity steps, which is exactly what obstacle proximity needs (front alone for warning, all three for danger, rate carrying distance). Don't reach for the motors to express a side — the honest fix is a motor mounted off the handle, which is a build change.

   Two sub-steps run on the **voice thread** and block only it: destination confirmation and turn-to-face orientation. Both are bounded, both abort on an emergency press, and both borrow the PTT button and hand it back in a `finally`. Orientation is also the one place that speaks with `_play_clip` rather than `_announce`: it repeats the same instruction while the thing it describes is changing, and a queue would have the user hearing "face left" seconds after they finished turning. Its verb is *face*, never *turn* — `nav.started` ends with the route's first turn and orientation speaks on its heels, so sharing the wording put two different lefts back to back. While orientation was a motor pulse the modality kept them apart for free; in one audio channel the vocabulary has to.

   **`_voice_cancel` means "abandon this voice cycle", and two buttons set it** — emergency, and repeat used as stop. Every pipeline stage checks it. One event rather than two because every stage wants the same answer; `_voice_cancel_reason` carries the *why* for the log alone, and is always assigned before the event is set so a thread observing the event observes a current reason.

   **Every `sounddevice` stream is owned by the function that created it, and nothing else closes it.** `voice/audio.py` never calls the module-level `sd.play`, `sd.rec` or `sd.stop` — those route through one global context that `sd.play` *closes* on entry, so a PTT chime on gpiozero's callback thread closed the announcer's live stream and the announcer then closed it again. That is a double free in C: the process aborted with `double free or corruption (out)` and no Python traceback. Playback is serialised by a lock in `audio.py`, and `stop_playback()` sets a flag the *playing* thread reads rather than calling into PortAudio from outside. A lock alone would not do — stopping has to interrupt the thread holding it.

2. **Hardware abstraction.** Every device has a `Protocol` interface in its module's `base.py`, a real driver (e.g. `dyp_a22.py`), and a mock (`mock.py`). Application code depends on the protocol, never the concrete driver.

   In `app.py` this is enforced by a single rule: **every device is constructed in an `_open_*` / `_try_open_*` factory method and nowhere else.** `start()` calls the factories but never a driver constructor. That is what lets `app_mock.py` subclass `App`, override only the factories, and run the whole runtime on a Mac with the loop, threads and decision logic inherited untouched. Add a device, add a factory — an inline constructor in `start()` silently drops it out of mock coverage.

   `_open_*` means the runtime cannot function without it and failure aborts startup (IMU, STT, TTS, NLU parser). `_try_open_*` means degraded operation is acceptable — it logs, returns `None`, and every caller handles `None`.

   `app_mock.py` is development-only and never imported by production: `deploy/systemd/indepensense.service` starts `indepensense.app`. The separation is structural, not a runtime flag, so a misconfigured flag can never substitute a fake sensor on the real device.

3. **Pi-only libraries are imported lazily, inside the function that needs them.** `serial`, `smbus2`, `gpiozero`, `picamera2`, `ultralytics`, `pytesseract`, `faster_whisper`, `piper`, `transformers`, `torch`, `sentence_transformers` — never at module top level. This is what lets the real drivers be imported, introspected, and unit-tested on a Mac where those packages don't exist. Follow the existing comment style:
   ```python
   import serial  # lazy: only resolvable on the Pi
   ```

   **Models load from directories under `models/`, laid out once by `tools/fetch_models.py`. Nothing resolves a Hugging Face repo id at runtime.** Whisper and the embedding model used to be handed a name and let their libraries resolve it, which asks the Hub for the current revision before touching the local copy — measured at ~8 s per boot for the embedding model alone, and a wait for the timeout on a boot with no network. A directory path is loaded as is, so startup is the same with the modem up, down or absent, and the weights in use are the ones that were tested. The cost is that a model never fetched is a startup error naming the tool rather than a download, which is the right failure for a device that must come up in the field.

4. **Drivers own protocol knowledge.** Parsing, checksums, register maps, and unit conversion live in the driver, not in tests or callers. Tests verify the driver; callers consume clean values. Document register addresses and datasheet sections in the driver's docstring, as `mpu6050.py` does.

5. **`config.py` owns what varies; drivers own what's fixed.** Ports, pins, I²C addresses, thresholds, intervals, model paths → `config.py`. Constants dictated by the chip itself (frame layout, header byte, checksum formula) stay in the driver — those are the chip's contract, not configuration.

6. **No user-facing text in Python.** Every spoken response lives in `intents/messages.py`, keyed by message then language; the executor only calls `messages.get(key, language)`. The active language is runtime state (`language.py`), shared by reference so a switch is visible to everything immediately — not a constant, and not a value copied at construction.

   Adding a response means adding every language's version. Unit tests enforce full coverage and matching placeholders, so a missing translation is a test failure rather than the wearable saying the wrong thing to the one user who speaks that language.

   **Numbers are spelled out automatically — pass the number, not a string.** `messages.get()` routes any `int`/`float` field through `speak_number`, because digits are effectively untrained in the MMS Tagalog voice and a bare "15" reaches the speaker garbled or missing. That was found late: every battery percentage, volume level, satellite count and signal strength had been dropping its number in Tagalog while reading perfectly in English. Pre-formatting a number into a string bypasses this, so don't — and note the Tagalog numeral brings a linker with it (`apat na`), which has to attach to a noun the English template may not need.

   **Speech is rendered once and replayed, not synthesised per utterance.** Clips are named after a hash of their text, so reuse is automatic and editing a message invalidates its recording — see `voice/clips.py`. Static messages (no placeholder) live in a permanent directory built by `tools/render_messages.py`; everything templated lands in a swept cache. Adding a message needs no wiring: the announcer hashes finished text and the split falls out. The tool only front-loads the work — a static message synthesised on demand is written to the permanent directory too, so the never-evicted set is self-healing rather than dependent on a deploy step being remembered. Two rules hold it together — **nothing may depend on a clip existing** (missing ones synthesise on demand; the only exceptions are `_BOOT_CLIPS`, which play before TTS loads), and **the sweep never touches the permanent directory**, because the least-spoken static messages are the emergency-delivery failures and those are needed at the one moment there is no time to synthesise them.

   `clips.sweep` is also pointed at `VOICE_TEST_DIR`, which holds one push-to-talk recording per utterance and used to grow without limit. Kept rather than deleted after transcription because `latency_bench` replays them for the thesis's timings; capped because indefinite retention of a blind user's recorded speech on a losable device is not a defensible default. The rule that admits both directories is the one above, restated: never point the sweep at the *permanent message* directory. See `config.VOICE_RECORDING_MAX_BYTES`.

   Sentence *structure* may differ per language, not just wording — Tagalog does not inflect nouns for number, so scene description branches per language rather than sharing a pluraliser. Put that kind of grammar in `messages.py`, not in the handler.

7. **Intent parsing is three-stage, and the first split is static.**
   `TieredIntentParser` runs an embedding matcher before the LLM. What the fast path may answer is decided by the *intent*, not by confidence: an embedding is one vector per utterance, so it can name an intent but never extract a span from it. Intents with a free-text parameter always escalate; intents with none, or with a closed enum foldable into the label, are answerable. The fast path never returns `unknown` — that is the cloud answerer's trigger and stays with the LLM.

   Adding an intent means deciding which side it falls on. `parse_bank` enforces it: an open-span intent given its own section in `prompts/nlu_examples.md` fails on load rather than silently becoming answerable.

   Behind the matcher sits `FallbackIntentParser(cloud, local)`: Mistral first, Ollama when the cloud fails. Measured on the same 226 `llm_probe` cases, cloud scored **98.7% against local's 82.3%**, and the gap is concentrated where it matters — the adversarial group went from 66.7% to 100%, which is the set where a misclassification acts rather than merely annoys. The fast path still answers ~52% locally in ~30 ms, so only the escalated remainder ever reaches the network.

   **The handover trigger is `IntentResult.failure`, never a bare `unknown`.** A clean `unknown` is a decline and must pass through to the cloud *answerer*; falling back on it would spend a local inference re-answering a correct answer, and the local model's much lower `unknown` recall would often turn a genuine question into a bogus intent.

   **The two prompts are separate on purpose.** `nlu_system.md` tells the classifier five times to answer `unknown` when unsure, which Qwen 1.7B needs and the cloud model does not: 15 of its 17 first-run failures were `unknown` on utterances it plainly understood. `nlu_system_cloud.md` replaces that blanket bias with a targeted one, keeping caution for `system.shutdown`, `guardian.status_ok`, `place.delete` and a *missed* `emergency.trigger`. A larger model obeys a deferral instruction better, not worse, so this is not fixed by paying for one. Editing either means re-running `llm_probe`, and **prompt edits are not monotonic** — one "fix" during tuning repaired a case and broke two, dropping the adversarial group from 100% to 96.3%.

8. **Tagalog is served from the cloud; English is not.**
   Both exceptions are bounded to the one language whose local quality was the measured problem, which is a far easier thing to defend than moving speech wholesale — and it keeps English audio on the device entirely.

   Measured on the Pi with `latency_bench`: English STT is 1.13 s on Whisper `tiny`, Tagalog is **5.29 s on `small`, a real-time factor of 2.23x** — slower than the speech it transcribes — and `WHISPER_MODELS` already records that `tiny` and `base` were unusable for Tagalog. English TTS through Piper is 0.07–0.30 s; Tagalog through MMS is 2.23 s and sounds markedly worse than the Filipino fine-tune on the server.

   **The local models stay resident and are not optional.** They are the fallback, and unlike intent parsing nothing sits beneath STT — no transcript means nothing downstream runs, voice-triggered emergency included.

   **Cloud TTS is not faster than local MMS over cellular** (1.6–3.4 s against 2.23 s). Its value is pronunciation, which is why `tools/render_messages.py` renders the static catalogue ahead of time: a clip costs a file read forever after, so only the 35 templated messages with open slots ever reach the network.

9. **A clip's identity includes the voice that produced it.**
   `clips.digest` hashes voice, language and text. Without the voice, two engines speaking one language share a filename: re-rendering with a different Tagalog voice overwrote the old clips, anything the *other* engine synthesised at runtime landed on the same names, and the user heard the voice change mid-session between a pre-rendered static message and a templated one. It also meant changing voice invalidated nothing, where editing a message's text always had.

   The identity comes from `router.voice_id`, which lives beside `build_tts` and mirrors its precedence because the two must agree — a name the router would not use files every clip under the wrong voice.

   **The fallback therefore lives where naming is decided, not inside a `TTSEngine`.** `clips.render` names the file before calling the engine, so a wrapper that quietly substituted MMS would write its audio under the remote voice's name; the next lookup would find it and never try the remote engine again. `clips.render_first` takes `(engine, voice)` pairs and files each result under the voice that produced it; `clips.find_any` searches the chain in preference order, because a clip rendered locally during an outage is still a clip.

10. **Offline is a first-class state, and the thing that breaks it is DNS.**
   `socket.create_connection` resolves the hostname *before* it applies any timeout, so none of the app's deadlines cover name resolution. On a link that blackholes packets — what a wobbling modem leaves behind, since the bearer often stays up and the default route lingers — the resolver never answers. Measured on the device: **20 s per lookup**, three lookups per voice command.

   Three mechanisms, each covering a different shape:
   - `net.has_network_route()` — a UDP `connect()` that sends no packets and answers in ~0.2 ms. Catches *no route at all*. No cooldown, so a reconnect is picked up on the very next command.
   - `net.HostBreaker` — remembers the first failure and skips that host for 30 s, turning "every command unusable" into "one slow command, then local". Keyed per host, so a Mistral outage does not stop the device using its own server.

     **What opens it is "this endpoint wasted the user's time, or told us to stop" — not "the request failed".** That is a revision: it was *unreachability only* until a 429 or a slow reply proved that too narrow. `net.breaker_reason_for` is the single policy all four cloud drivers share, and it opens on a connection error, a read timeout (the most expensive failure there is — the caller waits out the whole budget first), a 429, and other 4xx. It does **not** open on 5xx or on a reply whose body is malformed: the host answered quickly, the next utterance may well succeed, and one wasted round trip is cheaper than 30 s on a local model scoring 82.3% against the cloud's 98.7%. `requests.exceptions.JSONDecodeError` subclasses *both* `RequestException` and `ValueError`, so the order of those checks is what keeps a junk body out of the transport bucket.

     **The breaker records *why*, because one caller speaks it aloud.** `cloud.offline` says "I need an internet connection", and a blind user answers that by walking somewhere else to find signal. Since `CLOUD_LLM_PROBE_URL` is `CLOUD_LLM_URL`, the answerer shares a breaker with the intent parser — so most of what opens it is a failed *classification*, and under the rule above most of those are not connectivity failures at all. Only `UNREACHABLE` becomes "offline"; backoff, a rejected key and a slow reply become `cloud.error`. A message the user acts on has to be true.
   - `RES_OPTIONS=timeout:1 attempts:1` in `indepensense.service` — bounds the lookup itself to 2 s. In the unit rather than `/etc/resolv.conf`, which Tailscale owns and rewrites.

   Every path out must pass all three. `probe_reachable` bypassed them once and the cost landed on the least-watched path: a local `unknown` sends the utterance to the cloud answerer, so an offline user waited out a full stall to be told there was no internet.

11. **Tests nested per module:**
   - `src/indepensense/<module>/tests/unit/` — pytest, no hardware, must pass on a Mac
   - `src/indepensense/<module>/tests/manual/` — human-run scripts that need real hardware

   Runtime-wide code that belongs to no single domain (`app.py`, `language.py`, `net.py`) is tested in `src/indepensense/tests/unit/`.

   A new hardware component isn't done until it has a manual test, and that test is listed in the README's Manual Verification Tests table. The fabricator uses those commands to verify wiring without writing Python.

   **Unit tests never touch the network.** Modules whose code makes HTTP calls stub `requests` with an autouse fixture — otherwise the suite passes or fails depending on whether the dev machine is online, and stalls for the timeout when it isn't.

   **Nor the clock.** Retry backoff is a module constant or a constructor argument, never a literal inside the loop, and tests stub it to zero with an autouse fixture. A test that sleeps through a real backoff spends seconds asserting what a call counter already knows: four `test_auth` cases sat at 3.5 s each proving a 404 is *not* retried, and the suite went from 22 s to 52 s the day retries landed. Same objection as the network, different clock.

## Where things live

```
src/indepensense/
├── app.py       # the runtime: wires everything together, owns the loop and threads
├── config.py    # every tunable: pins, addresses, thresholds, intervals, model paths
├── <domain>/    # base.py (Protocol) + real driver(s) + mock.py + tests/{unit,manual}/
└── tools/       # standalone utilities (e.g. system_performance)
```

Domains: `sensors`, `vision`, `voice`, `intents`, `navigation`, `routing`, `feedback`, `safety`, `power`, `telemetry`. The README's Codebase Overview table says what each one does.

Outside `src/`:

- `prompts/nlu_system.md` — the LLM intent-classification system prompt. **Prompt changes go here, not into Python.** Loaded via `config.NLU_PROMPT_PATH`. After editing it, re-run the probe: `llm_probe` exercises 226 prompts across English, Tagalog and adversarial groups, reported per group — a blended score would hide a model that aces English and fails Tagalog.
- `prompts/nlu_examples.md` — the labelled example bank for the embedding fast path. Same discipline as the system prompt: **content goes here, not into Python.** Loaded via `config.NLU_EMBEDDING_BANK_PATH`. Section headings are class labels and are validated on load, so a typo fails loudly instead of silently shrinking the bank. After editing it, re-run `embedding_probe` — and `--check-overlap` first, because the held-out test set lives in `llm_probe` and a copied phrasing turns the accuracy number into memorisation.

  **Adding examples is not monotonic.** The gate is score *and* margin, and margin is the gap to the nearest example of a *different* class — so a new row raises its own class while lowering its neighbours'. One carrier-phrase addition to `system.help` silently broke a working `system.time` match. Always re-run the probe after a bank edit and read **precision** first: capture buys latency, precision is what it costs. `--try` / `--try-file` names the gate that rejected a given transcript and its nearest neighbours, which is the only way to tell "add a phrasing" from "pull two classes apart".
- `docs/` — hardware wiring, voice pipeline, GraphHopper, Photon, SIM7600.
- `deploy/systemd/` — unit files for `indepensense`, `graphhopper`, `photon`, `ollama-warmup`.

## Working on the code

On the Mac, use the venv interpreter explicitly — there is no auto-activation:

```bash
.venv/bin/python -m pytest        # all unit tests, must pass on Mac
.venv/bin/python -m pytest src/indepensense/<module>/tests/unit/ -v
```

Manual tests run on the Pi with `python -m indepensense.<module>.tests.manual.<name>` — the README lists every one. Routing and intent tests additionally need GraphHopper, Photon, and Ollama running.

## Commits

Small, focused, and written so the implementation chapter can cite them. Lowercase verb prefix, then what changed, then an em dash and the *why* when it isn't obvious:

```
add: QMC5883L magnetometer driver with MockMagnetometer, calibration helper, and app wiring
fix: correct battery current sign convention — positive = charging, negative = discharging
switch: NLU Qwen 2.5 1.5B → Qwen 3 1.7B
tune: bump camera to 1280x720 and drop YOLO confidence threshold to 0.3
```

Prefixes in use: `add`, `fix`, `switch`, `tune`, `change`, `wire`, `harden`, `polish`, `test`, `docs`, `config`.

## Docs discipline

Documentation is part of the deliverable, not an afterthought — the thesis quotes it.

- Wiring changed? Update `docs/hardware.md`. It is the single source of truth for physical connections; if it disagrees with reality, the doc gets fixed.
- New manual test? Add it to the README's test table.
- New module or renamed domain? Update the README's Codebase Overview table.
- An architecture decision reversed or added? Update this file, so it never drifts from the code again.
