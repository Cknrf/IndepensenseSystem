"""Empirical probe: benchmark a local LLM as an NLU engine on the Pi 5.

Measures per-query latency, RAM usage, and semantic accuracy against a fixed
set of expected intent + slot values. Used to decide which model earns a
place in the final wearable.

Accuracy is reported **per language group** (English, Tagalog, adversarial)
as well as overall. A single blended number is not decision-useful here:
Tagalog is the system's priority language, so a model that scores well
overall by acing English while failing Tagalog must be rejected, and a
blended figure hides exactly that.

The system prompt is loaded from `prompts/nlu_system.md` at the project
root — kept out of code so it can be iterated without editing this file.

Prerequisites:
    curl -fsSL https://ollama.com/install.sh | sh
    ollama pull <model-name>

Run from repo root:
    # default model
    python -m indepensense.intents.tests.manual.llm_probe

    # or specify a different model — e.g. to re-run the old baseline
    python -m indepensense.intents.tests.manual.llm_probe qwen2.5:1.5b-instruct
"""
import json
import sys
import time

import requests

from indepensense.config import PROJECT_ROOT

OLLAMA_URL = "http://localhost:11434/api/generate"
# Kept in sync with `config.NLU_MODEL`. Override on the command line to
# benchmark other models — that is the point of this script.
DEFAULT_MODEL = "qwen3:1.7b"
MODEL = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_MODEL

# Qwen 3 is a hybrid reasoning model and emits a `<think>` block unless told
# otherwise, which wrecks both latency and the strict-JSON contract. Ollama
# rejects `think` on models that cannot reason (e.g. the Qwen 2.5 baseline we
# compare against), so we send it, detect rejection once, and fall back for
# the rest of the run rather than forcing the user to pass a flag.
_send_think = True

PROMPT_PATH = PROJECT_ROOT / "prompts" / "nlu_system.md"
SYSTEM_PROMPT = PROMPT_PATH.read_text()


# Test cases: (transcript, expected_intent, expected_slots).
# The checker compares intent equality and REQUIRED-slot equality
# (case-insensitive for strings). Extra slots the model adds are
# tolerated (the executor drops them for `unknown` and normalises
# them for `navigation.start`).
#
# Coverage aims:
# - Every intent has positive cases in both English and Tagalog.
# - "Adversarial" cases at the end verify the Phase 1 prompt
#   hardening: transcripts that a naive model would misclassify as
#   a specific intent when they should be `unknown`.
ENGLISH_CASES = [
    # --- navigation.start ---
    ("Navigate to SM Lipa",              "navigation.start", {"location": "SM Lipa", "nearest": False}),
    ("Take me to Jollibee",              "navigation.start", {"location": "Jollibee", "nearest": False}),
    ("Guide me to the nearest hospital", "navigation.start", {"location": "hospital", "nearest": True}),
    ("How do I get to the pharmacy",     "navigation.start", {"location": "pharmacy"}),
    ("Bring me to school",               "navigation.start", {"location": "school"}),

    # --- navigation.location ---
    ("Where am I?",                      "navigation.location", {}),
    ("What's my current address",        "navigation.location", {}),
    ("Tell me my location",              "navigation.location", {}),

    # --- navigation.stop ---
    ("Cancel navigation",                "navigation.stop", {}),
    ("Stop the trip",                    "navigation.stop", {}),

    # --- navigation.repeat ---
    ("Repeat the last instruction",      "navigation.repeat", {}),
    ("Say that again",                   "navigation.repeat", {}),

    # --- emergency.trigger ---
    ("Help me, this is an emergency",    "emergency.trigger", {}),
    ("I need help now",                  "emergency.trigger", {}),
    ("SOS",                              "emergency.trigger", {}),

    # --- device.status ---
    ("How much battery do I have left",  "device.status", {"status_field": "battery"}),
    ("Is the GPS connected",             "device.status", {"status_field": "gps"}),

    # --- system.time ---
    ("What time is it",                  "system.time", {}),

    # --- vision.describe ---
    ("What's around me",                 "vision.describe", {}),
    ("Describe my surroundings",         "vision.describe", {}),
    ("What do you see",                  "vision.describe", {}),

    # --- vision.read ---
    ("Read this",                        "vision.read", {}),
    ("What does this sign say",          "vision.read", {}),
    ("Read the menu for me",             "vision.read", {}),

    # --- system.language ---
    # A misclassification here is worse than most: if the model cannot
    # recognise a switch request, the user is stranded in a language they
    # may not want and has no settings screen to escape through.
    ("Switch to English",                "system.language", {"language": "en"}),
    ("Speak English please",             "system.language", {"language": "en"}),
    ("Switch to Tagalog",                "system.language", {"language": "tl"}),
    ("Can you speak Filipino",           "system.language", {"language": "tl"}),

    # --- unknown (clear non-commands) ---
    ("Play some music",                  "unknown", {}),
    ("Send a text to my mom",            "unknown", {}),

    # --- unknown, and that is the point: cloud-LLM territory ---
    # These are reasonable things to ask a voice assistant and are NOT
    # intents. `unknown` is the correct answer, not a failure — it is the
    # sole entry point to the cloud fallback (see intents/cloud.py). If
    # the model ever classified these as a real intent, the command would
    # be mishandled instead of answered.
    ("How tall is Mount Apo",            "unknown", {}),
    ("How many days until Christmas",    "unknown", {}),
    ("What is the capital of Japan",      "unknown", {}),

]

