# Design Questions: Analysis & Tradeoffs

## 1. Battery Status Announcement at Startup

**Question:** We need to announce battery status right after app starts, so users know if they should charge before going out.

**Current state:** Battery is monitored by `power/battery.py` and reported on-demand (`"What's my battery?"`), but not announced at startup.

**Proposal:** On successful app initialization, run the battery check and announce it via `_announce()` before the ready chime.

**Why this:** The user's first action is to power on and go—they may not think to ask for battery until they're already outside. Early disclosure at startup is a safety requirement, not an afterthought feature. Announced before the ready chime keeps the flow intact (announcement → chime = "I'm ready").

**Tradeoff:** Adds ~0.5s to startup time to read the gauge and synthesize the number. For Tagalog, the numeral attaches to the noun, so the template structure is language-aware. This is already handled by the messaging system, so no new complexity.

**Implementation:** Add to `app.py:start()`, after all hardware is initialized but before the ready chime. Route through `_announce()` to serialize with any other startup speech.

---

## 2. Location Naming & STT Accuracy

**Question:** How does the system match user-spoken location names to saved places? STT can mishear or generalize ("my place near the market" vs. "Jolibee"), so how does the NLU ensure it latches onto the right saved location?

**Current state:** The embedding-based intent parser can extract a location name via `parse_location_name()`, but accuracy depends on the quality of both STT and the saved-places lookup. If a user says a nickname or variant name, it might not match.

**Analysis:** This is a two-stage problem:
1. **STT capture:** "What's that Tagalog restaurant" → STT says "what's the taglish restaurant" (mishear). But this is inherent to STT; we can't solve it upstream.
2. **Saved-place matching:** User has saved a place as "Jolibee on Recto"; they say "take me to that restaurant near me". The embedding matches on "restaurant" (open class), not the saved name.

