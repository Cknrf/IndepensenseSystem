"""Manual test: make real calls to the cloud LLM and measure them.

Confirms three things a unit test cannot, because they need the network
and a live key:

  1. **The key works.** Reads it exactly the way the runtime does, so a
     wrong variable name or an unloaded `.env` fails here rather than
     during a demo.
  2. **Real latency from where you actually are.** Reports cold vs warm
     separately. Cold includes the TLS handshake — about three round
     trips, which is ~0.75 s against an EU-hosted provider from the
     Philippines. Warm reuses the socket. The gap between the two is the
     value of connection reuse, measured rather than assumed.
  3. **Answer quality, including Tagalog.** Tagalog is low-resource for
     most providers and Mistral's quality there is unmeasured. Read the
     answers, don't just check they arrived.

Setup:
    cp .env.example .env
    # paste your key into INDEPENSENSE_CLOUD_API_KEY

Run from repo root:
    python -m indepensense.intents.tests.manual.cloud_probe

    # Just one language
    python -m indepensense.intents.tests.manual.cloud_probe --language tl

    # Try a different model
    python -m indepensense.intents.tests.manual.cloud_probe --model mistral-large-latest

What to look for
----------------

**Latency.** Warm calls are what the user experiences, since the socket
stays open for the life of the process. Add ~4-6 s for the rest of the
chain (Tagalog STT, local NLU, Piper) to get the real
press-to-answer time. If warm calls exceed ~3 s, lower
`CLOUD_LLM_MAX_TOKENS` before considering a different provider —
generation time scales with output length.

**Length.** Answers over ~40 words will be truncated by
`CLOUD_MAX_RESPONSE_CHARS` mid-sentence, which sounds broken when
spoken. If that happens often, the system prompt needs tightening rather
than the cap raising.

**Markdown.** Any asterisk, bullet or numbered list in the output is a
bug: Piper reads those aloud as literal characters. The probe flags them.
"""
import argparse
import os
import time

from indepensense.config import (
    CLOUD_LLM_API_KEY_ENV,
    CLOUD_LLM_MAX_TOKENS,
    CLOUD_LLM_MODEL,
    CLOUD_LLM_TIMEOUT_S,
    CLOUD_LLM_URL,
    CLOUD_MAX_RESPONSE_CHARS,
    ENV_FILE,
)
from indepensense.intents.mistral import MistralAnswerer

# Questions a user might plausibly ask that no intent covers, which is
# exactly what reaches this path. Two factual, one local-knowledge, one
# that should be refused rather than invented.
QUESTIONS = {
    "en": [
        "How tall is Mount Apo",
        "How many days are there in February 2028",
        "What is the jeepney fare for a short ride in Manila",
        "What is my sister's phone number",
    ],
    "tl": [
        "Gaano katangkad ang Bundok Apo",
        "Ilang araw ang Pebrero sa taong 2028",
        "Magkano ang pamasahe sa jeep sa Manila",
        "Ano ang numero ng telepono ng kapatid ko",
    ],
}

# Anything Piper would read out as a literal character.
_MARKDOWN_MARKERS = ("*", "_", "#", "`", "- ", "1.", "•")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--language", choices=("en", "tl", "both"), default="both")
    ap.add_argument("--model", default=CLOUD_LLM_MODEL)
    args = ap.parse_args()

    api_key = os.environ.get(CLOUD_LLM_API_KEY_ENV)
    if not api_key:
        print(f"ERROR: {CLOUD_LLM_API_KEY_ENV} is not set.")
        print()
        print(f"  config.py loads secrets from: {ENV_FILE}")
        print(f"  exists: {ENV_FILE.exists()}")
        print()
        print("  Fix with:")
        print("    cp .env.example .env")
        print(f"    # then set {CLOUD_LLM_API_KEY_ENV}=... in .env")
        raise SystemExit(1)

    print(f"model     : {args.model}")
    print(f"endpoint  : {CLOUD_LLM_URL}")
    print(f"max_tokens: {CLOUD_LLM_MAX_TOKENS}   timeout: {CLOUD_LLM_TIMEOUT_S}s")
    print(f"key       : ...{api_key[-4:]} (from {'.env' if ENV_FILE.exists() else 'environment'})")

    answerer = MistralAnswerer(
        api_key=api_key,
        model=args.model,
        url=CLOUD_LLM_URL,
        timeout_s=CLOUD_LLM_TIMEOUT_S,
        max_tokens=CLOUD_LLM_MAX_TOKENS,
    )

    languages = ("en", "tl") if args.language == "both" else (args.language,)
    timings: list[tuple[str, float]] = []
    failures = 0

    try:
        for language in languages:
            print()
            print("=" * 70)
            print(f"  {language}")
            print("=" * 70)

            for index, question in enumerate(QUESTIONS[language]):
                started = time.monotonic()
                result = answerer.answer(question, language)
                elapsed = time.monotonic() - started

                # The very first call of the whole run pays the TLS
                # handshake; everything after reuses the socket.
                phase = "cold" if not timings else "warm"
                timings.append((phase, elapsed))

                print()
                print(f"  Q: {question}")
                if result.reason != "ok":
                    failures += 1
                    print(f"  ! FAILED ({result.reason}) after {elapsed:.2f}s")
                    continue

                text = result.text
                print(f"  A: {text}")
                print(f"     {elapsed:.2f}s [{phase}]  {len(text)} chars, "
                      f"{len(text.split())} words")

                if len(text) > CLOUD_MAX_RESPONSE_CHARS:
                    print(f"     WARNING: over {CLOUD_MAX_RESPONSE_CHARS} chars — "
                          f"the executor will truncate this mid-sentence")
                found = [m for m in _MARKDOWN_MARKERS if m in text]
                if found:
                    print(f"     WARNING: markdown-ish characters {found} — "
                          f"Piper reads these aloud literally")
    finally:
        answerer.close()

    _summarise(timings, failures)


def _summarise(timings, failures: int) -> None:
    print()
    print("=" * 70)
    print("  Summary")
    print("=" * 70)

    if not timings:
        print("  No calls completed.")
        return

    cold = [t for phase, t in timings if phase == "cold"]
    warm = [t for phase, t in timings if phase == "warm"]

    print(f"  calls    : {len(timings)}  ({failures} failed)")
    if cold:
        print(f"  cold call: {cold[0]:.2f}s  (includes TLS handshake)")
    if warm:
        print(f"  warm     : min {min(warm):.2f}s  "
              f"avg {sum(warm) / len(warm):.2f}s  max {max(warm):.2f}s")
    if cold and warm:
        saved = cold[0] - (sum(warm) / len(warm))
        print(f"  handshake: ~{saved:.2f}s, paid once per process thanks to "
              f"connection reuse")

    if warm:
        typical = sum(warm) / len(warm)
        print()
        print(f"  Press-to-answer for the user is roughly {typical + 5:.0f}s: "
              f"{typical:.1f}s here")
        print("  plus ~4-6s for Tagalog STT, local NLU and Piper. The "
              "'thinking' cue covers it.")
        if typical > 3.0:
            print()
            print("  Warm calls are slow. Lower CLOUD_LLM_MAX_TOKENS before")
            print("  considering another provider — output length drives this")
            print("  far more than geography does.")

    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
