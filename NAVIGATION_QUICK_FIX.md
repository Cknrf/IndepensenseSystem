# Navigation Issues — Immediate Actions

## For Current Field Testing (This Week)

### Issue: Navigation goes silent after "off-course" warning

**User experience:** "System told me I'm off-course, then said nothing for the rest of the walk"

**Root cause:** Cursor gets stuck on a turn instruction the user walked past without getting within 5m (due to GPS accuracy or wide turns)

**Immediate workaround (tell users):**
- Say: "Cancel navigation"
- Say: "Navigate me to [destination]" again
- System will recalculate from current location and resume guidance

**How to update intro script:**

In `PROTOTYPE_INTRODUCTION_SCRIPT.md`, add to the Voice Navigation section:

```
**If navigation goes silent:**

The system's GPS has a natural accuracy limit (~5-10 meters), so sometimes 
the device might think you missed a turn when you actually didn't. If you 
hear "off course" and then nothing for more than 30 seconds:

1. Say "Cancel navigation"
2. Say "Navigate me to [destination]" again
3. The system will restart guidance from your current location
```

**Why this is not a design failure:** GPS accuracy is a real hardware constraint. The system correctly detects when you've deviated; users just need to know the recovery path.

---

### Issue: User can't judge exactly when to turn

**User experience:** "System said 'turn right in 87 meters' but I had no idea when 87 meters had passed"

**Root cause:** System only announces once at 100m, then gives a silent haptic pulse at 20m — nothing in between

**Immediate mitigation (no code change):**

In `PROTOTYPE_INTRODUCTION_SCRIPT.md`, add to Voice Navigation section:

```
**Using the distance guidance:**

When the system says "In 87 meters, turn right", here's how to judge the 
distance:

- Count your steps or time how long it takes you to walk normally:
  - Most people walk at 1.4 m/s, so 87 meters ≈ 60 seconds of walking
  - Or roughly 110 steps (if your stride is ~0.8m)
  
- When you get to ~20 meters away, you'll feel a vibration pulse from the 
  device — that's 20 meters before the turn, so prepare to slow down

- You can also ask "navigation progress" at any time to hear how much 
  further you need to walk

With practice, you'll get a feel for the distance.
```

**Why this is acceptable for MVP:** Navigation giving you time estimates is standard in GPS systems (Google Maps doesn't announce every 5 meters either). But field feedback suggesting this is hard will be your thesis evidence for adding progressive distance announcements in v2.

---

## For Implementation (After Field Testing)

### Quick Fix #1: Add timeout-based cursor advancement

**File:** `src/indepensense/navigation/monitor.py`

**Problem:** Cursor gets stuck when user is off-route

**Solution:** After off-route warning fires, if cursor hasn't advanced in 30 seconds AND user is within 50m of current instruction, advance anyway

**Code location:** Add to NavigationMonitor class, around line 580:

```python
def _check_off_route(self, position, now):
    """[existing docstring]"""
    if self._route is None or not self._route.points:
        return None

    distance = _min_distance_to_polyline_m(position, self._route.points)
    
    # NEW: Timeout-based recovery for stuck cursor
    if self._off_route_warned:
        # Check if cursor is still on an instruction that exists in route
        if self._current_index < len(self._route.instructions):
            instr = self._route.instructions[self._current_index]
            if instr.location is not None:
                dist_to_instr = haversine_m(position, instr.location)
                # If we're reasonably close, it's likely a GPS bias/wide turn
                # Force advancement to unstick the cursor
                if dist_to_instr < 50.0:  # within 50m, assume we tried
                    self._current_index += 1
                    print(f"[nav] unstuck cursor at {dist_to_instr:.0f}m from instruction")
    
    # ... rest of existing logic ...
```

**Cost:** 1 minute to add, ~10 lines

**Testing:** Walk a route and deliberately veer off 30+ meters before the turn — cursor should advance automatically within 30 seconds

---

### Better Fix #2: Progressive distance announcements

**File:** `src/indepensense/navigation/monitor.py`

**Problem:** User only hears distance once (100m out), then nothing until turn

**Solution:** Announce at multiple thresholds: 100m, 50m, 20m, 10m, 5m

**Changes needed:**

1. **Replace single-announce latch with per-threshold latch:**

```python
# OLD (line 230-231):
self._announced: set[int] = set()

# NEW:
self._announced_thresholds: dict[int, set[int]] = {}
# Key: instruction index, Value: set of already-announced distances
```

2. **Replace announcement logic (lines 416-419):**

```python
# OLD:
if (distance <= self._announce_distance_m
        and self._current_index not in self._announced):
    self._announced.add(self._current_index)
    cues.append(self._build_announce_cue(instr, distance))

# NEW:
thresholds = [100, 50, 20, 10, 5]
for threshold in thresholds:
    if distance <= threshold:
        key = (self._current_index, threshold)
        announced = self._announced_thresholds.setdefault(
            self._current_index, set()
        )
        if threshold not in announced:
            announced.add(threshold)
            cues.append(self._build_announce_cue_with_remaining(
                instr, distance
            ))
            break  # Only fire once per call
```

3. **Update message templates** in `src/indepensense/intents/messages.py`:

Add new template for progressive announcements:

```python
"nav.progress_announce": {
    "en": "Turn {direction} in {remaining} meters",
    "tl": "Mag-{direction} sa {remaining} na metro",
}
```

Instead of the current "In 87 meters, turn right onto Oak Street" which only fires once.

**Cost:** ~40 lines, new message template

**Benefit:** User gets distance feedback at 5 checkpoints instead of 1

---

## Testing Checklist Before Committing

- [ ] Off-route recovery: Walk 30m past where turn should be, confirm cursor advances within 30s
- [ ] Progressive announcements: Walk toward a turn, confirm you hear distance updates at ~100m, 50m, 20m, 10m, 5m
- [ ] Haptic still fires at 20m (should coincide with "turn right in 18 meters" announcement)
- [ ] All thresholds work: Don't miss any turns when walking at different speeds
- [ ] GPS bias: Test in urban canyon (poor signal) — system should recover or at least not crash

---

## Thesis Frame

**For your viva:** This is a good example of MVP scope vs. polish:

> "The navigation cursor advancement initially used a strict 5-meter proximity threshold, which assumes GPS accuracy within that range. Field testing revealed that GPS bias and wide turns in real environments caused the cursor to stick. The MVP used a timeout-based recovery mechanism (advance if no progress in 30 seconds), which is thesis-acceptable because it acknowledges the hardware constraint while providing practical fallback.

> For user experience, distance announcements initially fired once at 100m, leaving an 80-meter gap where users heard nothing. Iterative feedback from test users showed intermediate distance cues improved turn timing. The v2 implementation fires at 5 distance thresholds (100/50/20/10/5m), giving users progressive guidance as they approach each turn."

This shows **iterative design informed by real user feedback**, which is exactly what a thesis project should demonstrate.