TAGALOG_CASES = [
    ("Dalhin mo ako sa Jollibee",                    "navigation.start",    {"location": "Jollibee"}),
    ("Puntahan mo ang pinakamalapit na ospital",     "navigation.start",    {"location": "ospital", "nearest": True}),
    ("Nasaan ako",                                    "navigation.location", {}),
    ("Nasaan ako ngayon",                             "navigation.location", {}),
    ("Ihinto ang navigation",                         "navigation.stop",     {}),
    ("Ulitin mo yung sinabi",                         "navigation.repeat",   {}),
    ("Tulong! Emergency!",                            "emergency.trigger",   {}),
    ("Ilan pa ang natitirang battery",                "device.status",       {"status_field": "battery"}),
    ("Anong oras na",                                 "system.time",         {}),
    ("Ano ang nakikita mo",                           "vision.describe",     {}),
    ("Basahin mo ito",                                "vision.read",         {}),
    ("Magpatugtog ka ng musika",                      "unknown",             {}),

    # --- system.language ---
    # The switch phrase is spoken in the language currently ACTIVE, so
    # Tagalog speech asking for English is the realistic case and the one
    # that must work. Note the target is the language asked FOR, not the
    # language being spoken.
    ("Lumipat sa Ingles",                             "system.language",     {"language": "en"}),
    ("Mag-Ingles ka naman",                           "system.language",     {"language": "en"}),
    ("Magsalita ka ng Tagalog",                       "system.language",     {"language": "tl"}),
    ("Tagalog na lang",                               "system.language",     {"language": "tl"}),

    # --- unknown, bound for the cloud fallback ---
    ("Gaano katangkad ang Bundok Apo",                "unknown",             {}),
    ("Ilang araw na lang bago mag-Pasko",             "unknown",             {}),

]

# Adversarial: verify Phase 1 prompt hardening. These are transcripts where a
# naive LLM might latch onto a keyword ("time", "help", "location") and pick
# the wrong intent. After the "prefer unknown when in doubt" prompt rewrite,
# these should all resolve as expected. English-only for now — the Tagalog
# equivalents are a known gap (see module docstring).
ADVERSARIAL_CASES = [
    # "time" in non-time-query context → unknown, not system.time
    ("sometime tomorrow",                "unknown", {}),
    ("one at a time please",             "unknown", {}),
    ("in a bit",                         "unknown", {}),

    # "help" in non-emergency context
    ("help me find the pharmacy",        "navigation.start", {"location": "pharmacy"}),
    ("how do I use this",                "unknown", {}),

    # "location" / "where" about a place, not the user
    ("where is Jollibee",                "unknown", {}),

    # Statements and chatter (not commands)
    ("the weather is nice today",        "unknown", {}),
    ("I'm feeling tired",                "unknown", {}),

    # Common Whisper hallucinations on silence / background noise
    ("you",                              "unknown", {}),
    ("thanks for watching",              "unknown", {}),
    ("okay",                             "unknown", {}),

    # A language NAME appearing in an utterance is not a request to
    # switch to it. The third case is the dangerous one: grabbing
    # "English" out of a destination would swallow a real navigation
    # command and send the user nowhere.
    ("How do you say hello in Tagalog",  "unknown", {}),
    ("Read this English sign",           "vision.read", {}),
    ("Take me to English Street",        "navigation.start", {"location": "English Street"}),
    ("I speak Tagalog at home",          "unknown", {}),
]

