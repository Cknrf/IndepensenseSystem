"""Empirical probe: benchmark a local LLM as an NLU engine on the Pi 5.

Measures per-query latency, RAM usage, and now **semantic accuracy** against
a fixed set of expected intent + slot values. This is the tool we use to
decide whether Qwen 2.5 1.5B, 3B, or something else earns a place in the
final wearable.

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

OLLAMA_URL = "http://localhost:11434/api/generate"
DEFAULT_MODEL = "qwen2.5:3b-instruct"
MODEL = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_MODEL

SYSTEM_PROMPT = """You are the intent parser for a wearable voice assistant used by visually-impaired users in the Philippines. Given a user's spoken command in English or Tagalog, return ONLY a JSON object matching this exact schema:

{
  "intent": "navigate_to" | "location_query" | "navigation_stop" | "navigation_repeat" | "emergency" | "device_status" | "time_query" | "unknown",
  "parameters": {
    "location": string (only for navigate_to),
    "nearest": boolean (only for navigate_to),
    "status_field": "battery" | "gps" | "signal" (only for device_status)
  }
}

RULES:
1. Return the intent that best matches what the user actually asked for.
2. If the command does not clearly match one of the listed intents, return {"intent": "unknown", "parameters": {}}. Prefer "unknown" over guessing — a wrong action is worse than doing nothing on this device.
3. Only include parameters that apply to the chosen intent; omit unrelated keys.
4. The user may speak in English or Tagalog. Treat both languages equally.
5. For navigate_to, "location" is the destination string with leading navigation phrases (e.g. "take me to", "dalhin mo ako sa") stripped.
6. For navigate_to, set "nearest": true only if the user said "nearest", "closest", "pinakamalapit", or an equivalent modifier. Otherwise "nearest": false.

EXAMPLES:

--- navigate_to ---
User: "Navigate to SM Lipa"
Output: {"intent": "navigate_to", "parameters": {"location": "SM Lipa", "nearest": false}}

User: "Take me to Jollibee"
Output: {"intent": "navigate_to", "parameters": {"location": "Jollibee", "nearest": false}}

User: "Guide me to the nearest hospital"
Output: {"intent": "navigate_to", "parameters": {"location": "hospital", "nearest": true}}

User: "How do I get to the pharmacy"
Output: {"intent": "navigate_to", "parameters": {"location": "pharmacy", "nearest": false}}

User: "Bring me to school"
Output: {"intent": "navigate_to", "parameters": {"location": "school", "nearest": false}}

User: "Dalhin mo ako sa Jollibee"
Output: {"intent": "navigate_to", "parameters": {"location": "Jollibee", "nearest": false}}

User: "Puntahan mo ang ospital"
Output: {"intent": "navigate_to", "parameters": {"location": "ospital", "nearest": false}}

User: "Gabayan mo ako papuntang pinakamalapit na botika"
Output: {"intent": "navigate_to", "parameters": {"location": "botika", "nearest": true}}

--- location_query ---
User: "Where am I?"
Output: {"intent": "location_query", "parameters": {}}

User: "What's my current address?"
Output: {"intent": "location_query", "parameters": {}}

User: "Tell me my location"
Output: {"intent": "location_query", "parameters": {}}

User: "Nasaan ako?"
Output: {"intent": "location_query", "parameters": {}}

User: "Nasaan ako ngayon?"
Output: {"intent": "location_query", "parameters": {}}

User: "Ano ang address ko?"
Output: {"intent": "location_query", "parameters": {}}

--- navigation_stop ---
User: "Cancel navigation"
Output: {"intent": "navigation_stop", "parameters": {}}

User: "Stop the trip"
Output: {"intent": "navigation_stop", "parameters": {}}

User: "End navigation"
Output: {"intent": "navigation_stop", "parameters": {}}

User: "Ihinto ang navigation"
Output: {"intent": "navigation_stop", "parameters": {}}

User: "Kanselahin ang direksyon"
Output: {"intent": "navigation_stop", "parameters": {}}

--- navigation_repeat ---
User: "Repeat the last instruction"
Output: {"intent": "navigation_repeat", "parameters": {}}

User: "Say that again"
Output: {"intent": "navigation_repeat", "parameters": {}}

User: "Can you repeat?"
Output: {"intent": "navigation_repeat", "parameters": {}}

User: "Ulitin mo yung sinabi"
Output: {"intent": "navigation_repeat", "parameters": {}}

