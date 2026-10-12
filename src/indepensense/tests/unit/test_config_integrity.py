"""Structural checks on `config.py` that Python itself will not make.

`config.py` is one long flat module of module-level assignments, which
is the right shape for it — but it means a name assigned twice is not an
error, not a warning, and not visible in a diff that touches only one of
the two places. Python simply keeps the last one.

That is not hypothetical. `REMOTE_TTS_URL` was defined twice: once as
the full `/tts` endpoint the runtime driver posts to, and three hundred
lines later as the bare base URL a manual benchmark appends its own path
to. The second won, so the driver posted to the server root and **every
Tagalog message failed to render with a 404** — 66 of 132 clips, with
nothing but a count in the tool's output to say so.
"""
import ast
from collections import Counter
from pathlib import Path

import indepensense.config as config_module


def _assignment_counts() -> Counter:
    """How many times each module-level name is assigned in config.py.

    Parsed from the source rather than read off the module, because by
    the time the module is imported a duplicate has already collapsed
    into whichever assignment ran last — the evidence is gone.
    """
    tree = ast.parse(Path(config_module.__file__).read_text())
    names: Counter = Counter()
    for node in tree.body:
        targets = []
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
        for target in targets:
            if isinstance(target, ast.Name):
                names[target.id] += 1
    return names


def test_config_has_no_duplicate_assignments():
    duplicates = {name: n for name, n in _assignment_counts().items() if n > 1}

    assert not duplicates, (
        f"assigned more than once in config.py: {duplicates}. "
        f"Python keeps the last one silently — rename one, or delete it."
    )


def test_the_two_gpuer_urls_are_not_the_same_name():
    """The specific collision that caused the 404.

    One is a full endpoint and one is a base; they are different things
    and must stay differently named. Kept as its own case so the failure
    message points at the actual mistake rather than at a generic
    duplicate.
    """
    assert config_module.REMOTE_TTS_URL.endswith("/tts"), (
        "the runtime driver posts to this directly, so it must be the "
        "full endpoint, not a base URL"
    )
    assert config_module.REMOTE_STT_URL.endswith("/stt")
    assert not config_module.TTS_API_BASE_URL.endswith("/tts"), (
        "tts_api_bench appends its own path to this"
    )


def test_no_cloud_model_is_a_floating_alias():
    """`-latest` moves, and a thesis that quotes an accuracy figure needs
    the model that produced it to still exist.

    This is the same argument architecture decision 3 makes for the local
    models, which load from directories laid out by `fetch_models` rather
    than resolving a Hugging Face repo id at runtime: the weights in use
    should be the ones that were tested. A provider alias is the cloud
    version of the same hazard, and it drifts without any commit to show
    for it.

    Re-pinning is a deliberate act: change the ID, re-run `llm_probe`,
    update the measured table in `config.py`.
    """
    models = {
        name: value for name, value in vars(config_module).items()
        if name.endswith("_MODEL") and isinstance(value, str)
    }
    floating = {n: v for n, v in models.items() if v.endswith("-latest")}

    assert not floating, (
        f"floating model aliases: {floating}. Pin the dated ID and re-run "
        f"the probe that produced the numbers in config.py."
    )