# (group, transcript, expected_intent, expected_slots). `group` drives the
# per-language breakdown in the summary.
TEST_CASES = (
    [("english", *case) for case in ENGLISH_CASES]
    + [("tagalog", *case) for case in TAGALOG_CASES]
    + [("adversarial", *case) for case in ADVERSARIAL_CASES]
)

GROUPS = ("english", "tagalog", "adversarial")


def free_ram_mb() -> int:
    """Return currently-free RAM in MB from /proc/meminfo."""
    with open("/proc/meminfo") as f:
        for line in f:
            if line.startswith("MemAvailable:"):
                kb = int(line.split()[1])
                return kb // 1024
    return -1


def query(text: str) -> tuple[float, dict | None, str]:
    """Send one transcript to Ollama. Return (elapsed_s, parsed_json_or_None, raw_response).

    Sends `think: False` for reasoning models. If Ollama rejects the flag
    (non-reasoning model), disables it for the remainder of the run and
    retries once. Without this the rejection would surface as an empty
    response on every case and look like a total accuracy collapse.
    """
    global _send_think

    payload = {
        "model": MODEL,
        "system": SYSTEM_PROMPT,
        "prompt": text,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.0},
    }
    if _send_think:
        payload["think"] = False

    t0 = time.time()
    response = requests.post(OLLAMA_URL, json=payload, timeout=60)
    elapsed = time.time() - t0

    try:
        body = response.json()
    except ValueError:
        return elapsed, None, response.text[:200]

    if response.status_code != 200:
        error = str(body.get("error", ""))
        if _send_think and "think" in error.lower():
            _send_think = False
            print(f"  note: {MODEL} rejected `think` — disabling it for the rest of this run")
            return query(text)
        return elapsed, None, f"HTTP {response.status_code}: {error[:150]}"

    raw = body.get("response", "")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = None
    return elapsed, parsed, raw


def score(
    result: dict | None,
    expected_intent: str,
    expected_slots: dict,
) -> tuple[bool, bool | None]:
    """Score a model output against expected values.

    Returns (intent_correct, slots_correct):
      - intent_correct: True if the intent matches exactly.
      - slots_correct:  True if every expected slot key is present with the
                        expected value. None when there are no expected slots
                        (i.e. slot correctness is not measured for that case).

    Extra slots the model returns are tolerated on any intent — the executor
    normalises them (e.g. drops all params for `unknown`). String comparisons
    are case-insensitive.
    """
    if result is None:
        return False, (False if expected_slots else None)

    intent_correct = result.get("intent") == expected_intent

    if not expected_slots:
        return intent_correct, None

    got_slots = result.get("parameters") or {}
    slots_correct = True
    for key, want in expected_slots.items():
        if key not in got_slots:
            slots_correct = False
            break
        got = got_slots[key]
        if isinstance(want, str) and isinstance(got, str):
            if want.lower() != got.lower():
                slots_correct = False
                break
        elif got != want:
            slots_correct = False
            break

    return intent_correct, slots_correct