User: "Pakiulit"
Output: {"intent": "navigation_repeat", "parameters": {}}

--- emergency ---
User: "Help me, this is an emergency"
Output: {"intent": "emergency", "parameters": {}}

User: "I need help now"
Output: {"intent": "emergency", "parameters": {}}

User: "SOS"
Output: {"intent": "emergency", "parameters": {}}

User: "Tulong!"
Output: {"intent": "emergency", "parameters": {}}

User: "Kailangan ko ng tulong"
Output: {"intent": "emergency", "parameters": {}}

--- device_status ---
User: "How much battery do I have left"
Output: {"intent": "device_status", "parameters": {"status_field": "battery"}}

User: "Is the GPS connected"
Output: {"intent": "device_status", "parameters": {"status_field": "gps"}}

User: "How's the signal"
Output: {"intent": "device_status", "parameters": {"status_field": "signal"}}

User: "Ilan pa ang natitirang battery?"
Output: {"intent": "device_status", "parameters": {"status_field": "battery"}}

--- time_query ---
User: "What time is it"
Output: {"intent": "time_query", "parameters": {}}

User: "What's the time"
Output: {"intent": "time_query", "parameters": {}}

User: "Anong oras na?"
Output: {"intent": "time_query", "parameters": {}}

--- unknown (commands that do NOT fit any listed intent) ---
User: "Play some music"
Output: {"intent": "unknown", "parameters": {}}

User: "Send a text to my mom"
Output: {"intent": "unknown", "parameters": {}}

User: "Tell me a joke"
Output: {"intent": "unknown", "parameters": {}}

User: "Magpatugtog ka ng musika"
Output: {"intent": "unknown", "parameters": {}}

User: "What's the weather?"
Output: {"intent": "unknown", "parameters": {}}
"""


# Test cases with expected intent + expected slot values.
# The checker compares intent equality and REQUIRED-slot equality (case-
# insensitive for strings). Extra slots the model adds are tolerated.
TEST_CASES = [
    # navigate_to (English)
    ("Navigate to SM Lipa", "navigate_to", {"location": "SM Lipa", "nearest": False}),
    ("Take me to Jollibee", "navigate_to", {"location": "Jollibee", "nearest": False}),
    ("Guide me to the nearest hospital", "navigate_to", {"location": "hospital", "nearest": True}),
    ("How do I get to the pharmacy", "navigate_to", {"location": "pharmacy"}),
    ("Bring me to school", "navigate_to", {"location": "school"}),

    # location_query (English)
    ("Where am I?", "location_query", {}),
    ("What's my current address", "location_query", {}),
    ("Tell me my location", "location_query", {}),

    # navigation_stop (English)
    ("Cancel navigation", "navigation_stop", {}),
    ("Stop the trip", "navigation_stop", {}),

    # navigation_repeat (English)
    ("Repeat the last instruction", "navigation_repeat", {}),
    ("Say that again", "navigation_repeat", {}),

    # emergency (English)
    ("Help me, this is an emergency", "emergency", {}),
    ("I need help now", "emergency", {}),
    ("SOS", "emergency", {}),

    # device_status (English)
    ("How much battery do I have left", "device_status", {"status_field": "battery"}),
    ("Is the GPS connected", "device_status", {"status_field": "gps"}),

    # time_query (English)
    ("What time is it", "time_query", {}),

    # unknown (English)
    ("Play some music", "unknown", {}),
    ("Send a text to my mom", "unknown", {}),

    # Tagalog
    ("Dalhin mo ako sa Jollibee", "navigate_to", {"location": "Jollibee"}),
    ("Puntahan mo ang pinakamalapit na ospital", "navigate_to", {"location": "ospital", "nearest": True}),
    ("Nasaan ako", "location_query", {}),
    ("Nasaan ako ngayon", "location_query", {}),
    ("Ihinto ang navigation", "navigation_stop", {}),
    ("Ulitin mo yung sinabi", "navigation_repeat", {}),
    ("Tulong! Emergency!", "emergency", {}),
    ("Ilan pa ang natitirang battery", "device_status", {"status_field": "battery"}),
    ("Anong oras na", "time_query", {}),
    ("Magpatugtog ka ng musika", "unknown", {}),
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
    print(f"Model: {MODEL}")
    print(f"Free RAM before loading model: {free_ram_mb()} MB")
    print(f"Warming up with a throwaway query...")

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
