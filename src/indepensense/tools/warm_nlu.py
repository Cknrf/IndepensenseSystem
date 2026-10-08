"""Pin the NLU model in Ollama and prefill its system prompt, once, at boot.

    python -m indepensense.tools.warm_nlu

Run by `ollama-warmup.service`. Waits for Ollama to list the configured
model, then sends the parser's own warmup request — the same model,
system prompt and options a real query uses — with `keep_alive=-1` so the
model stays resident.

**Why the app's warmup was still 54 s with the model already pinned.**
The warmup unit used to send `"ok"` with no system prompt through curl.
That loaded the weights (1.9 GB off the SD card, ~70 s) but built no
prefix cache for the 2,512-token system prompt, so the app evaluated it
itself at the end of every boot: 54.5 s on the Pi. Ollama keeps the
prefix cache per loaded model across requests and processes — measured
on the Pi, the same request again evaluated those tokens in 0.2 s and
the app's warmup fell to ~3 s. Doing the prefill here moves it off the
app's path and onto a unit that runs in parallel, while the app is still
I/O-bound loading models.

**Why Python and not the shell script it replaces.** The request has to
be byte-for-byte the one the parser sends, or Ollama warms a prefix
nobody uses. `OllamaIntentParser.warm_up` builds it from the same method
`parse` does, so the two cannot drift — which a hand-written curl body
could, silently, the day the prompt file or the request style changed.
Reading `config.NLU_MODEL` for free is the other half: the script had to
shell out to Python for that anyway.

Exit status: 0 when the model is warm, 1 otherwise, so `systemctl status
ollama-warmup` says which. The app re-warms on its own at the end of its
load regardless; a failure here costs the user that time, not the voice
interface.
"""
from __future__ import annotations

import argparse
import sys
import time

from indepensense.config import (
    NLU_COMPACT_PREFILL,
    NLU_MODEL,
    NLU_PROMPT_PATH,
    NLU_TIMEOUT_S,
    NLU_WARMUP_TIMEOUT_S,
    OLLAMA_URL,
)
from indepensense.intents.parser import OllamaIntentParser

# How long to wait for Ollama to answer *and* list the model. Bounded,
# with the reason printed: a model nobody pulled used to hold the unit
# for its whole TimeoutStartSec with nothing in the journal saying why.
CATALOGUE_TIMEOUT_S = 60.0
CATALOGUE_POLL_S = 1.0


def wait_for_model(
    ollama_url: str, model: str, timeout_s: float, poll_s: float = CATALOGUE_POLL_S,
) -> bool:
    """True once `GET /api/tags` lists `model`; False at the deadline.

    Ollama answers errors while it is still starting, and a connection
    refused before that — both are "not yet", not failures.
    """
    import requests  # lazy: keeps the module importable off-device

    deadline = time.monotonic() + timeout_s
    while True:
        try:
            response = requests.get(f"{ollama_url}/api/tags", timeout=5.0)
            if response.ok and any(
                entry.get("name") == model or entry.get("model") == model
                for entry in response.json().get("models", [])
            ):
                return True
        except (requests.RequestException, ValueError):
            pass
        if time.monotonic() >= deadline:
            return False
        time.sleep(poll_s)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--catalogue-timeout", type=float, default=CATALOGUE_TIMEOUT_S,
                        help="seconds to wait for Ollama to list the model")
    parser.add_argument("--warmup-timeout", type=float, default=NLU_WARMUP_TIMEOUT_S,
                        help="seconds allowed for the load + prefill request")
    args = parser.parse_args(argv)

    print(f"warming {NLU_MODEL} at {OLLAMA_URL}", flush=True)
    if not wait_for_model(OLLAMA_URL, NLU_MODEL, args.catalogue_timeout):
        print(
            f"Ollama has no model '{NLU_MODEL}' after {args.catalogue_timeout:.0f}s. "
            f"config.NLU_MODEL selects it; pull it with: ollama pull {NLU_MODEL}",
            file=sys.stderr, flush=True,
        )
        return 1

    llm = OllamaIntentParser(
        model=NLU_MODEL,
        ollama_url=OLLAMA_URL,
        prompt_path=NLU_PROMPT_PATH,
        timeout_s=NLU_TIMEOUT_S,
        warmup=False,
        compact_prefill=NLU_COMPACT_PREFILL,
    )
    if not llm.warm_up(args.warmup_timeout):
        return 1
    print(f"{NLU_MODEL} pinned in RAM with its system prompt cached", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
