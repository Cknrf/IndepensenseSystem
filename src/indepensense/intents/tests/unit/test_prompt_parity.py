"""The two system prompts must stay in step on everything but caution.

`nlu_system.md` (local) and `nlu_system_cloud.md` (cloud) deliberately
differ in how readily they answer `unknown` — that split is the whole
reason there are two files, and `config.NLU_CLOUD_PROMPT_PATH` explains
it. Everything else has to match, and nothing enforces that by
construction.

This is the drift control. Adding an intent means editing two prompts
now, and the failure mode of forgetting one is silent: the engine with
the stale prompt cannot name the new intent, so it answers `unknown`
forever and the only symptom is a slightly worse accuracy number nobody
re-measures. That is exactly what happened with `guardian.status_ok`
when it had a handler and bank rows but no prompt entry — see commit
`0b36ecc`. One file was easy to forget; two is easier.

Same role `parse_bank` plays for the embedding bank and the coverage
tests play for `messages.py`: a structural invariant asserted cheaply
rather than trusted.
"""
import re

import pytest

from indepensense.config import NLU_CLOUD_PROMPT_PATH, NLU_PROMPT_PATH
from indepensense.intents.base import Intent


def _declared_intents(path) -> set[str]:
    """Intent labels named in the prompt's INTENTS block.

    Parsed from the block rather than by searching the whole file,
    because the labels also appear throughout RULES and EXAMPLES and a
    whole-file scan would pass even if the catalogue itself were
    missing an entry.
    """
    text = path.read_text()
    block = re.search(r"^INTENTS\n(.*?)\n\s*\nRULES", text, re.S | re.M)
    assert block, f"{path.name} has no INTENTS block delimited by a blank line"
    return {
        m.group(1)
        for m in re.finditer(r"^([a-z_]+(?:\.[a-z_]+)?)\s", block.group(1), re.M)
    }


@pytest.fixture(scope="module")
def local() -> set[str]:
    return _declared_intents(NLU_PROMPT_PATH)


@pytest.fixture(scope="module")
def cloud() -> set[str]:
    return _declared_intents(NLU_CLOUD_PROMPT_PATH)


def test_both_prompts_declare_the_same_intents(local, cloud):
    assert local == cloud, (
        f"prompt drift — only in local: {sorted(local - cloud)}, "
        f"only in cloud: {sorted(cloud - local)}"
    )


def test_every_intent_in_the_enum_is_declared_in_both_prompts(local, cloud):
    """A model cannot return a label it was never offered.

    The executor handles the full `Intent` enum, so an intent missing
    from a prompt is a handler that engine can never reach.
    """
    expected = {i.value for i in Intent}
    assert local == expected, f"local prompt: {sorted(expected ^ local)}"
    assert cloud == expected, f"cloud prompt: {sorted(expected ^ cloud)}"


def test_the_cloud_prompt_is_the_less_cautious_of_the_two():
    """Pins the one difference that is supposed to exist.

    If a future edit copies the local prompt's blanket deferral wording
    into the cloud file, the 15-of-17 `unknown` failure mode comes
    straight back and the only evidence would be an accuracy number
    nobody re-ran. Counting the word is crude, but it fails loudly in
    the direction that matters.
    """
    local_text = NLU_PROMPT_PATH.read_text().lower()
    cloud_text = NLU_CLOUD_PROMPT_PATH.read_text().lower()

    assert "when in doubt, output unknown" in local_text, (
        "the local prompt's deferral bias is load-bearing for Qwen 1.7B"
    )
    assert "when in doubt, output unknown" not in cloud_text, (
        "the cloud prompt must not inherit the local model's blanket bias"
    )
