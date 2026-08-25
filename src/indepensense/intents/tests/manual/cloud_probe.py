"""Manual test: make real calls to the cloud LLM and measure them.

Confirms three things a unit test cannot, because they need the network
and a live key:

  1. **The key works.** Reads it exactly the way the runtime does, so a
     wrong variable name or an unloaded `.env` fails here rather than
     during a demo.
  2. **Real latency from where you actually are.** Reported per language
     and split cold vs warm. Cold includes the TLS handshake; warm reuses
     the socket. Measured from Manila against Mistral, the handshake is
     small enough (~0.2 s) to disappear into normal variation, so the
     summary only claims a figure when it can actually isolate one — an
     earlier version compared a cold English call against an average
     including Tagalog and reported a negative handshake.
  3. **Answer quality, including Tagalog.** Read the answers; do not just
     check they arrived. Observed on 2026-08-25: Mistral gave Mount Apo's
     height correctly in English (2,954 m) and incorrectly in Tagalog
     (2,983 m), with identical confidence, and quoted a flat jeepney fare
     in English against a route-dependent range in Tagalog. Refusals
     worked in both languages. A confidently wrong answer is
     indistinguishable from a correct one here, which is why this stays a
     manual test with a human reading the output.

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

**Correctness.** Nothing here can check it — that is the point of reading
the answers. Hallucinations are not deterministic, so run this more than
once; the same question can be answered differently, and differently per
language. This is why the cloud fallback is scoped as a convenience for
general questions and never as a source of truth: navigation, emergency
and obstacle detection are all local, and `unknown` is the only route to
the cloud.
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
    # (phase, language, seconds). Language matters for the summary: answer
    # length differs systematically between them, and generation time
    # tracks length.
    timings: list[tuple[str, str, float]] = []
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
                timings.append((phase, language, elapsed))

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

    print(f"  calls: {len(timings)}  ({failures} failed)")

    # Per language, because answer length differs systematically between
    # them and generation time tracks length. A blended average hides
    # that Tagalog is consistently the slower path.
    print()
    for language in ("en", "tl"):
        warm = [t for phase, lang, t in timings if phase == "warm" and lang == language]
        if not warm:
            continue
        print(f"  {language} warm: min {min(warm):.2f}s  "
              f"avg {sum(warm) / len(warm):.2f}s  max {max(warm):.2f}s  "
              f"({len(warm)} calls)")

    cold = [(lang, t) for phase, lang, t in timings if phase == "cold"]
    if cold:
        cold_language, cold_seconds = cold[0]
        print(f"  cold call: {cold_seconds:.2f}s [{cold_language}] "
              f"— includes the TLS handshake")

        # Compare against warm calls in the SAME language only. Comparing
        # a cold English call against an average that includes Tagalog
        # measures the difference in answer length, not the handshake, and
        # can come out negative — which it did before this was fixed.
        same = [
            t for phase, lang, t in timings
            if phase == "warm" and lang == cold_language
        ]
        if same:
            overhead = cold_seconds - min(same)
            if overhead > 0.05:
                print(f"  handshake: ~{overhead:.2f}s, paid once per process "
                      f"thanks to connection reuse")
            else:
                print("  handshake: too small to separate from normal "
                      "variation in this run")

    warm_all = [t for phase, _, t in timings if phase == "warm"]
    if warm_all:
        typical = sum(warm_all) / len(warm_all)
        print()
        print(f"  Press-to-answer for the user is roughly {typical + 5:.0f}s: "
              f"{typical:.1f}s here plus")
        print("  ~4-6s for Tagalog STT, local NLU and Piper. The 'thinking' "
              "cue covers it.")
        if typical > 3.0:
            print()
            print("  Warm calls are slow. Lower CLOUD_LLM_MAX_TOKENS before")
            print("  considering another provider — output length drives this")
            print("  far more than geography does.")

    print()
    print("  Read the answers, do not just count them. A confidently wrong")
    print("  answer looks identical to a correct one here, and the same")
    print("  question can get different answers in each language.")

    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
