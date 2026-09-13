# Deferred Work

Things we have consciously decided **not** to build yet, and why. This is not a
bug list and not a wishlist — an item earns a place here only after it has been
discussed and deliberately parked, so that "we never thought of it" and "we
thought about it and said no for now" stay distinguishable.

For the thesis this doubles as the source for the *Future Work* section: each
entry already carries its rationale, so the chapter writes itself from here
rather than from memory.

**Status key**

- `parked` — decided against for this iteration; revisit only if a listed
  trigger fires.
- `blocked` — we want it, something concrete is in the way.
- `candidate` — plausible, not yet decided either way.

---

## Vision

### Positional scene description from YOLO bounding boxes
**Status:** parked · **Raised:** 2026-09-12

`vision.describe` currently reports *what* is in frame but not *where*.
`_describe_scene` in `intents/executor.py` groups detections by class name and
counts them ("I see two people, one chair"), discarding `Detection.bbox` —
which `vision/base.py` already populates in pixel coordinates.

Mapping the bbox x-centre to left / centre / right thirds of the frame would
give "a person ahead on your left, a chair to your right" with no new hardware
and no new model. Deferred to keep the current iteration focused on latency and
navigation, not because it is difficult.

**Revisit when:** the latency and navigation tracks are closed, or if user
testing shows people asking "where?" after a describe response.

### Currency / banknote recognition
**Status:** candidate · **Raised:** 2026-09-12

Frequently requested by blind users in the Philippines. Would need either a
dedicated classifier or OCR heuristics over denomination numerals. Accuracy
risk is high and the failure mode (telling someone a 50 is a 500) is bad enough
that it needs its own evaluation before it ships.

---

## Voice & latency

### Re-test Tagalog on `base` with a steered `initial_prompt`
**Status:** parked · **Raised:** 2026-09-12

`WHISPER_MODELS["tl"]` is `small`. Both `tiny` and `base` were rejected on
2026-07-19 for producing unusable Tagalog transcripts — but that evaluation ran
without an `initial_prompt`, and `WHISPER_INITIAL_PROMPTS["tl"]` is still `""`.
Prompt steering is what rescued English `tiny` on Filipino brand names.

Parked rather than pursued: we have direct evidence that `small` is needed for
acceptable Tagalog accuracy, and accuracy on the system's priority language is
worth more than the latency a smaller model would buy. Only worth revisiting if
measured STT latency turns out to be the dominant cost *and* the accuracy gap
closes under steering.

**Revisit when:** end-to-end latency measurements attribute most of the delay to
STT specifically.

---

## Navigation

### Tagalog turn-by-turn instruction text
**Status:** blocked · **Raised:** 2026-09-12

Navigation cues are hardcoded English in `navigation/monitor.py`
(`_check_arrival`, `_check_off_route`, `_build_announce_cue`), violating the
`messages.py` rule. Moving those three strings into `messages.py` is easy.

The blocking part is `instr.text`, which comes from GraphHopper and is English
prose ("Turn left onto Rizal Street"). GraphHopper has no Tagalog locale, so
genuine Tagalog navigation requires synthesising instruction text locally from
`RouteInstruction.direction` + `street_name` instead of passing GraphHopper's
sentence through. That is a real piece of work, not a translation pass.

**Blocked on:** deciding the local instruction-synthesis grammar for both
languages.

### "Too far to walk" ceiling on geocoded destinations
**Status:** parked · **Raised:** 2026-09-13

Originally conceived as a hard filter — drop candidates beyond some
distance so a result in another province can never be routed to. It was
proposed when `routing/ranking.py` was the only defence, and ranking cannot
help when the geocoder returns *only* far candidates: sorting a list of one
changes nothing.

Destination confirmation has since made it largely redundant. A far result
is now read back to the user with its distance before anything is routed,
and they decline. The guard would be a second net under a net that works.

If revived, it should be a **spoken message rather than a silent filter** —
"the nearest one I can find is 510 kilometres away, that's too far to walk"
tells the user why nothing happened, where filtering would leave them with
the false "I couldn't find any place matching Jollibee". It also needs a
threshold that has to be defended: ~10 km is roughly a two-hour walk, which
is a plausible ceiling for a battery-powered pedestrian device.

**Revisit when:** field testing shows users being offered absurd
destinations often enough that declining each one is a nuisance.

