# Understanding the Navigation Cursor — Deep Dive

## The Core Concept: What is the "Cursor"?

The navigation system divides every route into **numbered steps called instructions**:

```
Route to "Starbucks" has 4 instructions:

Index 0: "Start on Main Street, go straight"
Index 1: "Turn right onto Oak Avenue"      <-- Current cursor is here
Index 2: "Turn left onto 5th Street"
Index 3: "Arrive at Starbucks"
```

The **cursor** is just a **number that tracks which instruction we're on**. It starts at 0, and advances to 1, 2, 3 as you walk.

```python
# In NavigationMonitor class:
self._current_index = 0  # This is the cursor

def check(self, position, ...):
    # We look at: self._route.instructions[self._current_index]
    # That's the instruction the cursor is pointing at
```

**Why does this matter?** Because all the logic (announce, haptic, advance) works on the *current* instruction the cursor is pointing at. If the cursor doesn't move, the system keeps firing cues for the same instruction forever.

---

## The Three Distance Thresholds

For *each* instruction, there are three magic distances:

```
Instruction: "Turn right onto Oak Avenue"
Location on map: (14.3521°N, 121.0235°E)

User walks toward it from GPS position (14.3520°N, 121.0240°E)
Distance to instruction location: 50 meters

      100m threshold
         |
    ✓ ANNOUNCE --- Speak: "In 47 meters, turn right onto Oak Avenue"
                    Latches so it only fires once
         |
    ... silence ...
         |
      20m threshold
         |
    ✓ HAPTIC ------ Vibrate left motor once (silent cue)
                    Latches so it only fires once
         |
    ... user walking ...
         |
       5m threshold
         |
    ✓ ADVANCE ----- Move cursor to next instruction
                    Assume user took the turn
         |
    ✗ NO MORE CUES for this instruction
```

---

## The Problem: What Happens When Cursor Can't Advance

### Scenario: Your Groupmate's Walk

**Expected path:**
```
    Main Street (straight)
         |
         |-- 5m before turn
         |
    ✓ ADVANCE cursor (turn completed, move to next instruction)
         |
    Oak Avenue (turn right)
```

**What actually happened:**

```
GPS Position: (14.3521°N, 121.0235°E)
Turn Location: (14.3515°N, 121.0230°E)    ← Instruction says turn HERE

User walks toward turn...

At 100m away: ✓ ANNOUNCE "In 87 meters, turn right"
              (announcement LATCHES — won't fire again)

At 50m away:  (silent, walking continues)

At 20m away:  ✓ HAPTIC "vibrate left motor"
              (haptic LATCHES — won't fire again)

At 10m away:  (silent, walking continues)

At 5m away:   ... user is NOT at this distance yet ...

At 2m away:   ... user NEVER gets within 5m of turn location ...
              Because they walked on a slightly different path
              (took a shortcut, or GPS drifted, or turn was wide)
```

**Why didn't they get within 5m?**

GPS accuracy on Earth is typically **±5-10 meters** depending on:
- Building obstructions (urban canyon = worse accuracy)
- Satellite visibility
- Time of day
- Device quality

So even if your groupmate walked perfectly straight to the turn, the GPS might report them as:
- 8 meters away (off to the left)
- 7 meters away (off to the right)
- 12 meters away (GPS jitter)

**Result:** They never hit the 5m threshold.

---

## The Stuck Cursor Problem

Since the user never reached 5m, the cursor **never advanced**.

```python
# In NavigationMonitor.check() around line 430:

distance = haversine_m(position, instr.location)  # 8 meters (GPS shows)

if distance <= 5:  # 8 is NOT <= 5
    self._current_index += 1  # <-- THIS NEVER HAPPENS
    continue
```

**What happens next check() call?**

The cursor is still at the same instruction. But:

1. ✗ Announcement already fired (latched) — won't fire again
2. ✗ Haptic already fired (latched) — won't fire again
3. ✗ User is still >5m away (GPS shows 8m) — can't advance

**Result: Zero cues fire. System goes silent.**

---

## Why It Gets Worse: The Stuck Cursor Trap

After off-route warning fires, the system enters this state:

```
User position: Still walking toward destination
GPS shows: 8m away from turn location, but >30m off the planned polyline

NavigationMonitor.check() runs:

1. Off-route warning fires once: "You are off the planned route"
   (then latches, won't fire again)

2. Cursor still at instruction #1 (Turn right)
   - Distance: 8m
   - Announcement: already latched (won't fire)
   - Haptic: already latched (won't fire)
   - Advance: needs ≤5m (user is 8m, doesn't happen)
   
3. No cues fire
   → System is silent

4. Next check() call (1 second later):
   Same situation. Still silent.

5. User walks forward, now 3m from turn:
   - Still ≤5m? Yes!
   - But... now the off-route warning already latched
   - And announcement already latched
   - And haptic already latched
   - So STILL no new cues

6. User finally walks within 5m and cursor advances:
   - Cursor moves to instruction #2 (Turn left onto 5th Street)
   - This instruction hasn't been announced yet
   - But they're already at the turn, no time to hear "in 87 meters"
   - They miss the second turn too
```