def main():
    print(f"Model:  {MODEL}")
    print(f"Prompt: {PROMPT_PATH} ({len(SYSTEM_PROMPT)} chars)")
    print(f"Free RAM before loading model: {free_ram_mb()} MB")
    print("Warming up with a throwaway query...")

    cold_elapsed, _, _ = query("Hello")
    print(f"Cold query took {cold_elapsed:.2f}s")
    print(f"Free RAM after model loaded: {free_ram_mb()} MB")
    print()

    total_time = 0.0
    parse_failures = 0
    intent_correct_count = 0
    slots_correct_count = 0
    slots_measured_count = 0
    combined_correct_count = 0
    misses: list[tuple[str, str, str, dict, str]] = []   # (group, input, expected_intent, expected_slots, got)
    stats = {g: {"n": 0, "intent": 0, "combined": 0, "time": 0.0} for g in GROUPS}

    for i, (group, text, expected_intent, expected_slots) in enumerate(TEST_CASES, 1):
        elapsed, parsed, raw = query(text)
        total_time += elapsed
        stats[group]["n"] += 1
        stats[group]["time"] += elapsed

        if parsed is None:
            parse_failures += 1
            intent_ok = False
            slots_ok = False if expected_slots else None
            summary = raw[:80]
            marker = "❌ JSON parse failed"
        else:
            summary = json.dumps(parsed, ensure_ascii=False)
            intent_ok, slots_ok = score(parsed, expected_intent, expected_slots)
            if intent_ok and (slots_ok is None or slots_ok):
                marker = "✓ correct"
            elif intent_ok:
                marker = "△ intent ok, slots WRONG"
            else:
                marker = "✗ WRONG"

        if intent_ok:
            intent_correct_count += 1
            stats[group]["intent"] += 1
        if slots_ok is not None:
            slots_measured_count += 1
            if slots_ok:
                slots_correct_count += 1
        combined = intent_ok and (slots_ok is None or slots_ok)
        if combined:
            combined_correct_count += 1
            stats[group]["combined"] += 1
        else:
            misses.append((group, text, expected_intent, expected_slots, summary))

        print(f"[{i:2d}/{len(TEST_CASES)}] [{group:11s}] ({elapsed:5.2f}s) {marker}")
        print(f"    in:       {text}")
        print(f"    expected: intent={expected_intent}, slots={expected_slots}")
        print(f"    got:      {summary}")

    total = len(TEST_CASES)
    print()
    print(f"Summary for model: {MODEL}")
    print(f"  Total queries:       {total}")
    print(f"  JSON parse failures: {parse_failures}")
    print(f"  Intent accuracy:     {intent_correct_count}/{total} "
          f"({100 * intent_correct_count / total:.1f}%)")
    if slots_measured_count:
        print(f"  Slot accuracy:       {slots_correct_count}/{slots_measured_count} "
              f"({100 * slots_correct_count / slots_measured_count:.1f}%) "
              f"[measured on cases with expected slots]")
    print(f"  Combined (both ok):  {combined_correct_count}/{total} "
          f"({100 * combined_correct_count / total:.1f}%)")
    print(f"  Cold query time:     {cold_elapsed:.2f}s")
    print(f"  Total time (warm):   {total_time:.1f}s")
    print(f"  Avg per query:       {total_time / total:.2f}s")
    print(f"  Free RAM at end:     {free_ram_mb()} MB")
    print(f"  Thinking disabled:   {_send_think}")

    print()
    print("Per-group breakdown (Tagalog is the priority language):")
    for group in GROUPS:
        s = stats[group]
        if not s["n"]:
            continue
        print(f"  {group:12s} intent {s['intent']:2d}/{s['n']:2d} "
              f"({100 * s['intent'] / s['n']:5.1f}%)   "
              f"combined {s['combined']:2d}/{s['n']:2d} "
              f"({100 * s['combined'] / s['n']:5.1f}%)   "
              f"avg {s['time'] / s['n']:.2f}s")

    if misses:
        print()
        print(f"Failures ({len(misses)}):")
        for group, text, expected_intent, expected_slots, got in misses:
            print(f"  [{group}] '{text}'")
            print(f"    expected: intent={expected_intent}, slots={expected_slots}")
            print(f"    got:      {got}")


if __name__ == "__main__":
    main()
