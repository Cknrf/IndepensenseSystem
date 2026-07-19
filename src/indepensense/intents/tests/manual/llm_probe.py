"""Empirical probe: benchmark a local LLM as an NLU engine on the Pi 5.

Measures per-query latency, RAM usage, and semantic accuracy against a fixed
set of expected intent + slot values. Used to decide whether Qwen 2.5 1.5B,
3B, or something else earns a place in the final wearable.

The system prompt is loaded from `prompts/nlu_system.md` at the project
root — kept out of code so it can be iterated without editing this file.

Prerequisites:
    curl -fsSL https://ollama.com/install.sh | sh
    ollama pull <model-name>

Run from repo root:
    # default model
    python -m indepensense.intents.tests.manual.llm_probe

    # or specify a different model
    python -m indepensense.intents.tests.manual.llm_probe qwen2.5:1.5b-instruct
"""
import json
import sys
import time

import requests

from indepensense.config import PROJECT_ROOT

OLLAMA_URL = "http://localhost:11434/api/generate"
DEFAULT_MODEL = "qwen2.5:3b-instruct"
MODEL = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_MODEL

PROMPT_PATH = PROJECT_ROOT / "prompts" / "nlu_system.md"
SYSTEM_PROMPT = PROMPT_PATH.read_text()


# Test cases with expected intent + expected slot values.
# The checker compares intent equality and REQUIRED-slot equality (case-
# insensitive for strings). Extra slots the model adds are tolerated.
TEST_CASES = [
    # navigation.start (English)
    ("Navigate to SM Lipa",              "navigation.start", {"location": "SM Lipa", "nearest": False}),
    ("Take me to Jollibee",              "navigation.start", {"location": "Jollibee", "nearest": False}),
    ("Guide me to the nearest hospital", "navigation.start", {"location": "hospital", "nearest": True}),
    ("How do I get to the pharmacy",     "navigation.start", {"location": "pharmacy"}),
    ("Bring me to school",               "navigation.start", {"location": "school"}),

    # navigation.location (English)
    ("Where am I?",                      "navigation.location", {}),
    ("What's my current address",        "navigation.location", {}),
    ("Tell me my location",              "navigation.location", {}),

    # navigation.stop (English)
    ("Cancel navigation",                "navigation.stop", {}),
    ("Stop the trip",                    "navigation.stop", {}),

    # navigation.repeat (English)
    ("Repeat the last instruction",      "navigation.repeat", {}),
    ("Say that again",                   "navigation.repeat", {}),

    # emergency.trigger (English)
    ("Help me, this is an emergency",    "emergency.trigger", {}),
    ("I need help now",                  "emergency.trigger", {}),
    ("SOS",                              "emergency.trigger", {}),

    # device.status (English)
    ("How much battery do I have left",  "device.status", {"status_field": "battery"}),
    ("Is the GPS connected",             "device.status", {"status_field": "gps"}),

    # system.time (English)
    ("What time is it",                  "system.time", {}),

    # unknown (English)
    ("Play some music",                  "unknown", {}),
    ("Send a text to my mom",            "unknown", {}),

    # Tagalog
    ("Dalhin mo ako sa Jollibee",                    "navigation.start",    {"location": "Jollibee"}),
    ("Puntahan mo ang pinakamalapit na ospital",     "navigation.start",    {"location": "ospital", "nearest": True}),
    ("Nasaan ako",                                    "navigation.location", {}),
    ("Nasaan ako ngayon",                             "navigation.location", {}),
    ("Ihinto ang navigation",                         "navigation.stop",     {}),
    ("Ulitin mo yung sinabi",                         "navigation.repeat",   {}),
    ("Tulong! Emergency!",                            "emergency.trigger",   {}),
    ("Ilan pa ang natitirang battery",                "device.status",       {"status_field": "battery"}),
    ("Anong oras na",                                 "system.time",         {}),
    ("Magpatugtog ka ng musika",                      "unknown",             {}),
]


def free_ram_mb() -> int:
    """Return currently-free RAM in MB from /proc/meminfo."""
    with open("/proc/meminfo") as f:
        for line in f:
            if line.startswith("MemAvailable:"):
                kb = int(line.split()[1])
                return kb // 1024
    return -1


def query(text: str) -> tuple[float, dict | None, str]:
    """Send one transcript to Ollama. Return (elapsed_s, parsed_json_or_None, raw_response)."""
    payload = {
        "model": MODEL,
        "system": SYSTEM_PROMPT,
        "prompt": text,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.0},
    }
    t0 = time.time()
    response = requests.post(OLLAMA_URL, json=payload, timeout=60)
    elapsed = time.time() - t0
    raw = response.json().get("response", "")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = None
    return elapsed, parsed, raw


def matches_expected(
    result: dict | None,
    expected_intent: str,
    expected_slots: dict,
) -> bool:
    """Check whether the model's output has the expected intent + required slots.

    Extra slots the model adds are tolerated. String comparisons are case-
    insensitive. Missing required slots or wrong intent fail.
    """
    if result is None:
        return False
    if result.get("intent") != expected_intent:
        return False
    got_slots = result.get("parameters") or {}
    for key, want in expected_slots.items():
        if key not in got_slots:
            return False
        got = got_slots[key]
        if isinstance(want, str) and isinstance(got, str):
            if want.lower() != got.lower():
                return False
        elif got != want:
            return False
    return True


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
    correct = 0
    misses: list[tuple[str, str, str]] = []   # (input, expected_intent, got_summary)

    for i, (text, expected_intent, expected_slots) in enumerate(TEST_CASES, 1):
        elapsed, parsed, raw = query(text)
        total_time += elapsed
        if parsed is None:
            parse_failures += 1
            marker = "❌ JSON parse failed"
            summary = raw[:80]
            is_correct = False
        else:
            summary = json.dumps(parsed, ensure_ascii=False)
            is_correct = matches_expected(parsed, expected_intent, expected_slots)
            marker = "✓ correct" if is_correct else "✗ WRONG"
        if is_correct:
            correct += 1
        else:
            misses.append((text, expected_intent, summary))
        print(f"[{i:2d}/{len(TEST_CASES)}] ({elapsed:5.2f}s) {marker}")
        print(f"    in:       {text}")
        print(f"    expected: intent={expected_intent}, slots={expected_slots}")
        print(f"    got:      {summary}")

    total = len(TEST_CASES)
    print()
    print(f"Summary for model: {MODEL}")
    print(f"  Total queries:       {total}")
    print(f"  JSON parse failures: {parse_failures}")
    print(f"  Correct:             {correct}/{total} ({100 * correct / total:.1f}%)")
    print(f"  Cold query time:     {cold_elapsed:.2f}s")
    print(f"  Total time (warm):   {total_time:.1f}s")
    print(f"  Avg per query:       {total_time / total:.2f}s")
    print(f"  Free RAM at end:     {free_ram_mb()} MB")

    if misses:
        print()
        print(f"Misclassifications ({len(misses)}):")
        for text, expected, got in misses:
            print(f"  '{text}'")
            print(f"    expected intent: {expected}")
            print(f"    got:             {got}")


if __name__ == "__main__":
    main()