**The core problem:** Latches prevent spam, but they prevent recovery.

---

## Why This Isn't "Just GPS Error"

You might think: "Can't we just add GPS error margin?"

**No, because the margin is part of the design:**

```python
# Current code:
if distance <= 5:  # This 5 is the "advance threshold"
    advance()

# What if we changed it to:
if distance <= 15:  # Account for 10m GPS error
    advance()
```

**Looks good! But it breaks other scenarios:**

### Scenario A: Tight zig-zag turns (3 turns in 50 meters)

```
    Instruction 1: Turn right
       └─ Position: (14.3521°N, 121.0235°E)
    
    Instruction 2: Turn left (15m ahead)
       └─ Position: (14.3506°N, 121.0235°E)
    
    Instruction 3: Turn right (30m from instruction 1)
       └─ Position: (14.3490°N, 121.0235°E)
```

If advance threshold is 15m:
- User at 14m from instruction 1
- Cursor advances to instruction 2
- But instruction 2 is only 15m away total
- User might already be past it
- Cursor never fires instruction 2's cues

### Scenario B: GPS jitter on straight segment

```
    Instruction 1: Go straight on Main Street
    Instruction 2: Turn right in 100m
    
    User walks straight, position jitters:
    - 40m from instruction 1 (jitter: ±8m)
    - 60m from instruction 1 (jitter: ±5m)
    
    If advance threshold is 15m:
    - When jitter puts them 14m away, cursor advances prematurely
    - They hear instruction 2's announcement too early
    - Miss the actual turn
```

**So the 5m threshold exists for a reason: it's a tradeoff.**

- **5m threshold:** Works well on routes with turns >30m apart. Fails when GPS drifts >5m.
- **15m threshold:** Works on drifty GPS. Breaks on tight zigzag routes.

---

## The Current Code Flow

Let me show you the actual code to see where it breaks:

### File: `navigation/monitor.py`, method `check()` (line 330-438)

```python
def check(self, position, now=None, heading=None):
    """Given user position, return cues to fire."""
    if self._route is None:
        return []
    
    cues = []
    
    # ... off-route and arrival checks ...
    
    # MAIN LOOP: Process current instruction
    while self._current_index < len(self._route.instructions):
        instr = self._route.instructions[self._current_index]
        
        if instr.location is None:
            self._current_index += 1
            continue
        
        distance = haversine_m(position, instr.location)
        
        # ===== ANNOUNCE AT 100M =====
        if (distance <= self._announce_distance_m  # 100m
                and self._current_index not in self._announced):  # <-- LATCH
            self._announced.add(self._current_index)  # <-- Mark as fired
            cues.append(self._build_announce_cue(instr, distance))
        
        # ===== HAPTIC AT 20M =====
        if (distance <= self._haptic_distance_m  # 20m
                and self._current_index not in self._haptic_fired):  # <-- LATCH
            self._haptic_fired.add(self._current_index)  # <-- Mark as fired
            cues.append(NavigationCue(kind="haptic", direction=instr.direction))
        
        # ===== ADVANCE AT 5M =====
        if distance <= self._advance_distance_m:  # 5m
            self._current_index += 1  # <-- Move to next instruction
            continue  # <-- Exit loop and come back next call()
        
        # Not yet at turn, nothing more to do
        break  # <-- Exit loop if not at threshold
    
    return cues
```

**The problem is here:**

1. Once `self._announced` contains index 1, that latch is permanent
2. If `distance > 5`, the `if distance <= 5` block never executes
3. Cursor stays at index 1 forever
4. Every future `check()` call on index 1 finds it already in `self._announced`
5. No new cues fire

**There's no mechanism to say:** "User walked past this instruction somehow, move on anyway"

---

## Visual Walkthrough: The Exact Failure

Let me show you frame-by-frame what happens:

### Frame 1: User is 50m away from turn

```python
# NavigationMonitor.check() call

distance = 50.0  # 50 meters away
self._current_index = 1  # "Turn right"

# ANNOUNCE check:
if 50 <= 100 and 1 not in {0}:  # True and True
    self._announced.add(1)  # NOW: {0, 1}
    fire_announce("In 47 meters, turn right")  # ✓ FIRES

# HAPTIC check:
if 50 <= 20 and 1 not in set():  # False (50 NOT <= 20)
    pass  # Does not fire

# ADVANCE check:
if 50 <= 5:  # False (50 NOT <= 5)
    pass  # Cursor does NOT advance

# Return cues: ["announce"]
# Loop exits (break on line 436)
```

**Result:** User hears "In 47 meters, turn right"

---

### Frame 2: User is 8m away (GPS drifted, never within 5m)

