"""Empirical probe: benchmark a local LLM as an NLU engine on the Pi 5.

This is a *test*, not a driver. We want real numbers before committing to
LLM NLU:

- How much RAM does the Ollama process use with the model loaded?
- What is per-query latency? Cold (first) vs warm (subsequent)?
- Does the JSON output actually parse and match what we want?
- Does latency degrade when GraphHopper + Photon are also running?

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

SYSTEM_PROMPT = """You are the intent parser for a wearable voice assistant. Given a user's spoken command, return ONLY a JSON object matching this exact schema:

{
  "intent": "navigate_to" | "location_query" | "navigation_stop" | "navigation_repeat" | "emergency" | "device_status" | "time_query" | "unknown",
  "parameters": {
    "location": string (only for navigate_to),
    "nearest": boolean (only for navigate_to),
    "status_field": "battery" | "gps" | "signal" (only for device_status)
  }
}

Rules:
- Only include parameters relevant to the intent; omit others.
- For navigate_to, "location" is the destination the user said, stripped of navigation phrases like "take me to".
- If the user's command doesn't fit any intent, return {"intent": "unknown", "parameters": {}}.

Examples:
User: "Navigate to SM Lipa"
Output: {"intent": "navigate_to", "parameters": {"location": "SM Lipa", "nearest": false}}

User: "Guide me to the nearest hospital"
Output: {"intent": "navigate_to", "parameters": {"location": "hospital", "nearest": true}}

User: "Where am I?"
Output: {"intent": "location_query", "parameters": {}}

User: "What's my current address?"
Output: {"intent": "location_query", "parameters": {}}

User: "Cancel navigation"
Output: {"intent": "navigation_stop", "parameters": {}}

User: "Repeat last instruction"
Output: {"intent": "navigation_repeat", "parameters": {}}

User: "I need help immediately"
Output: {"intent": "emergency", "parameters": {}}

User: "How much battery is left?"
Output: {"intent": "device_status", "parameters": {"status_field": "battery"}}

User: "What time is it?"
Output: {"intent": "time_query", "parameters": {}}

User: "Tell me a joke"
Output: {"intent": "unknown", "parameters": {}}
"""

TEST_TRANSCRIPTS = [
    # Navigate_to variations
    "Navigate to SM Lipa",
    "Take me to Jollibee",
    "Guide me to the nearest hospital",
    "How do I get to the pharmacy",
    "Bring me to school",

    # Location query variations
    "Where am I?",
    "What's my current address",
    "Tell me my location",

    # Navigation control
    "Cancel navigation",
    "Stop the trip",
    "Repeat the last instruction",
    "Say that again",

    # Emergency
    "Help me, this is an emergency",
    "I need help now",
    "SOS",

    # Device status
    "How much battery do I have left",
    "Is the GPS connected",

    # Time
    "What time is it",

    # Should fall through to unknown
    "Play some music",
    "Send a text to my mom",

    # Tagalog samples (to see how it handles multilingual)
    "Dalhin mo ako sa Jollibee",
    "Nasaan ako",
    "Tulong! Emergency!",
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
        "format": "json",       # force JSON output
        "options": {"temperature": 0.0},   # deterministic
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


def main():
    print(f"Model: {MODEL}")
    print(f"Free RAM before loading model: {free_ram_mb()} MB")
    print(f"Warming up with a throwaway query...")

    warm_elapsed, _, _ = query("Hello")
    print(f"Cold query took {warm_elapsed:.2f}s")
    print(f"Free RAM after model loaded: {free_ram_mb()} MB")
    print()

    total_time = 0.0
    parse_failures = 0
    for i, text in enumerate(TEST_TRANSCRIPTS, 1):
        elapsed, parsed, raw = query(text)
        total_time += elapsed
        if parsed is None:
            parse_failures += 1
            marker = "❌ JSON parse failed"
            summary = raw[:80]
        else:
            marker = "✓"
            summary = json.dumps(parsed, ensure_ascii=False)
        print(f"[{i:2d}/{len(TEST_TRANSCRIPTS)}] ({elapsed:5.2f}s) {marker}")
        print(f"    in:  {text}")
        print(f"    out: {summary}")

    print()
    print(f"Summary for model: {MODEL}")
    print(f"  Total queries:       {len(TEST_TRANSCRIPTS)}")
    print(f"  JSON parse failures: {parse_failures}")
    print(f"  Cold query time:     {warm_elapsed:.2f}s")
    print(f"  Total time (warm):   {total_time:.1f}s")
    print(f"  Avg per query:       {total_time / len(TEST_TRANSCRIPTS):.2f}s")
    print(f"  Free RAM at end:     {free_ram_mb()} MB")


if __name__ == "__main__":
    main()
