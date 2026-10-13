"""Cloud LLM fallback — the "answer anything" path.

The local NLU (Qwen 3 1.7B via Ollama) classifies into a fixed set of
intents and is deliberately biased toward `unknown` — see
`prompts/nlu_system.md`. That bias is right for a safety device: a
wearable that guesses is worse than one that admits it didn't
understand. But it leaves a gap. "How many days until Christmas", "what
is the tagalog word for umbrella", "how tall is Mount Apo" are all
reasonable things to ask a voice assistant and none of them are intents.

So `unknown` becomes the trigger rather than a dead end. When the local
parser returns `unknown` and a cloud answerer is configured, the
transcript goes to a cloud LLM. The local model stays conservative and
the cloud becomes graceful degradation, not a competing classifier.

Why not a `cloud.ask` intent
----------------------------

Because it would fight the bias that makes the local model trustworthy.
A catch-all intent gives the classifier a tempting bucket for anything
it is unsure about, and the failure mode is severe: "take me to the
hospital" routed to a chatbot instead of navigation. Keeping `unknown`
as the sole entry point means the cloud only ever sees utterances the
local model already declined, so it can never intercept a real command.

It also yields an honest thesis metric: how often the local model
defers, measurable straight off the `unknown` rate.

Privacy
-------

**This path** sends only the transcript — never the recorded audio. The
question has already been through speech-to-text, so there is nothing to
gain from shipping the recording with it.

That is no longer the whole picture for the device, and the docstring
used to imply it was. Tagalog speech-to-text runs on `gpuer`
(`REMOTE_STT_ENABLED`), so Tagalog *audio* does leave the Pi — see
`docs/cloud-services.md`. English audio does not; the exception is
bounded to the language whose on-device quality was the measured
problem.

The distinction that survives is between **processors**, and it is the
one worth stating in the ethics chapter. `gpuer` is under the project's
control, so recordings stay in hand. Mistral is a third party, and the
only thing it ever receives is text the user chose to say aloud.

Implementing a provider
-----------------------

The provider in use is `MistralAnswerer` (`intents/mistral.py`), opened by
`_try_open_cloud_answerer` in `app.py`. This module holds the contract
rather than the implementation, so swapping providers touches one factory
method. A replacement needs to:

  - implement `CloudAnswerer.answer(question, language, previous) -> CloudAnswer`
  - replay `previous` — the last `(question, answer)` pair, or None — as
    a real prior turn, so a follow-up ("what about the second") resolves.
    One turn only; the executor decides what to keep and when it expires
  - never raise; return `reason="error"` instead
  - distinguish offline from provider failure, so the user hears
    "no internet connection" only when that is actually true
  - instruct the provider to answer **briefly** and **in `language`**.
    The answer is spoken aloud by Piper, so three paragraphs is a
    90-second monologue. `CLOUD_MAX_RESPONSE_CHARS` truncates as a
    backstop, but the prompt should make truncation unnecessary
  - read its key from the environment, never from a committed file
  - lazy-import its SDK inside the method, per the project convention

Then point `_try_open_cloud_answerer` in `app.py` at it. `OfflineGuard`
below wraps whatever that returns, so the offline path does not need
reimplementing per provider.
"""
import sys

from indepensense.intents.base import CloudAnswer
from indepensense import net
from indepensense.net import probe_reachable


class OfflineGuard:
    """Wraps a `CloudAnswerer` and short-circuits when there's no internet.

    Kept separate from any provider driver so that every future provider
    inherits the behaviour instead of reimplementing it, and so the
    offline path is testable without a provider at all.

    Why check before calling rather than letting the request fail: the
    voice pipeline plays a "thinking" cue before a cloud call, and
    playing it only to immediately say "no internet" is a worse
    experience than answering straight away.

    `probe_url` is the provider's own host, not a neutral third party.
    The earlier design probed `1.1.1.1` on the theory that one endpoint
    timing out could mean the provider is down rather than the link, and
    a well-known target disambiguates. In practice it introduced a third
    host that can fail on its own, and on the deployment carrier it did:
    `1.1.1.1` is null-routed there, so every cloud question was refused
    with "I need an internet connection" while Mistral answered in 0.7 s.
    The best predictor of "can I reach the provider" is the provider.

    The distinction the old design chased is real but cheap to lose: a
    provider outage now reads as offline rather than as an error. Both
    end in the user not getting an answer, and `reason` keeps them
    separable in the log.
    """

    def __init__(
        self,
        inner,
        probe_url: str,
        probe_timeout_s: float = 2.0,
    ):
        self._inner = inner
        self._probe_url = probe_url
        self._probe_timeout_s = probe_timeout_s

    def is_online(self) -> bool:
        return probe_reachable(self._probe_url, timeout_s=self._probe_timeout_s)

    def answer(
        self,
        question: str,
        language: str,
        previous: tuple[str, str] | None = None,
    ) -> CloudAnswer:
        """Ask the provider, unless we already know it will not work.

        **"offline" is only said when it is true.** The two reasons map
        to two different sentences, and the user acts on one of them:
        `cloud.offline` is "I need an internet connection", which a
        blind user answers by walking somewhere else to find signal.
        Saying that because the provider returned 429, or because a
        classification ran past its 2.5 s budget, sends someone across a
        road for nothing.

        The breaker is shared with `MistralIntentParser` — same host —
        so a failed classification is what usually opens it, and under
        the current rules most of those failures are *not* connectivity
        ones. `HostBreaker.reason` is what keeps the two apart.
        """
        reason = self._unavailable_reason()
        if reason is not None:
            print(f"[cloud] not sending the question: {reason}",
                  file=sys.stderr)
            return CloudAnswer(text=None, reason=reason)
        return self._inner.answer(question, language, previous)

    def _unavailable_reason(self) -> str | None:
        """`"offline"`, `"error"`, or None to go ahead."""
        if not net.has_network_route():
            return "offline"

        breaker = net.breaker_for(self._probe_url)
        open_because = breaker.reason
        if open_because is not None:
            # Only a genuine reachability failure is "offline". Backoff,
            # a rejected key and a slow reply all mean the link is fine
            # and something else is wrong — which is `cloud.error`.
            return "offline" if open_because == net.UNREACHABLE else "error"

        # Nothing known yet, so probe. A failure here records itself as
        # UNREACHABLE, which is what it is: a bare HEAD that could not
        # complete.
        return None if self.is_online() else "offline"

    def close(self) -> None:
        """Release the wrapped provider's resources — its HTTP session, in
        Mistral's case. Tolerates a provider without `close`, since the
        protocol's own `close` is optional."""
        closer = getattr(self._inner, "close", None)
        if closer is not None:
            closer()
