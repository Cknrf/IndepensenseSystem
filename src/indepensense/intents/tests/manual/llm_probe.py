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

    # the request style `config.NLU_LARGE_MODEL` switches to: compact-JSON
    # prefill instead of JSON mode (see intents/parser.py). Measure 4B this
    # way — in JSON mode it pretty-prints and the latency is not the one
    # the device would see.
    python -m indepensense.intents.tests.manual.llm_probe qwen3:4b --prefill

With no model named, the model and request style are whatever `config.py`
selects, so a bare run measures exactly what the device runs.

Cloud mode
----------

`--cloud` measures a Mistral model through the same test set and the same
scoring, which is the entire point: the local baseline and the candidate
have to be compared on identical cases or the comparison is worthless.

    # the pinned config.NLU_CLOUD_MODEL
    python -m indepensense.intents.tests.manual.llm_probe --cloud

    # or any other Mistral model, e.g. the cheap comparison
    python -m indepensense.intents.tests.manual.llm_probe ministral-8b-2512 --cloud

Needs `INDEPENSENSE_CLOUD_API_KEY` in the environment.

Measuring the latency the device actually sees
----------------------------------------------

`--modem` sends every cloud request out of the SIM7600 instead of
whatever the routing table prefers:

    python -m indepensense.intents.tests.manual.llm_probe --cloud --modem
    python -m indepensense.intents.tests.manual.llm_probe --cloud --modem=wwan1

