# Navigation Issues — Detailed Analysis

## Summary

Two separate issues discovered during prototype testing:

1. **Off-Course Silence** — System detects user is off-route, warns once, then goes silent for the rest of navigation even if they attempt to recover.
2. **Lack of Granular Guidance** — Navigation only announces distance once (100m out) and gives a haptic pulse at 20m, leaving the user unable to judge exact timing for turns.

---

## Issue 1: Off-Course Silence

### What Happened

1. System announced: "Go straight for 80 meters, then turn right onto Oak Street"
2. User started walking straight
3. Around the turn point, user deviated from the route (either took a slightly different path, GPS jitter, or simply didn't get within 5m of the announced turn)
4. System announced: "You are off the planned route. You can continue trying to reach the destination, or say cancel navigation to stop."
5. **Then: complete silence for the rest of navigation**, even though user could still hear guidance by asking "Where am I?" or "Navigation progress"

### Root Cause Analysis

The navigation system has a **cursor-based advancement model** that does not recover from off-route deviation:

**How it normally works:**
```
Thresholds:
- 100m away: Announce turn instruction once
-  20m away: Pulse the direction motor once
-   5m away: Advance cursor to next instruction (assume turn was taken)
```

**What happens when the user deviates:**

The `NavigationMonitor` in `navigation/monitor.py` uses the following logic:

```python
# Line 413: Calculate distance to current instruction
distance = haversine_m(position, instr.location)

# Lines 416-419: Announce at 100m threshold
if distance <= self._announce_distance_m and not already_announced:
    fire_announce()

# Lines 423-427: Haptic at 20m threshold  
if distance <= self._haptic_distance_m and not already_fired:
    fire_haptic()

# Lines 430-433: ADVANCE CURSOR at 5m threshold
if distance <= self._advance_distance_m:
    self._current_index += 1  # Move to next instruction
    continue
```

**The problem:**

1. User hears turn instruction at 100m (announcement fires and latches)
2. User deviates significantly from route (GPS shows 31+ meters off)
3. Off-route warning fires (line 577 in monitor.py): "You are off the planned route"
4. **However:** User never gets within 5m of that turn's location
5. **Cursor never advances** (line 430 not reached)
6. Navigation stays on the same instruction forever
7. No more cues fire because:
   - Announcement already latched (only fires once)
   - Haptic already latched (only fires once)
   - Cursor is stuck, so no new instructions to announce
   - Arrival check bypasses the stuck cursor, but that only fires when destination is reached

The system correctly identifies off-route but provides **no recovery mechanism**. The cursor is stuck on an instruction the user walked past without getting within 5m.

### Current Workarounds (Not User-Friendly)

1. User must say "cancel navigation" to reset
2. User can ask "navigation progress" to hear remaining distance (but no turn guidance)
3. User cannot recover and resume turn-by-turn guidance without cancelling

### Design Limitations

From `navigation/monitor.py` line 53-62:

```
Known limitations:
- We do NOT try to identify "past the turn" from a distance increase;
  that's fragile with GPS jitter. Advancement is strictly on proximity.
- If the user never gets within 5 m of a turn (GPS bias, wide turn),
  the monitor gets stuck on that instruction and its remaining turns
  go unspoken. The user can voice "cancel navigation" to reset.
```

This is acknowledged as an MVP limitation for thesis work, but it manifests as user-facing silence during real navigation.

---

## Issue 2: Lack of Granular Guidance

### What Happened

System announced: "In 87 meters, turn right onto Oak Street"

User had no way to know if they'd walked 20 meters, 50 meters, or 70 meters of that distance. They had to estimate based on time/steps, which is unreliable.

### Current Guidance Model

**Only two thresholds produce user-facing cues:**

| Distance | Cue | Notes |
|----------|-----|-------|
| 100m | Announce ("In 87m, turn right") | Fires once, latches |
| 20m  | Haptic pulse (silent, motor only) | Fires once, latches |
| 5m   | Advance to next instruction | Internal only, no user cue |

**What's missing:**

Progressive distance announcements as user approaches the turn:
- "Turn right in 50 meters" (when crossing 50m mark)
- "Turn right in 20 meters" (haptic already fires here, but no voice)
- "Turn right in 10 meters" (proactive warning)
- "Turn right in 5 meters" (immediate warning)
- "Turn right now" (at the turn itself)

### Impact on User Experience

**For a sighted user:** See turn approaching on map, adjust pace accordingly.

**For a blind user:** 
- Hears "turn right in 87 meters"
- Has no distance reference as they walk
- Cannot judge "am I close yet?"
- Relies entirely on haptic pulse at 20m as warning
- By 20m, they may be walking too fast to turn smoothly
- Miss the turn or overshoot because no advance preparation time

### Design Trade-off (Acknowledged)

Current design intentionally uses **single-fire latches** to prevent alert fatigue:

```python
# Line 416-419 in monitor.py
if (distance <= self._announce_distance_m
        and self._current_index not in self._announced):  # <-- latch
    self._announced.add(self._current_index)
    cues.append(...)
```

Rationale: Don't spam "turn right in 99m... 98m... 97m..." — it would be exhausting.

**But:** This leaves a gap between 100m and 20m with zero guidance.

---

## Recommendations

### For Issue 1 (Off-Course Silence): Recovery Strategy

**Option A: Timeout-based advancement (recommended for MVP)**

If user stays off-route for sustained period while in the general direction of the destination:

```python
# In NavigationMonitor, after off_route warning fires:
# If the user hasn't advanced in 30 seconds despite being off-route,
# and they are within 50m of the current instruction, advance the cursor anyway.

if (self._off_route_warned 
    and now - self._pending_turn_time > 30
    and distance_to_instruction < 50):
    # Forcibly advance; assume they tried and missed due to GPS variance
    self._current_index += 1
```

**Pros:**
- Recovers stuck cursor automatically
- Thesis-acceptable MVP solution
- Minimal code change

**Cons:**
- Might advance on wrong turn if there are 3 consecutive tight turns
- Requires tuning the timeout and distance thresholds

---

**Option B: Distance-from-route advancement**

Allow cursor to advance when user is reasonably close to the *next* instruction, even if they didn't get within 5m:

```python
# Look ahead to next instruction
next_instr = self._route.instructions[self._current_index + 1]
next_distance = haversine_m(position, next_instr.location)

# If user is closer to next instruction than current, advance
if next_distance < distance:
    self._current_index += 1
```

**Pros:**
- More robust to GPS drift and wide turns
- Follows user's actual path

**Cons:**
- Can advance too early on a route with sharp zig-zags
- More complex logic

---

**Option C: Immediate user recovery action** (UX improvement, not code fix)

Teach users in the introduction script: "If navigation goes silent after an 'off-course' warning, say 'cancel navigation' and ask 'navigate me to [destination]' again. The system will recalculate from your current location."

**Pros:**
- Zero code change
- User understands expected behavior
- Respects the GPS accuracy limits

**Cons:**
- Not seamless — requires user action
- Might happen often in urban canyons

---

### For Issue 2 (Lack of Granular Guidance): Progressive Announcements

**Recommended: Threshold-based step-down (no latch-per-threshold)**

Instead of "announce once at 100m", fire announcements at multiple thresholds:

```python
# In NavigationMonitor.check(), replace the single announce block with:

distances_to_announce_at = [100, 50, 20, 10, 5]  # metres
for threshold in distances_to_announce_at:
    key = (self._current_index, threshold)  # latch per threshold
    if (distance <= threshold 
        and key not in self._announced_by_threshold):
        self._announced_by_threshold.add(key)
        remaining = distance
        cues.append(self._build_announce_cue(
            instr, remaining, is_progress=True
        ))
        break  # Fire at most once per check; only the smallest-threshold 
```

**Message progression:**

```
100m: "In 87 meters, turn right onto Oak Street"
 50m: "Turn right in 42 meters"
 20m: "Turn right in 19 meters" (haptic also fires here)
 10m: "Turn right in 8 meters"
  5m: "Turn right in 3 meters"
  0m: "Turn right now" or just advance without announcement
```

**Pros:**
- User hears distance updates as they approach
- Can adjust pace to make the turn smoothly
- Maintains the "don't spam" principle with per-threshold latches
- Works with existing haptic pulse at 20m
- Easy to tune: just change the threshold list

**Cons:**
- More voice announcements (but spread over 80+ meters, not per-meter)
- Need different message templates for "progress" announcements
- Tuning thresholds requires field testing

---

**Alternative: Distance-based hybrid** (more aggressive)

Use a **sliding threshold** instead of fixed steps:

```python
# Announce every 25 meters if distance > 50m,
# every 10 meters if distance ≤ 50m

if distance <= self._announce_distance_m and not already_announced:
    if distance > 50:
        interval = 25
    else:
        interval = 10
    
    if int(distance / interval) != int(prev_distance / interval):
        # Crossed an interval boundary
        announce(...)
```

**Pros:**
- Denser guidance when close (5m intervals) 
- Sparser guidance when far (25m intervals)
- Prevents the 80m gap where user hears nothing

**Cons:**
- More announcements overall
- Harder to tune for different walking speeds
- "In 87 meters" → "In 76 meters" could be annoying (user walked 11m in ~10s)

---

## Implementation Priority

**For MVP thesis:**

1. **Critical:** Fix Issue 1 (off-route silence) with **Option C** (user recovery guidance + timeout-based advancement in code)
   - Cost: ~10 lines of code + update intro script
   - Thesis-defensible: "Off-route detection acknowledges GPS accuracy limits; users are instructed to reset navigation if needed"

2. **High impact but can defer:** Implement Issue 2 (granular guidance) with **progressive thresholds**
   - Cost: ~30 lines of code + new message templates
   - Thesis argument: "Iterative user feedback showed intermediate distance announcements improve turn timing"

**For field testing (now):**

- Update `PROTOTYPE_INTRODUCTION_SCRIPT.md` to explain both behaviors and workarounds
- Document in test notes: "If navigation silences after 'off-course', say 'cancel navigation' and ask again"
- Observe whether users naturally walk within 5m of turns or if GPS bias causes misses

---

## Code Locations

**NavigationMonitor (core logic):**
- `src/indepensense/navigation/monitor.py` — line 330-438 (check method)
- Lines 416-436: announce + haptic + advance logic

**Application integration:**
- `src/indepensense/app.py` — line 2054-2087 (_check_navigation method)
- Line 2079: call to monitor.check()

**Message templates:**
- `src/indepensense/intents/messages.py` — where navigation announcements are defined

**Tests:**
- `src/indepensense/tests/unit/test_app_navigation.py`
- `src/indepensense/navigation/tests/` — monitor-specific tests
