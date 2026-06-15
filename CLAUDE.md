# IndepenSense — Working Agreement

This file tells Claude how to collaborate on this thesis project. Read `README.md` for the project's purpose and architecture.

## Context

- **Thesis project** — decisions need to be defensible in writing and viva. Always explain *why*, not just *what*.
- **Dev environment:** macOS. **Deploy target:** Raspberry Pi 5 (Raspberry Pi OS).
- **Single developer**, tight timeline. Prefer the simplest credible option that meets requirements.

## Architecture decisions in force

1. **Single polling loop** for the on-device runtime. One synchronous loop reads each sensor in turn, fuses state, decides actions, emits feedback. Escalate to threading or asyncio **only if a measured latency problem appears** — not preemptively.
2. **Hardware abstraction.** Every sensor has a `Protocol` interface in `base.py`, a real driver (e.g. `dyp_a22.py`), and a mock (`mock.py`). Application code depends on the protocol, never the concrete driver. This lets the project run on Mac for fast iteration.
3. **Drivers own protocol knowledge.** The parsing/checksum/conversion for a sensor lives in its driver, not in tests or callers. Tests verify the driver; callers consume clean values.
4. **Tests nested per module:**
   - `src/indepensense/<module>/tests/unit/` — automated pytest, no hardware needed
   - `src/indepensense/<module>/tests/manual/` — human-run scripts that need real hardware
5. **Backend / guardian dashboard** lives in a separate repository. Not in scope here.

## How Claude should behave

- **Ask before structural changes.** Propose, explain the tradeoff, wait for approval. The user defends every decision in their thesis.
- **Explain tradeoffs, not just conclusions.** Always name the alternative and why it was rejected.
- **No silent abstractions.** Do not introduce a class, layer, or interface unless asked or until it has earned its place. YAGNI.
- **Explain concepts when asked.** "What is X?" is a real learning question — answer with the concept, why it exists, and a concrete example. Do not be patronizing.
- **Hardware-aware suggestions.** Anything sensor-touching must have a mock or be guarded so it runs on Mac.
- **Thesis-friendly commits.** Small, focused, with clear "why" in the message. The implementation chapter will reference these.
- **No backwards-compat hacks.** Project is greenfield. Delete cleanly; do not leave commented-out code or unused stubs.

## Project layout

```
src/indepensense/
├── __init__.py
└── sensors/
    ├── __init__.py
    ├── base.py            # UltrasonicSensor Protocol + Reading dataclass
    ├── dyp_a22.py         # real driver (UART, header + checksum)
    ├── mock.py            # mock impl for off-device development
    └── tests/
        ├── unit/          # pytest, runs anywhere
        └── manual/        # human-driven scripts, need real sensor
```

Other domains (`vision/`, `navigation/`, `fusion/`, `feedback/`, `telemetry/`, `safety/`) will be added under `src/indepensense/` **when their first real code lands** — not as empty placeholders.

## Setup

On any machine:

```bash
pip install -e .
pip install -r requirements.txt
```

Additionally on the Raspberry Pi:

```bash
pip install -r requirements-pi.txt
```

## Running things

- Unit tests: `pytest`
- Manual sensor test (Pi only): `python -m indepensense.sensors.tests.manual.single_dyp_test`
