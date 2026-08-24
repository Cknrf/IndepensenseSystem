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
   voice thread (one per PTT press), gpiozero button callbacks, per-event warning-pattern threads under a mutex, heartbeat sender, telemetry retry worker, and the 1 Hz GPS cache thread.
   The rule is **never block the main loop**, not "never use threads". Adding a *new* long-lived thread is a structural change — propose it first. No asyncio; the thread set is small and each one has a single clear job. See the module docstring at the top of `app.py` for the authoritative description.

2. **Hardware abstraction.** Every device has a `Protocol` interface in its module's `base.py`, a real driver (e.g. `dyp_a22.py`), and a mock (`mock.py`). Application code depends on the protocol, never the concrete driver.

   In `app.py` this is enforced by a single rule: **every device is constructed in an `_open_*` / `_try_open_*` factory method and nowhere else.** `start()` calls the factories but never a driver constructor. That is what lets `app_mock.py` subclass `App`, override only the factories, and run the whole runtime on a Mac with the loop, threads and decision logic inherited untouched. Add a device, add a factory — an inline constructor in `start()` silently drops it out of mock coverage.

   `_open_*` means the runtime cannot function without it and failure aborts startup (IMU, STT, TTS, NLU parser). `_try_open_*` means degraded operation is acceptable — it logs, returns `None`, and every caller handles `None`.

   `app_mock.py` is development-only and never imported by production: `deploy/systemd/indepensense.service` starts `indepensense.app`. The separation is structural, not a runtime flag, so a misconfigured flag can never substitute a fake sensor on the real device.

3. **Pi-only libraries are imported lazily, inside the function that needs them.** `serial`, `smbus2`, `gpiozero`, `picamera2`, `ultralytics`, `pytesseract`, `faster_whisper`, `piper` — never at module top level. This is what lets the real drivers be imported, introspected, and unit-tested on a Mac where those packages don't exist. Follow the existing comment style:
   ```python
   import serial  # lazy: only resolvable on the Pi
   ```

4. **Drivers own protocol knowledge.** Parsing, checksums, register maps, and unit conversion live in the driver, not in tests or callers. Tests verify the driver; callers consume clean values. Document register addresses and datasheet sections in the driver's docstring, as `mpu6050.py` does.

5. **`config.py` owns what varies; drivers own what's fixed.** Ports, pins, I²C addresses, thresholds, intervals, model paths → `config.py`. Constants dictated by the chip itself (frame layout, header byte, checksum formula) stay in the driver — those are the chip's contract, not configuration.

6. **No user-facing text in Python.** Every spoken response lives in `intents/messages.py`, keyed by message then language; the executor only calls `messages.get(key, language)`. The active language is runtime state (`language.py`), shared by reference so a switch is visible to everything immediately — not a constant, and not a value copied at construction.

   Adding a response means adding every language's version. Unit tests enforce full coverage and matching placeholders, so a missing translation is a test failure rather than the wearable saying the wrong thing to the one user who speaks that language.

   Sentence *structure* may differ per language, not just wording — Tagalog does not inflect nouns for number, so scene description branches per language rather than sharing a pluraliser. Put that kind of grammar in `messages.py`, not in the handler.

7. **Tests nested per module:**
   - `src/indepensense/<module>/tests/unit/` — pytest, no hardware, must pass on a Mac
   - `src/indepensense/<module>/tests/manual/` — human-run scripts that need real hardware

   Runtime-wide code that belongs to no single domain (`app.py`, `language.py`, `net.py`) is tested in `src/indepensense/tests/unit/`.

   A new hardware component isn't done until it has a manual test, and that test is listed in the README's Manual Verification Tests table. The fabricator uses those commands to verify wiring without writing Python.

   **Unit tests never touch the network.** Modules whose code makes HTTP calls stub `requests` with an autouse fixture — otherwise the suite passes or fails depending on whether the dev machine is online, and stalls for the timeout when it isn't.

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

- `prompts/nlu_system.md` — the LLM intent-classification system prompt. **Prompt changes go here, not into Python.** Loaded via `config.NLU_PROMPT_PATH`. After editing it, re-run the probe: `llm_probe` exercises 66 prompts across English, Tagalog and adversarial groups, reported per group — a blended score would hide a model that aces English and fails Tagalog.
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
