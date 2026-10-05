#!/usr/bin/env bash
#
# Pre-load the NLU model into Ollama and pin it in RAM. Run by
# ollama-warmup.service at boot.
#
# This is a script rather than two ExecStart lines because the model name
# has to be **read from config.py**, not written here. The unit hardcoded
# `qwen3:1.7b` in two places while `config.NLU_MODEL` picks between that
# and `qwen3:4b` through the `NLU_LARGE_MODEL` switch. Flipping that
# switch left the unit waiting for a model nobody had pulled, then
# pinning the wrong one — the small model's 1.9 GB resident beside the
# large model's 3.2 GB on an 8 GB Pi, next to Whisper, YOLO and the
# embedding model. `config.py` claims "one switch sets the model, the
# request style and the warmup budget so they cannot be mismatched"; the
# deploy unit was the hole in that, and this closes it.
#
# Run by hand to check what it would do:
#     bash deploy/systemd/ollama-warmup.sh
set -euo pipefail

REPO="${REPO:-/home/cknrf/Desktop/thesis/IndepensenseSystem}"
PY="${PY:-$REPO/.venv/bin/python}"
OLLAMA="${OLLAMA:-http://127.0.0.1:11434}"

# The two waits have to add up to less than the unit's TimeoutStartSec
# (180), which bounds the whole start. 60 + 120 = 180 exactly, and the
# unit must kill us rather than the other way round only if something is
# badly wrong — otherwise curl is killed mid-load while it still believes
# it has time, which reads as a mysterious truncation rather than a
# timeout.
CATALOGUE_TIMEOUT_S="${CATALOGUE_TIMEOUT_S:-60}"
LOAD_TIMEOUT_S="${LOAD_TIMEOUT_S:-120}"

MODEL="$(PYTHONPATH="$REPO/src" "$PY" -c \
    'from indepensense.config import NLU_MODEL; print(NLU_MODEL)')"
[ -n "$MODEL" ] || { echo "could not read NLU_MODEL from config.py" >&2; exit 1; }
echo "warming $MODEL"

# Wait for Ollama to answer AND have this model catalogued. `--fail`
# returns non-zero on any HTTP error, so the loop keeps trying while
# Ollama returns 500 during start-up.
#
# Bounded, unlike the `until` loop this replaces. That one relied on the
# unit's TimeoutStartSec to break it, which it does — but after three
# silent minutes with nothing in the journal explaining why. A missing
# model is the single most likely cause and deserves to say so.
deadline=$(( SECONDS + CATALOGUE_TIMEOUT_S ))
until curl -sf "$OLLAMA/api/tags" | grep -q "$MODEL"; do
    if [ "$SECONDS" -ge "$deadline" ]; then
        echo "Ollama has no model '$MODEL' after ${CATALOGUE_TIMEOUT_S}s." >&2
        echo "config.NLU_MODEL selects it; pull it with: ollama pull $MODEL" >&2
        exit 1
    fi
    sleep 1
done

# One request with keep_alive=-1 pins it in RAM.
#
#   --fail-with-body : non-zero on HTTP 4xx/5xx, and print the body so
#                      `journalctl -u ollama-warmup` shows the real error
#   -S               : show errors even in silent mode
curl -sS --fail-with-body --max-time "$LOAD_TIMEOUT_S" \
    -X POST "$OLLAMA/api/generate" \
    -H 'Content-Type: application/json' \
    -d "{\"model\":\"$MODEL\",\"prompt\":\"ok\",\"keep_alive\":-1,\"stream\":false,\"options\":{\"num_predict\":4}}" \
    -o /dev/null

echo "$MODEL pinned in RAM"