```python
# NavigationMonitor.check() call (1 second later)

distance = 8.0  # 8 meters away (GPS never drifted below 5m)
self._current_index = 1  # STILL "Turn right" (cursor didn't advance)

# ANNOUNCE check:
if 8 <= 100 and 1 not in {0, 1}:  # True but FALSE (1 IS in announced)
    pass  # Does not fire (LATCH prevents it)

# HAPTIC check:
if 8 <= 20 and 1 not in set():  # True but FALSE (1 IS in haptic_fired)
    pass  # Does not fire (LATCH prevents it)

# ADVANCE check:
if 8 <= 5:  # False (8 NOT <= 5)
    pass  # Cursor does NOT advance

# Return cues: []
# Loop exits
```

**Result:** System is SILENT (no cues)

---

### Frame 3: User walks forward to 2m away

```python
# NavigationMonitor.check() call (2 seconds later)

distance = 2.0  # 2 meters away (finally!)
self._current_index = 1  # STILL "Turn right"

# ANNOUNCE check:
if 2 <= 100 and 1 not in {0, 1}:  # True but FALSE
    pass  # Nope, already announced

# HAPTIC check:
if 2 <= 20 and 1 not in set():  # True but FALSE
    pass  # Nope, already fired

# ADVANCE check:
if 2 <= 5:  # TRUE! Finally!
    self._current_index = 2  # Cursor moves to "Turn left"
    continue  # Loop restarts
    
# Now on index 2:
instr = instructions[2]  # "Turn left onto 5th Street"
distance = haversine_m(position, instr.location)  # Probably 85m+

# ANNOUNCE check:
if 85 <= 100 and 2 not in {0, 1}:  # True and True
    self._announced.add(2)
    fire_announce("In 82 meters, turn left")  # ✓ FIRES (too late!)

# Return cues: ["announce"]
```

**Result:** User finally hears the announcement... but they're already AT the previous turn!

---

## Why the Off-Route Warning Makes It Worse

The off-route detection fires **once** and latches:

```python
# In NavigationMonitor._check_off_route() around line 576:

if (distance > self._off_route_distance_m  # 30m off route
        and not self._off_route_warned):  # Haven't warned yet
    self._off_route_warned = True  # <-- LATCH
    return NavigationCue(kind="off_route", text="...")
```

**So when user is 35m off-route:**
1. First check: "You are off the planned route" (fires, latches)
2. Second check: Nothing (latch prevents repeat)
3. User thinks the warning was for them doing something wrong
4. But actually it's GPS drift + the 5m threshold doesn't accommodate it
5. They don't know to cancel and restart
6. They sit in silence

---

## The Root Cause: Latches + Fixed Thresholds

The system uses **latches** (fire-once blocks) because:

- **Problem they solve:** Prevent spam (don't announce every GPS update: "In 99m, in 98m, in 97m...")
- **Problem they cause:** Can't recover from missed thresholds

```python
# LATCHES PREVENT SPAM:
self._announced.add(1)  # Remember we announced index 1
# Next check: if 1 in self._announced, don't announce again

# BUT ALSO PREVENT RECOVERY:
# If you never hit the 5m threshold, announcement is "wasted"
# No mechanism to say "that latch is invalid now, re-announce"
```

The **fixed 5m threshold** assumes:
- GPS accuracy ≤ 5m (often not true in practice)
- User walks within 5m of instruction location (but may take wider turns)
- Route instructions are >15m apart (may not be true for urban routes)

---

## Summary: The Core Issue

| Component | Current Behavior | Problem |
|-----------|------------------|---------|
| **Cursor** | Number pointing to current instruction | If cursor doesn't advance, same instruction's cues repeat |
| **Latch on announce** | Fire once at 100m, never again | Can't recover if user doesn't reach 5m threshold |
| **Latch on haptic** | Fire once at 20m, never again | Can't send "try again" cue to help user reorient |
| **5m threshold** | Assume user took turn within 5m | Fails on 8m GPS drift or wide turns |
| **Off-route warning** | Fire once, then silent | Doesn't guide user back to route or skip stuck instruction |

**Result:** Stuck cursor = stuck navigation = silence

---

## Your Decision: What Should We Fix?

Now that you understand it, here are your real options:

### Option A: Relax the threshold (e.g., 15m instead of 5m)
- ✓ Easier to hit
- ✗ Might advance on wrong instruction in tight turns
- ✗ Doesn't solve all GPS cases (still might miss)

### Option B: Timeout-based recovery
- ✓ Automatic unstuck cursor after 30s
- ✓ No false advances on zig-zag routes
- ✗ Still needs to handle what to announce

### Option C: Remove latches from announce/haptic
- ✓ Can re-announce if user walks backward or GPS jitters
- ✗ Might spam on normal GPS drift

### Option D: Hybrid - smarter latching
- Keep latches but clear them after cursor advances
- Track per-threshold instead of per-instruction
- More complex but cleanest solution

### Option E: Don't fix it, just document workaround
- ✓ No code change
- ✗ Users need to know to "cancel and restart navigation"

Which direction feels right for your thesis?