### Distance to a place other than the current destination
**Status:** parked · **Raised:** 2026-09-13

`navigation.progress` answers "how much further" for the journey already
under way. It cannot answer "how far is the market from here" — that would
need a `location` parameter, a geocode, and a decision about whether to
measure along a route that does not exist yet or as the crow flies.

Left out rather than half-built: replying with the *current* destination's
distance to a question about somewhere else would be a confident wrong
answer, which this device can least afford. The prompt routes such
questions to `unknown`, where the cloud fallback can attempt them.

**Revisit when:** users are observed asking it.

### Automatic re-routing after off-route deviation
**Status:** parked

Already documented as a known limitation in the `navigation/monitor.py` module
docstring. The monitor detects sustained deviation and warns; it does not
recompute a route. The user's recourse is to cancel and re-issue the command.

Accepted for the MVP: a wrong automatic reroute is worse than a warning the
user can act on.

### Left / right obstacle sensing
**Status:** blocked · **Raised:** 2026-09-12

Both DYP-A22 sensors face forward (top and bottom). The three vibration motors
can express left / right, but nothing ever gives them a left / right *obstacle*
— only navigation turns use the side motors. So the user learns something is
ahead but never which way to step around it.

**Blocked on:** hardware. Either two more ultrasonic sensors angled outward, or
derive coarse direction from YOLO bbox position (see *Positional scene
description* above), which needs no new parts.

### Compass deviation table as a calibration fallback
**Status:** parked · **Raised:** 2026-09-12

`magnetometer_calibrate` fits hard-iron offsets and soft-iron scales from a
rotation sweep — the standard approach, and what `config.py` is built around.

A teammate independently built an Arduino prototype that took a different
route: measure raw X/Y at four known headings (N/E/S/W, referenced against a
phone compass) and interpolate between those anchors. Its numbers cannot
transfer to this codebase — it ran the chip at ±30 G where our driver runs
±8 G, a 3.75× difference in counts per microtesla — but the underlying idea is
sound and has a name in marine navigation: **swinging the compass** to build a
*deviation card*.

If mounted sphere-fit calibration leaves too much residual error, the fallback
is to sample the calibrated heading at 8 or 12 known true bearings and store a
correction table, interpolating between entries. This absorbs whatever the
ellipsoid fit could not — including residual mount tilt — without modelling it.

Parked because it needs a trusted reference bearing at calibration time and
adds a second calibration artefact to keep in sync with the first. Try the
standard sweep on the assembled unit before reaching for it.

**Revisit when:** mounted calibration is done and heading error is still too
large for turn-to-face guidance to be safe.

### Compass tilt compensation and magnetic declination
**Status:** parked · **Raised:** 2026-09-12

`sensors/qmc5883p.py` computes heading from two horizontal axes with no tilt
compensation — accuracy degrades as the mounting surface leaves horizontal —
and reports magnetic rather than true north.

Declination is negligible here (roughly 0–1° across Luzon) and does not justify
the complexity. Tilt compensation would need the MPU6050's accelerometer fused
with the magnetometer, which is a real sensor-fusion addition. Park until
mounted calibration shows how much tilt error the assembled wearable actually
has.

**Revisit when:** post-calibration heading error on the assembled unit exceeds
what turn-to-face guidance can tolerate.

---

## Places & guardian integration

### Guardian-controlled saved places via the backend
**Status:** parked · **Raised:** 2026-09-12

Saved places start as voice-controlled and device-local, because the moment a
user most needs "take me home" is also the moment they are most likely to have
no data connection — and because the user is physically standing at the place
when they save it, which is exactly when the GPS fix is trustworthy.

A guardian adding places from the dashboard is a reasonable second channel, but
it means a backend endpoint, a sync path, and cache invalidation — cross-repo
work with the backend developer.

**Revisit when:** the voice-controlled version is working and the backend
developer has capacity.

---

## Help & discoverability

### Full spoken capability listing
**Status:** parked · **Raised:** 2026-09-12

The help response is a short identity statement plus the three or four most
useful things, not an exhaustive catalogue — reading twelve capabilities aloud
is roughly forty-five seconds the user will not sit through and will not
remember.

An exhaustive second tier ("what else can you do?") is possible later if user
testing shows people hunting for features they cannot find.