**Without it, a run at a desk measures WiFi.** Both interfaces hold a
default route and `wlan0` wins on metric (600 against `wwan0`'s 700), so
the bench number is not the field number — measured 577 ms against
743 ms on 2026-10-12. Accuracy is route-independent; latency is not, so
`--modem` matters for the second and not the first.

The bind is `SO_BINDTODEVICE`, which works unprivileged here — no sudo,
no `ip rule`, and nothing that could drop an SSH session the way
re-prioritising the default route or disabling WiFi would. Source-address
binding is *not* enough on its own: the route lookup for the destination
still selects `wlan0`, and the kernel refuses the mismatched source with
`EADDRNOTAVAIL`. The interface is named in the summary so a saved run
records which path produced it.

Cloud mode also reports prompt-cache effectiveness per query, since the
cached fraction of the prefix is what makes the running cost tolerable.
"""
import json
import os
import sys
import time

import requests

from indepensense.config import (
    CLOUD_LLM_API_KEY_ENV,
    CLOUD_LLM_URL,
    NLU_CLOUD_MODEL,
    NLU_CLOUD_PROMPT_PATH,
    NLU_CLOUD_TIMEOUT_S,
    NLU_COMPACT_PREFILL,
    NLU_MODEL,
    NLU_WARMUP_TIMEOUT_S,
    PROJECT_ROOT,
)

OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_CHAT_URL = "http://localhost:11434/api/chat"
# Read from config rather than copied, so the default can never drift from
# the device. Override on the command line to benchmark other models — that
# is the point of this script.
DEFAULT_MODEL = NLU_MODEL

# Two separate budgets, because the first query is not like the others.
#
# COLD: the first query must prefill the whole system prompt (~10.8 KB,
# roughly 2,700 tokens) and may also load the weights off the SD card.
# Prefill is CPU-bound and this is a CPU-only Pi, so it can run to
# minutes. A hardcoded 60 s here used to abort the probe before it
# produced a single data point — and it was stricter than the app itself,
# which allows `NLU_WARMUP_TIMEOUT_S` (90 s). Generous on purpose: the
# point of the cold measurement is to learn the real number, not to
# enforce a limit.
#
# WARM: subsequent queries reuse Ollama's prefix cache for the system
# prompt, so they only generate. Still well above `NLU_TIMEOUT_S` (30 s)
# because a probe that truncates a slow query reports a wrong latency
# instead of a slow one.
COLD_QUERY_TIMEOUT_S = 300.0
WARM_QUERY_TIMEOUT_S = 120.0
_ARGS = [arg for arg in sys.argv[1:] if not arg.startswith("--")]
CLOUD = "--cloud" in sys.argv
MODEL = _ARGS[0] if _ARGS else (NLU_CLOUD_MODEL if CLOUD else DEFAULT_MODEL)
# A named model is measured in JSON mode unless `--prefill` says otherwise;
# the bare default follows config, like the device. Meaningless under
# `--cloud`, where the request style is the provider's.
PREFILL = not CLOUD and (
    "--prefill" in sys.argv or (not _ARGS and NLU_COMPACT_PREFILL)
)

# `--modem` / `--modem=<iface>`: bind cloud requests to the cellular
# interface. Default name matches the SIM7600 as ModemManager brings it
# up; `ip -br addr` on the Pi shows the current one.
_MODEM_ARG = next(
    (a for a in sys.argv if a == "--modem" or a.startswith("--modem=")), None,
)
MODEM_IFACE = (
    None if _MODEM_ARG is None
    else (_MODEM_ARG.split("=", 1)[1] if "=" in _MODEM_ARG else "wwan0")
)


def _build_cloud_session():
    """One session for the whole run, optionally pinned to the modem.

    A single session so the TLS handshake is paid once and the per-query
    numbers are the warm ones the device sees: 226 cold connections would
    add ~100-250 ms to every case and report a latency no deployed code
    would ever pay. `MistralIntentParser` holds a session for the same
    reason.

    `SO_BINDTODEVICE` rather than `source_address`, because binding the
    source alone leaves the route lookup pointing at `wlan0` and the
    kernel rejects the mismatch with `EADDRNOTAVAIL`.
    """
    session = requests.Session()
    if MODEM_IFACE is None:
        return session

    import socket
    from requests.adapters import HTTPAdapter
    from urllib3.poolmanager import PoolManager

    class _InterfaceAdapter(HTTPAdapter):
        def init_poolmanager(self, connections, maxsize, block=False, **kw):
            kw["socket_options"] = [(
                socket.SOL_SOCKET,
                socket.SO_BINDTODEVICE,
                MODEM_IFACE.encode(),
            )]
            self.poolmanager = PoolManager(
                num_pools=connections, maxsize=maxsize, block=block, **kw,
            )

    session.mount("https://", _InterfaceAdapter())
    return session


_cloud_session = _build_cloud_session() if CLOUD else None
# Accumulated across the run and reported in the summary. The cached
# fraction of the prefix is what decides whether this is affordable, so it
# is measured rather than assumed.
_cloud_prompt_tokens = 0
_cloud_cached_tokens = 0
# Must match `intents/parser.py`'s `_COMPACT_PREFIX`.
_COMPACT_PREFIX = '{"intent":"'

# Qwen 3 is a hybrid reasoning model and emits a `<think>` block unless told
# otherwise, which wrecks both latency and the strict-JSON contract. Ollama
# rejects `think` on models that cannot reason (e.g. the Qwen 2.5 baseline we
# compare against), so we send it, detect rejection once, and fall back for
# the rest of the run rather than forcing the user to pass a flag.
_send_think = True

# Each engine gets its own prompt — the cloud model needs the deferral
# bias dialled down, the local one needs it. Reading the wrong file here
# would measure a configuration the device never runs.
PROMPT_PATH = NLU_CLOUD_PROMPT_PATH if CLOUD else (
    PROJECT_ROOT / "prompts" / "nlu_system.md"
)
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
    ("Walk me to the nearest bus stop",  "navigation.start", {"location": "bus stop", "nearest": True}),
    ("I want to go to Lipa Cathedral",   "navigation.start", {"location": "Lipa Cathedral", "nearest": False}),
    ("Find me the closest ATM",          "navigation.start", {"location": "ATM", "nearest": True}),

    # --- navigation.location ---
    ("Where am I?",                      "navigation.location", {}),
    ("What's my current address",        "navigation.location", {}),
    ("Tell me my location",              "navigation.location", {}),
    ("What street is this",              "navigation.location", {}),
    ("Can you tell me where I am",       "navigation.location", {}),

    # --- navigation.stop ---
    ("Cancel navigation",                "navigation.stop", {}),
    ("Stop the trip",                    "navigation.stop", {}),
    ("End the route",                    "navigation.stop", {}),
    ("I don't need directions anymore",  "navigation.stop", {}),

    # --- navigation.repeat ---
    ("Repeat the last instruction",      "navigation.repeat", {}),
    ("Say that again",                   "navigation.repeat", {}),
    ("I didn't catch that",              "navigation.repeat", {}),
    ("Could you repeat the direction",   "navigation.repeat", {}),

    # --- emergency.trigger ---
    ("Help me, this is an emergency",    "emergency.trigger", {}),
    ("I need help now",                  "emergency.trigger", {}),
    ("SOS",                              "emergency.trigger", {}),
    ("Please help me, I fell down",      "emergency.trigger", {}),
    ("I'm hurt, get help",               "emergency.trigger", {}),

    # --- guardian.status_ok ---
    # The all-clear after an alert. Held out from the prompt, which teaches
    # "I'm safe now" and "Tell my guardian I'm fine". The near-misses that
    # must NOT send an all-clear are in the adversarial group.
    ("Tell my guardian everything is fine", "guardian.status_ok", {}),
    ("I'm okay now, no need to worry",   "guardian.status_ok", {}),

    # --- device.status ---
    ("How much battery do I have left",  "device.status", {"status_field": "battery"}),
    ("Is the GPS connected",             "device.status", {"status_field": "gps"}),
    ("Check my battery, please.", "device.status", {"status_field": "battery"}),
    
    ("Is the battery almost empty",      "device.status", {"status_field": "battery"}),
    ("Do you have a GPS fix",            "device.status", {"status_field": "gps"}),
    ("Do we have internet",              "device.status", {"status_field": "signal"}),
    ("How strong is the signal",         "device.status", {"status_field": "signal"}),

    # --- system.time ---
    ("What time is it",                  "system.time", {}),
    ("What time is it right now", "system.time", {}),
    ("Tell me what time it is",          "system.time", {}),
    ("Got the time?",                    "system.time", {}),

    # --- vision.describe ---
    ("What's around me",                 "vision.describe", {}),
    ("Describe my surroundings",         "vision.describe", {}),
    ("What do you see",                  "vision.describe", {}),
    ("Describe the room I'm in",         "vision.describe", {}),
    ("What objects can you see",         "vision.describe", {}),

    # --- vision.read ---
    ("Read this",                        "vision.read", {}),
    ("What does this sign say",          "vision.read", {}),
    ("Read the menu for me",             "vision.read", {}),
    ("Read the label on this bottle",    "vision.read", {}),
    ("What is written on this sign",     "vision.read", {}),

    # --- system.language ---
    # A misclassification here is worse than most: if the model cannot
    # recognise a switch request, the user is stranded in a language they
    # may not want and has no settings screen to escape through.
    ("Switch to English",                "system.language", {"language": "en"}),
    ("Speak English please",             "system.language", {"language": "en"}),
    ("Switch to Tagalog",                "system.language", {"language": "tl"}),
    ("Can you speak Filipino",           "system.language", {"language": "tl"}),
    ("Change to English",                "system.language", {"language": "en"}),
    ("I prefer Filipino",                "system.language", {"language": "tl"}),
    # An unsupported language is passed through by name so the executor can
    # say so. The fast path must escalate it — "Japanese" is not a label.
    ("Switch to Japanese",               "system.language", {"language": "Japanese"}),

    # --- unknown (clear non-commands) ---
    ("Play some music",                  "unknown", {}),
    ("Send a text to my mom",            "unknown", {}),

    # --- unknown, and that is the point: cloud-LLM territory ---
    # These are reasonable things to ask a voice assistant and are NOT
    # intents. `unknown` is the correct answer, not a failure — it is the
    # sole entry point to the cloud fallback (see intents/cloud.py). If
    # the model ever classified these as a real intent, the command would
    # be mishandled instead of answered.
    # --- system.volume ---
    ("Louder",                           "system.volume", {"direction": "up"}),
    ("Turn the volume down",             "system.volume", {"direction": "down"}),
    ("Set the volume to 60",             "system.volume", {"level": 60}),
    ("Can you make it louder", "system.volume", {"direction": "up"}),
    ("Raise the volume a bit",           "system.volume", {"direction": "up"}),
    ("Make it softer",                   "system.volume", {"direction": "down"}),
    ("Lower your voice",                 "system.volume", {"direction": "down"}),
    ("Volume 80",                        "system.volume", {"level": 80}),

    # --- navigation.progress ---
    ("How much further",                 "navigation.progress", {}),
    ("How far do I still have to go",    "navigation.progress", {}),
    ("How much longer",                  "navigation.progress", {}),
    ("How many meters are left",         "navigation.progress", {}),
    ("Are we there yet",                 "navigation.progress", {}),

    # --- place.save / place.delete ---
    ("Save this place as home",          "place.save", {"label": "home"}),
    ("Remember this as my sister's house", "place.save", {"label": "my sister's house"}),
    ("Forget the place saved as work",   "place.delete", {"label": "work"}),
    ("Take me home",                     "navigation.start", {"location": "home"}),
    # place.list names no place, so unlike its siblings the fast path can
    # answer it. The pair below is the boundary that matters: asking what
    # is ON the list, versus asking about one entry of it — the second has
    # no intent and must stay `unknown`.
    ("Which places do you have saved for me", "place.list", {}),
    # place.locate. Held out from the prompt: it teaches "the clinic" and
    # "CN's house", so matching a possessive, a plain noun phrase and a
    # Tagalog genitive is generalisation rather than lookup.
    ("What is the exact location of my sister's house",
     "place.locate", {"label": "my sister's house"}),
    # No article: `geocode_probe` on 2026-10-12 showed "the pharmacy" makes
    # Photon match the brand "The Generics Pharmacy" 7.1 km away and drop the
    # nearest real pharmacy (2.6 km) out of the window entirely, while
    # "pharmacy" finds it. The two navigation.start cases above already
    # expected the bare noun; this was the outlier.
    ("Where is the pharmacy I saved", "place.locate", {"label": "pharmacy"}),
    ("Say the names of the places I kept", "place.list", {}),
    ("Do you still remember my home",    "unknown", {}),
    ("Save this place as Grandma's house", "place.save", {"label": "Grandma's house"}),
    ("Delete the place saved as gym",    "place.delete", {"label": "gym"}),
    ("List all the places I saved",      "place.list", {}),
    ("Where is my office",               "place.locate", {"label": "my office"}),
    ("Did you save my office",           "unknown", {}),

    # --- system.shutdown ---
    ("Shut down the device",             "system.shutdown", {}),
    ("Turn off IndepenSense",            "system.shutdown", {}),
    ("Power off the wearable",           "system.shutdown", {}),

    # --- system.help ---
    ("What can you do",                  "system.help", {}),
    ("What can I ask you",               "system.help", {}),
    ("What are your commands",           "system.help", {}),
    ("How does this thing work",         "system.help", {}),

    ("How tall is Mount Apo",            "unknown", {}),
    ("How many days until Christmas",    "unknown", {}),
    ("What is the capital of Japan",      "unknown", {}),
    ("Call my mom",                      "unknown", {}),
    ("What's the weather tomorrow",      "unknown", {}),
    ("Sing me a song",                   "unknown", {}),

]

TAGALOG_CASES = [
    ("Dalhin mo ako sa Jollibee",                    "navigation.start",    {"location": "Jollibee"}),
    ("Puntahan mo ang pinakamalapit na ospital",     "navigation.start",    {"location": "ospital", "nearest": True}),
    ("Gabayan mo ako sa palengke",                    "navigation.start",    {"location": "palengke", "nearest": False}),
    ("Papuntang munisipyo",                           "navigation.start",    {"location": "munisipyo"}),
    ("Dalhin mo ako sa pinakamalapit na botika",      "navigation.start",    {"location": "botika", "nearest": True}),
    ("Nasaan ako",                                    "navigation.location", {}),
    ("Nasaan ako ngayon",                             "navigation.location", {}),
    ("Saan na ako ngayon",                            "navigation.location", {}),
    ("Anong lugar ito",                               "navigation.location", {}),
    ("Ihinto ang navigation",                         "navigation.stop",     {}),
    ("Kanselahin ang biyahe",                         "navigation.stop",     {}),
    ("Huwag mo na akong ihatid doon",                 "navigation.stop",     {}),
    ("Ulitin mo yung sinabi",                         "navigation.repeat",   {}),
    ("Ano ulit",                                      "navigation.repeat",   {}),
    ("Pakiulit ang huling direksyon",                 "navigation.repeat",   {}),
    ("Tulong! Emergency!",                            "emergency.trigger",   {}),
    ("Tulungan mo ako, nadapa ako",                   "emergency.trigger",   {}),
    ("Nasaktan ako, kailangan ko ng tulong",          "emergency.trigger",   {}),
    # guardian.status_ok — held out; the prompt teaches "Ligtas na ako".
    ("Okay lang ako",                                 "guardian.status_ok",  {}),
    ("Sabihin mo sa guardian ko na ayos lang ako",    "guardian.status_ok",  {}),
    ("Ilan pa ang natitirang battery",                "device.status",       {"status_field": "battery"}),
    ("Malakas pa ba ang baterya",                     "device.status",       {"status_field": "battery"}),
    ("Naka-lock na ba ang GPS",                       "device.status",       {"status_field": "gps"}),
    ("May signal ba dito",                            "device.status",       {"status_field": "signal"}),
    ("Anong oras na",                                 "system.time",         {}),
    ("Ano na ang oras",                               "system.time",         {}),
    ("Pakisabi kung anong oras na",                   "system.time",         {}),
    ("Ano ang nakikita mo",                           "vision.describe",     {}),
    ("Ano ang nasa paligid ko",                       "vision.describe",     {}),
    ("Ilarawan mo ang nasa harap ko",                 "vision.describe",     {}),
    ("Basahin mo ito",                                "vision.read",         {}),
    ("Pakibasa ang karatula",                         "vision.read",         {}),
    ("Ano ang nakasulat sa papel",                    "vision.read",         {}),
    ("Magpatugtog ka ng musika",                      "unknown",             {}),
    ("Pakicheck naman ang battery ko", "device.status", {"status_field": "battery"}),
    ("Pwede mo bang i-check ang battery", "device.status", {"status_field": "battery"}),
    ("Anong oras na ba", "system.time", {}),
    ("Pakilakasan ang boses", "system.volume", {"direction": "up"}),

    # --- system.language ---
    # The switch phrase is spoken in the language currently ACTIVE, so
    # Tagalog speech asking for English is the realistic case and the one
    # that must work. Note the target is the language asked FOR, not the
    # language being spoken.
    ("Lumipat sa Ingles",                             "system.language",     {"language": "en"}),
    ("Mag-Ingles ka naman",                           "system.language",     {"language": "en"}),
    ("Magsalita ka ng Tagalog",                       "system.language",     {"language": "tl"}),
    ("Tagalog na lang",                               "system.language",     {"language": "tl"}),
    ("Ingles na lang",                                "system.language",     {"language": "en"}),
    ("Mag-Filipino ka",                               "system.language",     {"language": "tl"}),
    ("Bumalik ka sa Tagalog",                         "system.language",     {"language": "tl"}),

    ("Palakasin mo ang tunog",                        "system.volume",       {"direction": "up"}),
    ("Pahinaan mo ang tunog",                         "system.volume",       {"direction": "down"}),
    ("Lakasan mo pa ang boses",                       "system.volume",       {"direction": "up"}),
    ("Hinaan mo ng kaunti",                           "system.volume",       {"direction": "down"}),
    ("Gawin mong 50 ang volume",                      "system.volume",       {"level": 50}),

    ("Gaano pa kalayo",                               "navigation.progress", {}),
    ("Ilang metro pa",                                "navigation.progress", {}),
    ("Matagal pa ba",                                 "navigation.progress", {}),

    ("I-save mo ito bilang bahay",                    "place.save",          {"label": "bahay"}),
    ("Kalimutan mo ang bahay",                        "place.delete",        {"label": "bahay"}),
    ("Ano-ano ang mga lugar na naitabi ko",           "place.list",          {}),
    ("Nasaan ang klinika ko",                         "place.locate",
     {"label": "klinika ko"}),
    ("Pakisabi ang mga lugar na tinago mo",           "place.list",          {}),
    ("Natatandaan mo pa ba ang klinika ko",           "unknown",             {}),
    ("Tandaan mo ito bilang paaralan",                "place.save",          {"label": "paaralan"}),
    ("Burahin mo ang opisina",                        "place.delete",        {"label": "opisina"}),
    ("Ilista mo ang mga lugar ko",                    "place.list",          {}),
    ("Nasaan ang bahay ni Lola",                      "place.locate",        {"label": "bahay ni Lola"}),

    ("Ano ang kaya mong gawin",                       "system.help",         {}),
    ("Paano ito gamitin",                             "system.help",         {}),
    ("Anong mga pwede kong iutos",                    "system.help",         {}),
    ("Paano kita gagamitin",                          "system.help",         {}),

    ("Patayin mo ang IndepenSense",                   "system.shutdown",     {}),
    ("Isara mo ang IndepenSense",                     "system.shutdown",     {}),

    # --- unknown, bound for the cloud fallback ---
    ("Gaano katangkad ang Bundok Apo",                "unknown",             {}),
    ("Ilang araw na lang bago mag-Pasko",             "unknown",             {}),
    ("Padalhan mo ng mensahe si Kuya",                "unknown",             {}),
    ("Ano ang panahon bukas",                         "unknown",             {}),
    ("Magkuwento ka ng biro",                         "unknown",             {}),

]

# Adversarial: verify Phase 1 prompt hardening. These are transcripts where a
# naive LLM might latch onto a keyword ("time", "help", "location") and pick
# the wrong intent. After the "prefer unknown when in doubt" prompt rewrite,
# these should all resolve as expected. Mostly English; the Tagalog block at
# the end mirrors the same traps, since a keyword the model over-trusts in
# one language is usually over-trusted in the other.
ADVERSARIAL_CASES = [
    # system.shutdown near-misses. Powering off is irreversible for the
    # user, so the phrases one word away from it matter as much as the
    # intent itself. The confirmation step is the real guard, but a
    # classifier that reaches for shutdown on "shut up" would ask the
    # question constantly and train the user to dismiss it.
    ("shut up",                          "unknown", {}),
    ("tumahimik ka",                     "unknown", {}),
    ("turn the volume off",              "system.volume", {"direction": "down"}),
    ("stop the trip",                    "navigation.stop", {}),

    # "time" in non-time-query context → unknown, not system.time
    ("sometime tomorrow",                "unknown", {}),
    ("one at a time please",             "unknown", {}),
    ("in a bit",                         "unknown", {}),

    # Numbers in a question are not a time either. Field transcripts: the
    # wearable answered the first of these with the time of day, having
    # apparently read "5 plus 7" as a clock reading, while classifying two
    # other phrasings of the same question correctly. Held out from the
    # prompt on purpose — it teaches the category with a different
    # arithmetic ("nine times eight"), so matching these is generalisation
    # rather than lookup. All three belong to the cloud.
    ("I'm just asking what is the answer 5 plus 7", "unknown", {}),
    ("I said what's the answer? 5-7",    "unknown", {}),
    ("magkano ang dalawa plus tatlo",    "unknown", {}),
    ("Uh wait a second", "unknown", {}),

    # "help" in non-emergency context
    ("help me find the pharmacy",        "navigation.start", {"location": "pharmacy"}),
    ("how do I use this",                "system.help", {}),
    ("what can you help me with",        "system.help", {}),

    # The single word must stay an emergency. This is the most expensive
    # confusion on the device: answering a cry for help by listing
    # features. It sits in the adversarial group because `system.help`
    # gives the model a tempting place to put it.
    # Saving is always the CURRENT position. Naming somewhere the user is
    # not would store the wrong coordinate under a label they later trust.
    ("Save Jollibee as my favourite",    "unknown", {}),

    ("help",                             "emergency.trigger", {}),
    ("tulong",                           "emergency.trigger", {}),

    # "location" / "where" about a place, not the user
    # Was `unknown`, and the behaviour the user sees is unchanged: the
    # executor finds no saved place by this name and hands the original
    # transcript to the cloud, exactly as before. What moved is WHERE the
    # decision is made. The classifier cannot know which labels this user
    # saved, so it now identifies the question's form and the executor —
    # which can see the saved places — resolves the referent.
    ("where is Jollibee",                "place.locate", {"label": "Jollibee"}),
    # Progress is about the journey under way; the distance to some other
    # place would be answered with the current destination's, confidently
    # and wrongly.
    ("How far is Jollibee from here",    "unknown", {}),

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
    # "speak" is the verb for both a volume change and a language switch.
    # Only the object separates them.
    ("Speak louder",                     "system.volume", {"direction": "up"}),

    ("Read this English sign",           "vision.read", {}),
    ("Take me to English Street",        "navigation.start", {"location": "English Street"}),
    ("I speak Tagalog at home",          "unknown", {}),

    # More English near-misses, one per intent that a keyword could pull in.
    ("help me cross the road",           "unknown", {}),
    ("help me read the menu",            "vision.read", {}),
    ("what's the date today",            "unknown", {}),
    ("remind me at noon to eat",         "unknown", {}),
    ("turn off the lights",              "unknown", {}),
    ("my phone's battery is dying",      "unknown", {}),
    ("I read an article about GPS",      "unknown", {}),
    ("how do you say thank you in Filipino", "unknown", {}),

    # guardian.status_ok near-misses. A false all-clear tells the guardian
    # to stand down during a real emergency, so filler and negated states
    # must not reach it.
    ("all good",                         "unknown", {}),
    ("I'm not fine at all",              "emergency.trigger", {}),

    # Tagalog mirrors of the traps above.
    ("tulungan mo akong tumawid",        "unknown", {}),
    ("tulungan mo akong hanapin ang botika", "navigation.start", {"location": "botika"}),
    ("tulungan mo akong basahin ang menu", "vision.read", {}),
    ("ihinto mo",                        "navigation.stop", {}),
    ("isa-isa lang",                     "unknown", {}),
    ("mamaya na lang",                   "unknown", {}),
    ("lowbat na ang telepono ko",        "unknown", {}),
    ("ang ganda ng panahon ngayon",      "unknown", {}),
    ("inaantok na ako",                  "unknown", {}),
    ("nasaan ang Jollibee",              "place.locate", {"label": "Jollibee"}),
    ("gaano kalayo ang SM mula dito",    "unknown", {}),
    ("naka-save ba ang bahay ko",        "unknown", {}),
    ("i-save mo ang Jollibee bilang paborito ko", "unknown", {}),
    ("ano ang Ingles ng mesa",           "unknown", {}),
    ("hindi ako ayos",                   "emergency.trigger", {}),
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
    """Return currently-free RAM in MB, or -1 where that isn't knowable.

    `/proc/meminfo` is Linux-only. Returning -1 on a Mac rather than raising
    keeps the probe runnable off-device: the RAM figures are context for the
    Pi's memory budget, while the accuracy scores — which are a property of
    the model and the prompt, not the host — are worth collecting anywhere.
    """
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) // 1024
    except OSError:
        return -1
    return -1


CLOUD_PROBE_TIMEOUT_S = 30.0


def _egress_ip() -> str:
    """The public address the run is actually leaving from.

    Printed because `--modem` silently measuring WiFi is the failure this
    whole flag exists to prevent, and a flag that is set but not working
    looks exactly like one that is. Two different addresses across two
    runs is the proof the bind took effect.
    """
    try:
        return _cloud_session.get("https://api.ipify.org", timeout=15).text.strip()
    except Exception as exc:   # noqa: BLE001 - diagnostic only
        return f"unknown ({type(exc).__name__})"


def _default_iface() -> str:
    """Interface the kernel would pick for the provider, for the header."""
    import subprocess
    try:
        out = subprocess.run(
            ["ip", "route", "get", "1.0.0.1"],
            capture_output=True, text=True, timeout=3.0,
        ).stdout.split()
        return out[out.index("dev") + 1] if "dev" in out else "?"
    except Exception:   # noqa: BLE001 - diagnostic only
        return "?"


def cloud_query(
    text: str,
    timeout_s: float = CLOUD_PROBE_TIMEOUT_S,
) -> tuple[float, dict | None, str]:
    """Send one transcript to Mistral. Same return shape as `query`.

    Deliberately builds the request here rather than importing
    `MistralIntentParser`: the probe measures the raw model against the
    test set, and routing through the driver would also measure the
    driver's normalisation, so a scoring bug and a model regression would
    be indistinguishable. The payload is kept identical to `_payload`
    there — two messages, system first, temperature 0, JSON mode — and if
    the two ever drift, this probe stops predicting the device.

    No timeout is enforced at the device's 2.5 s deadline. The probe
    measures what the model *can* do; how much of that the runtime is
    willing to wait for is a separate decision, and truncating here would
    report a fallback as a wrong answer.
    """
    global _cloud_prompt_tokens, _cloud_cached_tokens

    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
        "max_tokens": 128,
        "temperature": 0.0,
        "response_format": {"type": "json_object"},
    }

    t0 = time.time()
    response = _cloud_session.post(
        CLOUD_LLM_URL,
        json=payload,
        headers={
            "Authorization": f"Bearer {os.environ[CLOUD_LLM_API_KEY_ENV]}",
            "Content-Type": "application/json",
        },
        timeout=timeout_s,
    )
    elapsed = time.time() - t0

    try:
        body = response.json()
    except ValueError:
        return elapsed, None, response.text[:200]

    if response.status_code != 200:
        error = json.dumps(body.get("error") or body)
        return elapsed, None, f"HTTP {response.status_code}: {error[:150]}"

    usage = body.get("usage") or {}
    _cloud_prompt_tokens += usage.get("prompt_tokens", 0)
    _cloud_cached_tokens += (
        (usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0)
    )

    try:
        raw = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        return elapsed, None, f"unexpected shape: {exc}"

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = None
    return elapsed, parsed, raw


def query(
    text: str,
    timeout_s: float = WARM_QUERY_TIMEOUT_S,
) -> tuple[float, dict | None, str]:
    """Send one transcript to Ollama. Return (elapsed_s, parsed_json_or_None, raw_response).

    Sends `think: False` for reasoning models. If Ollama rejects the flag
    (non-reasoning model), disables it for the remainder of the run and
    retries once. Without this the rejection would surface as an empty
    response on every case and look like a total accuracy collapse.

    Under `--cloud` this hands straight over to `cloud_query`, so the
    caller — and therefore the scoring and reporting below — cannot tell
    the two engines apart. That is the point: an accuracy comparison is
    only meaningful if both sides ran the same cases through the same
    scorer.
    """
    global _send_think

    if CLOUD:
        return cloud_query(text)

    if PREFILL:
        url = OLLAMA_CHAT_URL
        payload = {
            "model": MODEL,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": text},
                {"role": "assistant", "content": _COMPACT_PREFIX},
            ],
            "stream": False,
            "options": {"temperature": 0.0, "stop": ["\n"]},
        }
    else:
        url = OLLAMA_URL
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
    response = requests.post(url, json=payload, timeout=timeout_s)
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
            # Pass the budget through: a cold query that lands here must
            # keep its longer allowance, not silently fall back to the warm one.
            return query(text, timeout_s=timeout_s)
        return elapsed, None, f"HTTP {response.status_code}: {error[:150]}"

    if PREFILL:
        raw = _COMPACT_PREFIX + (body.get("message") or {}).get("content", "")
    else:
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
    if CLOUD and not os.environ.get(CLOUD_LLM_API_KEY_ENV):
        # Fail before 226 queries rather than on the first one, and name
        # the variable — the key lives in `.env` on the Pi, which a
        # non-interactive shell does not source.
        sys.exit(
            f"{CLOUD_LLM_API_KEY_ENV} is not set. On the Pi: "
            f"`set -a && . ./.env && set +a` first."
        )

    if CLOUD:
        print(f"Model:  {MODEL}  (cloud, JSON mode)")
        print(f"Prompt: {PROMPT_PATH} ({len(SYSTEM_PROMPT)} chars)")
        print(f"URL:    {CLOUD_LLM_URL}")
        if MODEM_IFACE:
            print(f"Route:  {MODEM_IFACE} (cellular) — egress {_egress_ip()}")
        else:
            print(
                f"Route:  default ({_default_iface()}) — egress {_egress_ip()}\n"
                f"  NOTE: not pinned to the modem. At a desk this measures WiFi,\n"
                f"  which is ~170 ms faster than the field. Use --modem."
            )
    else:
        print(f"Model:  {MODEL}  ({'compact-JSON prefill' if PREFILL else 'JSON mode'})")
        print(f"Prompt: {PROMPT_PATH} ({len(SYSTEM_PROMPT)} chars)")
        print(f"Free RAM before loading model: {free_ram_mb()} MB")
    print("Warming up with a throwaway query...")

    cold_elapsed, _, _ = query("Hello", timeout_s=COLD_QUERY_TIMEOUT_S)
    print(f"Cold query took {cold_elapsed:.2f}s")
    if CLOUD:
        # The cold call pays TCP + TLS and, if the provider's prefix cache
        # has expired, a full prefill. Both are startup costs the device
        # pays once via `MistralIntentParser.warm_up`, which is why they
        # are reported separately rather than folded into the per-query
        # numbers below.
        print("  (cold = TLS handshake + any uncached prefill; warmed once at startup)")
    else:
        print(f"Free RAM after model loaded: {free_ram_mb()} MB")
        if cold_elapsed > NLU_WARMUP_TIMEOUT_S:
            # A cold query slower than the app's warmup budget means its startup
            # warmup gives up, so the first real voice command after boot pays
            # this cost instead.
            print(
                f"  NOTE: this exceeds NLU_WARMUP_TIMEOUT_S "
                f"({NLU_WARMUP_TIMEOUT_S:.0f}s), so app.py's startup warmup would "
                f"time out and the first voice command would pay the prefill."
            )
        if MODEL != NLU_MODEL:
            # The budget follows `config.NLU_LARGE_MODEL`, which is set for a
            # different model than the one measured here.
            print(
                f"  (config is set for {NLU_MODEL}; flipping NLU_LARGE_MODEL "
                f"changes the warmup budget along with the model.)"
            )
    print()

    total_time = 0.0
    parse_failures = 0
    intent_correct_count = 0
    slots_correct_count = 0
    slots_measured_count = 0
    combined_correct_count = 0
    misses: list[tuple[str, str, str, dict, str]] = []   # (group, input, expected_intent, expected_slots, got)
    stats = {g: {"n": 0, "intent": 0, "combined": 0, "time": 0.0} for g in GROUPS}

    # How many answers arrived too late for the runtime to use them. These
    # are not wrong — the model answered — but the device would have
    # abandoned the wait and fallen back to Ollama, so they bound how much
    # of the measured accuracy is actually reachable in production.
    over_deadline = 0

    for i, (group, text, expected_intent, expected_slots) in enumerate(TEST_CASES, 1):
        elapsed, parsed, raw = query(text)
        if CLOUD and elapsed > NLU_CLOUD_TIMEOUT_S:
            over_deadline += 1
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
    if CLOUD:
        route = f"{MODEM_IFACE}, cellular" if MODEM_IFACE else "default route"
        print(f"Summary for model: {MODEL} (cloud via {route})")
    else:
        print(f"Summary for model: {MODEL} ({'compact-JSON prefill' if PREFILL else 'JSON mode'})")
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
    if CLOUD:
        print(f"  Over {NLU_CLOUD_TIMEOUT_S:.1f}s deadline:  {over_deadline}/{total} "
              f"({100 * over_deadline / total:.1f}%) — would fall back to Ollama")
        if _cloud_prompt_tokens:
            print(f"  Prompt tokens:       {_cloud_prompt_tokens} total, "
                  f"{_cloud_cached_tokens} cached "
                  f"({100 * _cloud_cached_tokens / _cloud_prompt_tokens:.1f}%)")
    else:
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
