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

**Two external blockers account for most of what is `blocked` below**, and
several `parked` entries name them as their revisit trigger:

- **The assembled prototype.** Compass calibration gates three shipped
  features (`COMPASS_CALIBRATED` in `config.py`), the buzzer cannot be judged
  too loud until it can be heard in context, and two button positions are
  unrecorded.
- **A microphone.** The latency work — Whisper decode flags, the static-TTS
  cache, and a deterministic fast path in front of the LLM — is not deferred,
  it is simply unmeasured. Nothing there should be changed before
  `intents.tests.manual.end_to_end_test` has produced per-stage numbers.

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

**Revisit when:** the navigation track closed on 2026-09-13, so this is now
the strongest remaining vision item — the trigger has half fired. Still
waiting on the latency track, which is blocked on hardware.

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
`intents/messages.py` rule. Moving those three strings into `messages.py` is easy.

The blocking part is `instr.text`, which comes from GraphHopper and is English
prose ("Turn left onto Rizal Street"). GraphHopper has no Tagalog locale, so
genuine Tagalog navigation requires synthesising instruction text locally from
`RouteInstruction.direction` + `street_name` instead of passing GraphHopper's
sentence through. That is a real piece of work, not a translation pass.

**This got worse on 2026-09-13.** `nav.missed_turn` is properly translated but
interpolates `cue.text` — GraphHopper's English — into its Tagalog sentence, so
a Tagalog user hears "Mukhang nalampasan mo ang liko. Ang tagubilin ay: Turn
left onto Rizal Street." Every new cue that quotes an instruction inherits the
same seam, which is an argument for doing the synthesis sooner rather than
later.

**And worse again on 2026-09-17,** when Tagalog TTS moved from the Indonesian
Piper voice to `facebook/mms-tts-tgl`. The old voice at least phonemised
English through espeak-ng and produced something recognisable. MMS is a
character-level model with a 43-character vocabulary trained only on Tagalog:
it has no English phonology to fall back on, and any character outside that
vocabulary is dropped silently. "Turn left onto Rizal Street" spoken by it is
not accented English, it is Tagalog letter-sounds read off English spelling.
The seam is now audible rather than merely inelegant.

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

### Time remaining, not just distance
**Status:** parked · **Raised:** 2026-09-13

`navigation.progress` answers "how much further" with a distance and says
nothing about time, even though "how much longer" is how people phrase it.

Left out deliberately. The seconds would have to come from an assumed
walking speed, and the only one available is GraphHopper's pedestrian
profile at a brisk 5 km/h — which a cane user is unlikely to match. A
confident wrong number would have somebody hurrying, and the failure is
invisible: they cannot tell the estimate was optimistic until they are late.

If revived, the honest version calibrates against the user's own observed
pace over the current route rather than a constant, which needs distance
history the monitor does not keep.

**Revisit when:** enough real walks exist to derive a pace from, or a user
asks for it and accepts a rough answer.

### Listing saved places aloud
**Status:** parked · **Raised:** 2026-09-13

There is `place.save` and `place.delete` but no `place.list`. A user who
forgets what they saved something as cannot ask; they re-save it under a
name they do remember, which works but leaves an orphan.

`SavedPlaces.labels()` already exists and returns them sorted, so the
handler is a few lines. Parked because the list is spoken, and a user with a
dozen places gets a dozen labels read at them with no way to skip — the same
objection that kept the help response short. Worth doing with a cap, or not
at all.

**Revisit when:** anyone accumulates enough saved places to lose track, or
`place.delete` is observed failing because the label was misremembered.

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

**Sharpened on 2026-09-13.** Turn verification now catches a missed turn in
about five seconds, against the fifteen to thirty that position-based
deviation needs — so the wearable knows sooner, and still has nothing to
offer but the instruction that was missed. That widens the gap between what
it detects and what it can do about it, and makes this the most valuable
navigation item left.

### Quieting the buzzer
**Status:** parked · **Raised:** 2026-09-13

The buzzer was judged too loud in prototype testing. It is an **active**
buzzer — it contains its own oscillator, so applying voltage is the only
control there is and loudness is fixed by the part.

Options, none free of caveats:

* **PWM the supply** to lower the average voltage. Probably works, but the
  oscillator has a minimum start voltage, so the usable range may be only
  100%→60% before it stutters or falls silent. gpiozero on the Pi 5 uses
  *software* PWM whose jitter can itself be audible; GPIO 18 is a hardware
  PWM pin but reaching it needs `dtoverlay` and sysfs, not gpiozero.
* **Series resistor** — reliable, but hardware rework on a fabricated unit.
* **Physical damping** (tape or foam over the sound port) — several dB,
  free, reversible, and the fabricator can do it in a minute.

**The likely misdiagnosis:** the buzzer fires on TOP + *warning*, i.e.
anything within 100 cm at head level, with a 2 s cooldown. Under an awning
or past a row of signage that is a beep every two seconds indefinitely, so
"too loud" may really be "would not stop". The free fix is to drop the
buzzer from the warning tier — which already fires a front-motor pulse —
and keep it for danger (50 cm) and the emergency button, matching the
reasoning already applied to the silent BOTTOM sensor.

**Revisit when:** the prototype is back and it can be judged with the
warning tier silenced first, before anything is attenuated or rewired.

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
large for turn-to-face guidance to be safe. As of 2026-09-13 three shipped
features sit behind `COMPASS_CALIBRATED` — turn-to-face, the departure
heading, and turn verification — so calibration quality is now the single
gate on all of them rather than a nice-to-have.

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
what turn-to-face guidance can tolerate. Turn-to-face is used standing still,
which is the best case for an uncompensated compass; turn *verification* reads
heading while walking, where torso sway is worse, so that is where tilt error
will show up first.

---

## Places & guardian integration

### Guardian-controlled saved places via the backend
**Status:** parked · **Raised:** 2026-09-12

Saved places shipped on 2026-09-13 as voice-controlled and device-local,
because the moment a user most needs "take me home" is also the moment they are
most likely to have no data connection — and because the user is physically standing at the place
when they save it, which is exactly when the GPS fix is trustworthy.

A guardian adding places from the dashboard is a reasonable second channel, but
it means a backend endpoint, a sync path, and cache invalidation — cross-repo
work with the backend developer.

**Revisit when:** the voice-controlled version has been used on the prototype
and the backend developer has capacity.

---

## Hardware documentation

### Emergency and repeat button positions
**Status:** blocked · **Raised:** 2026-09-13

`docs/hardware.md` records PTT as the **left** button but leaves the other
two as *unrecorded*. That gap is load-bearing in one place: the spoken help
response deliberately does not tell the user which button summons help,
because naming a button we cannot locate is worse than not mentioning it.

The `help.capabilities` message carries a comment saying to add that
sentence once the layout is confirmed. `button.ptt_position` in
`intents/messages.py` is the pattern to follow — the position is its own key in both
languages, so a rebuilt enclosure is one edit.

**Blocked on:** somebody looking at the assembled prototype and writing the
two positions into the table.

---

## Help & discoverability

### Full spoken capability listing
**Status:** parked · **Raised:** 2026-09-12

`system.help` shipped on 2026-09-13 as a short identity statement plus the
four most useful things, not an exhaustive catalogue — reading twelve capabilities aloud
is roughly forty-five seconds the user will not sit through and will not
remember.

An exhaustive second tier ("what else can you do?") is possible later if user
testing shows people hunting for features they cannot find.