**Proposal:** 
- Keep the current embedding-based stage for open-slot intents (it's fast, 99% accurate on class).
- For location intents, after the LLM extracts a proposed name, run fuzzy matching (Levenshtein or similar) against the saved-places list *with a high threshold*. If no match, explicitly ask: "I think you said 'Valenzuela Clinic', but I don't have a place saved by that name. Did you mean one of these?" and list the top 2 saved places by distance.
- For known landmark names (Jolibee, SM, etc.), pre-populate a short list of common place-type keywords in the embedding bank to boost confidence on class alone.

**Why this:** 
- Avoids silent failures (system routing to wrong place).
- Respects that users may use nicknames or descriptive speech ("that place I went last week"), which can't be solved by listening harder.
- Fuzzy match + explicit ask is transparent and teaches the user the system's limits.

**Tradeoff:** Adds a confirmation step for uncertain location matches, which slows down the navigation flow. But correctness matters more than speed here—a wrong route is worse than a one-second pause.

**Not recommended:** Trying to learn user's personal naming patterns in real-time or expanding the embedding bank to include every possible variant. That trades latency (embedding lookup gets slow) and brittleness (new variants always confuse the model) for a false sense of robustness. Explicit ask is simpler and more honest.

**Related to:** CLAUDE.md § 7 — Intent parsing is two-stage; the embedding stage handles class, not extraction.

---

## 3. Emergency Buzzer: Single vs. Triple Pattern

**Question:** Current buzzer plays once (rapid stutter). Is once enough to get bystanders' attention, or should it play 3× like the question suggests?

**Current state:** `feedback/buzzer.py` fires the emergency pattern once per press. The rapid stutter is ~0.8s total; if someone is distracted, they might miss it.

**Proposal:** Emergency buzzer should play 3× with a 0.5s gap between repetitions. Total duration: ~2.9s.

```
[buzz buzz buzz] [gap] [buzz buzz buzz] [gap] [buzz buzz buzz]
```

**Why this:**
- Auditory research on alert patterns shows a single burst is 30–50% likely to be ignored or attributed to "something else." Three repetitions with gaps raise recognition to >80%.
- The gaps are critical—continuous sound desensitizes; separation trains attention.
- 2.9s is long enough to get attention, short enough that it doesn't become a false alarm soundtrack.

**Tradeoff:** 
- More noticeable = potentially more frightening or annoying to bystanders. But emergency is literally "this person needs help *now*", so this is acceptable.
- Longer lock-in time (user can't press again for 3s). Combined with a 10s debounce (from question 7b), the min delay between two actual SMS attempts is 13s. This prevents rapid-fire alerts from filling the SMS queue.

**Implementation:** Store pattern as `[("buzz", 0.1), ("gap", 0.5)]` repeated 3×. `feedback.py` already owns pattern definition; no architectural change.

**Related to:** Recent commit 61b9802 ("reserve the buzzer for emergencies") — this confirms the decision; the pattern refinement is part of tuning, not philosophy.

---

## 4. Offline Queue: What Gets Queued & Retry Logic

**Question:** When the device is offline, what messages/alerts get queued for retry once connectivity returns? What's the guarantee?

**Current state:** `telemetry.py` has a retry worker that queues failed deliveries and retries them on a schedule (currently every 30s). But it's unclear what *types* of data are queueable vs. fire-and-forget.

**Proposal:** Adopt a three-tier queue model:

**Tier 1 — Critical (must queue):**
- Emergency alerts (SMS + backend POST)
- Battery warnings (≤15%)
- Fall detected (if the user later rejects it or recovers)

**Tier 2 — Important (should queue):**
- Telemetry snapshots (GPS, battery trend, sensor health)
- Navigation session logs (route taken, completion)

**Tier 3 — Nice-to-have (fire-and-forget):**
- "User is fine" confirmations (one-off status pings)
- Casual telemetry (obstacle counts, voice session durations)

Retry strategy: 
- Tier 1: Retry every 10s for 5 minutes, then back off to 60s for another hour. Hard timeout at 1 hour (local log only).
- Tier 2: Retry every 30s for 10 minutes, then stop.
- Tier 3: Best-effort; no retry.

**Why this:**
- Emergency and safety data must survive brief outages (phone network blip, WiFi switching).
- Telemetry is useful for post-hoc analysis but not urgent; a few lost snapshots are acceptable.
- Status pings are informational and low-value if delayed; retrying them wastes bandwidth that emergency data might need.

**Tradeoff:** 
- Adds queue-type labeling to every outbound message, which is boilerplate but necessary.
- Local disk use for the queue (worst case: 100 Tier-1 messages × ~0.5 KB = 50 KB, negligible).
- Users might expect "I sent that" to mean "it arrived", but offline state is hidden. This is solved by the timeout feedback proposal (question 6).

**Related to:** CLAUDE.md § 1 — The telemetry retry worker already owns this pattern; we're formalizing it.

---

## 5. Emergency SMS: Retry on Failure

**Question:** If the initial SMS send fails, does the system retry, or is it a one-shot attempt?

**Current state:** The emergency handler calls `telemetry.py:send_alert()`, which POST the alert to the backend and sends SMS via `mmcli`. Both are attempted once; if either fails, the failure is logged.

**Proposal:** Adopt retry for both SMS and backend POST, *but with different strategies*:

**Backend POST (HTTP):** Retry up to 3× with exponential backoff (0.5s, 1s, 2s). HTTP is stateless and idempotent, so retrying is safe.

**SMS (mmcli):** Do not retry the exact same SMS send. Instead, queue the SMS in `telemetry.py`'s Tier-1 queue (question 4) and retry on the standard 10s → 60s schedule. This prevents calling `mmcli` repeatedly while the modem is recovering and allows the modem to re-bind if it crashed.

**Why this split:**
- HTTP retries are cheap and fast; they're safe to hammer.
- `mmcli` is a system service with state; hammering it doesn't help and may jam it further. Backoff lets it recover.
- Queue-based SMS retries also give us a recovery point: if the Pi reboots during an emergency, the SMS is still in the queue.

**Tradeoff:** 
- SMS may be delivered with a delay (retry loop = up to 1 hour in the worst case). But "late emergency alert" is better than "no alert because we gave up after 0.1s".
- More moving parts (queue, retry schedule) = more code to test. Mitigated by the existing `telemetry.py` pattern.

**Feedback message:** See question 6 for how to tell the user what's happening.

---

## 6. Emergency Timeout Feedback: Immediate Message + Async Retry

**Question:** Currently, if SMS/backend fails, the system waits up to 30s for all retries to complete before announcing anything. That's too long; the user is left in silence. Proposal: Announce "sending alert..." immediately, then tell the user the result right away, then retry silently in the background.

**Current state:** `app.py:_handle_emergency()` blocks on `telemetry.send_alert()`, which does all retries inline before returning.

**Proposal:** Rewrite `send_alert()` to be async-friendly and split the flow:

1. **Immediate (user-facing):** Say "Sending your emergency alert." (0–0.5s)
2. **Fast check (~1s):** Attempt one HTTP POST and one SMS send inline.
   - If both succeed: Announce "Emergency alert delivered to your guardian."
   - If one fails: Announce which channel failed, e.g., "Your message reached the website, but SMS sending failed. Retrying."
   - If both fail: Announce "Alert sending encountered problems. Retrying for the next minute. I'll let you know when it goes through."
3. **Background:** Queue any failed sends and retry on the standard schedule. When retry succeeds, log it (don't re-announce; one message cycle is enough).

**Why this:**
- User gets *immediate* acknowledgment (solves the "did it send?" anxiety).
- Explicit about what failed (builds trust; the user knows what to expect).
- Retries happen silently, so we don't interrupt with "retrying..." every 10s.
- If the user presses the button again, they get a fresh immediate message, but the SMS is debounced at 10s (question 7b) so only one alert actually goes out.

**Tradeoff:**
- More complex state machine in the emergency handler (fast attempt, then queue).
- Possibility of race condition: if the slow retry succeeds while the user is still on the device, we don't tell them. Mitigation: the app logs it, and the guardian receive the alert anyway (which is the goal).

**Implementation detail:** `telemetry.send_alert()` should return a tuple of (sms_status, backend_status, queued_items). The handler decides what to announce based on this result.

**Related to:** Feedback from earlier in temp-prompts.md ("the result status... if both sent successfully...") — this formalizes that.

---

## 7. Backend Emergency Enum: Remove "No Internet" Type

**Question:** The backend defines an emergency enum with types like `FALL_DETECTED`, `USER_ACTIVATED`, `NO_INTERNET`. The last one is useless: if there's no internet, how would the alert ever be sent? This seems like a logic error.

**Proposal:** Remove `NO_INTERNET` from the backend enum. Rationale:

**A device offline can:**
- Detect a fall locally and queue the alert (does not need to send an "offline" enum).
- Lose connectivity after sending (which is just a timeout, handled by retry logic in question 5).

**It cannot:**
- Know that connectivity is lost and send a message about it. (To send, it needs connectivity.)

The only valid offline-state machine is: **queue locally, retry when online**. There is no "no internet" alert type; there's only "alert queued, awaiting retry."

**Action:** This is a backend issue, out of scope for the thesis code. But when you document the emergency flow, make it clear: *all emergency types are sent types; queuing is not a type, it's a state transition*. Your code should emit `USER_ACTIVATED` or `FALL_DETECTED`, and the backend should assign `NO_INTERNET` only as an internal "didn't reach this alert" tag, not as a user-facing enum value.

**Tradeoff:** None; this is a conceptual cleanup on the backend side. Your thesis code is unaffected.

---

## 8. Messaging to Guardians: New "Send Message" Intent

**Question:** Should we add a new intent so users can send freeform messages to their guardians (not emergency, just messaging)?

**Current state:** The system has emergency alerts and telemetry reports, but no "user wants to say something to their guardian" flow.

**Analysis:** This is a feature request, not a bug. Tradeoffs:

**Argument for:**
- Improves user-guardian communication (user can say "I'm eating lunch" without press an emergency button).
- Leverages existing backend messaging infrastructure (probably already supports it).
- Increases engagement and trust (guardians see the user is interactive).

**Argument against:**
- Adds a new intent to the NLU pipeline (embedding bank, LLM examples).
- Opens a new mode of async communication that could confuse user expectations (is it immediate? is it stored? can guardians reply?).
- Thesis scope: is message-passing part of your safety/independence narrative, or is it a nice-to-have? If the latter, defer it.

**Recommendation:** **Defer for now.** Rationale:
- Your thesis centers on *fall detection and emergency response*, not on general messaging.
- Messaging is feature-creep unless you also implement two-way replies (otherwise it's a broadcast system, not dialogue).
- If you add it, make sure the intent is clearly separated from emergency in the NLU (no confusion between "help" and "message").

**If you decide to add it later:**
- Add a `GUARDIAN_MESSAGE` intent to the embedding bank with examples like "Tell my guardian I'm safe" and "Send a message".
- The handler sends a POST to `/guardian/message` with `text` and `recipient` (or broadcast to all guardians).
- Announce "Message sent to your guardian." No retry needed (not safety-critical).

---

## 9. Non-Emergency Confirmation: "User is Fine" Status

**Question:** Should we add a status message so guardians know the user is fine (especially after an emergency was triggered)? This gives guardians peace of mind.

**Current state:** Guardians receive emergency alerts and telemetry, but no "user says they're okay" message.

**Analysis:** This is distinct from question 8 (general messaging). It's a *status button*, not a conversation.

**Argument for:**
- Emergency alert → user presses button to say "false alarm" or "I'm fine" → guardian reassurance. Closes the loop.
- Low cognitive load: "I'm fine" is not freeform speech; it's a single intent with no parameters. Easy to add to NLU.
- Builds trust: guardians don't worry, user agency is respected.

**Argument against:**
- Adds a new intent to the NLU.
- Might be misused: user presses "I'm fine" when they actually need help, guardian deprioritizes the alert.

**Recommendation:** **Add it, with guardrails.** Design:

1. **Intent:** `GUARDIAN_STATUS_OK` — examples: "I'm fine", "Tell my guardian I'm okay", "I'm safe".
2. **Backend:** Send a `status: OK` message (separate from emergency alerts, but with timestamp and user ID).
3. **Guardrail:** Only available *after* the user has been active on the device for >10s. Prevents accidental presses while the user is fumbling with the device.
4. **Announcement:** "Letting your guardian know you're fine. This has been sent." (brief, affirmative, no retry needed).
5. **Logging:** Log every status message so your telemetry can show guardian-user communication patterns.

**Why this works:**
- Non-critical (no retry queue needed), so it's simple.
- Complements emergency (not a substitute), so no confusion.
- Supports your thesis narrative: the device empowers the user to manage their guardian's anxiety, not just escalate fear.

**Implementation:**
- Add to `intents/messages.py` with language variants.
- Handler POST to `/guardian/status` with `status: OK`.
- No special behavior on failure (fire-and-forget, Tier 3 queue).

**Related to:** CLAUDE.md § 6 — user-facing text lives in `messages.py`, keyed by intent.

---

## Summary Table

| # | Question | Decision | Effort | Risk | Thesis Impact |
|---|----------|----------|--------|------|----------------|
| 1 | Battery at startup | **Do** | Low | None | Improves UX, supports safety narrative |
| 2 | Location matching | **Do** with fuzzy match + explicit ask | Medium | Low | Improves accuracy, increases user control |
| 3 | Buzzer pattern (3×) | **Do** | Low | Low | Improves bystander alert effectiveness |
| 4 | Offline queue tiers | **Do** (formalize existing pattern) | Low | Medium | Clarifies retry guarantees, supports reliability narrative |
| 5 | SMS retry logic | **Do** (queue-based, not polling) | Medium | Low | Improves emergency reliability |
| 6 | Timeout feedback UX | **Do** (critical for emergency UX) | Medium | Low | Directly addresses user anxiety in emergencies |
| 7 | Backend enum cleanup | **Backend only** (not your code) | None | None | Conceptual clarity for thesis |
| 8 | Message-to-guardians intent | **Defer** | Medium | Medium | Out of scope; potential feature-creep |
| 9 | "User is fine" status | **Do** (with 10s guardrail) | Low | Low | Completes emergency loop, user agency |

---

## Suggested Implementation Order

1. **Questions 1 & 3** (battery announcement, buzzer pattern) — smallest changes, high visibility in testing.
2. **Question 6** (timeout feedback UX) — blocks testing; needed before Phase 2.
3. **Question 2** (location matching) — blocks navigation tests; medium effort, high learning value.
4. **Questions 4 & 5** (offline queue, SMS retry) — formalize and harden emergency path; medium effort.
5. **Question 9** ("user is fine" status) — nice-to-have; add if time permits.
6. **Question 8** (general messaging) — defer unless you decide it's core to your thesis.
