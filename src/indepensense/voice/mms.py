"""Meta MMS-TTS driver — a natively-trained Tagalog voice.

Piper publishes no Filipino/Tagalog voice, so the `tl` slot used to be
filled with the Indonesian `id_ID-news_tts-medium`: intelligible, because
Indonesian and Tagalog are both Austronesian with matching 5-vowel
systems, but audibly not Tagalog. `facebook/mms-tts-tgl` is trained on
Tagalog itself, which is the difference between an accent and a
substitute.

It is a VITS model (36.3M parameters) from Meta's Massively Multilingual
Speech project, run through `transformers`. Two consequences of that
choice are worth knowing before reading the code:

**It is character-level, with no text frontend.** Piper phonemises via
espeak-ng, which expands "90" into the number words of the voice's
language. MMS has no such stage: its vocabulary is 43 characters, and
anything outside it is dropped silently. Digits are technically in the
vocabulary but the MMS-lab training corpus spells numbers out, so they
are effectively untrained. Callers must hand this driver text that is
already words — which is what `intents.messages.tagalog_number` exists
for. Sentence punctuation is *not* in the vocabulary at all, hence the
sentence splitting below.

**It is licensed CC-BY-NC 4.0**, unlike the MIT-licensed Piper voices.
Fine for this thesis; a commercial deployment would need a different
Tagalog voice. Recorded here so the constraint travels with the code.

Model: https://huggingface.co/facebook/mms-tts-tgl
"""
import re
import threading
from pathlib import Path

# MMS drops any character outside its 43-token vocabulary, so a period
# contributes nothing and three sentences render as one run-on breath.
# Splitting here and inserting real silence is what restores the phrasing
# espeak-ng gives Piper for free.
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")

_SENTENCE_PAUSE_S = 0.25


class MmsTTS:
    """A single-language MMS voice.

    MMS ships one checkpoint per language, so unlike `PiperTTS` this holds
    exactly one model and `language` is only ever a sanity check. Routing
    across languages is `MultiEngineTTS`'s job.
    """

    def __init__(self, model_dir: Path, language: str):
        """Load the checkpoint from a local directory.

        `model_dir` is a downloaded snapshot of the Hugging Face repo
        (config.json, model.safetensors, tokenizer files) — see
        docs/voice.md. Local rather than a repo id so that a Pi with no
        network still starts, and so the model in use is the one that was
        tested rather than whatever the Hub currently serves.
        """
        from transformers import AutoTokenizer, VitsModel  # lazy: pulls torch

        if not model_dir.exists():
            raise FileNotFoundError(
                f"MMS voice for '{language}' not found at {model_dir}. "
                f"See docs/voice.md for the download command."
            )

        self.language = language
        self._model = VitsModel.from_pretrained(str(model_dir)).eval()
        self._tokenizer = AutoTokenizer.from_pretrained(str(model_dir))
        self.sample_rate = self._model.config.sampling_rate

        # The announcer thread and a voice thread can both want speech at
        # once. ONNX Runtime — what Piper uses — takes concurrent calls on
        # one session; torch makes no such guarantee for a shared module,
        # so synthesis is serialised. Contention is not a concern: playback
        # of the previous utterance is far longer than this.
        self._lock = threading.Lock()

    def synthesize(
        self,
        text: str,
        output_path: Path,
        language: str | None = None,
    ) -> None:
        if language is not None and language != self.language:
            raise ValueError(
                f"MmsTTS holds the '{self.language}' voice, asked for "
                f"'{language}'"
            )

        import numpy as np
        import soundfile as sf

        sentences = [s for s in _SENTENCE_END.split(text.strip()) if s.strip()]
        pause = np.zeros(int(_SENTENCE_PAUSE_S * self.sample_rate), dtype="float32")

        chunks: list = []
        for sentence in sentences:
            waveform = self._synthesize_one(sentence)
            if waveform is None:
                continue
            if chunks:
                chunks.append(pause)
            chunks.append(waveform)

        # Nothing survived tokenisation — a message that was entirely
        # punctuation, or characters outside the vocabulary. Write a valid
        # empty WAV rather than letting a downstream read fail: silence is
        # recoverable, an exception on the voice thread is not.
        audio = np.concatenate(chunks) if chunks else np.zeros(0, dtype="float32")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        sf.write(str(output_path), audio, self.sample_rate, subtype="PCM_16")

    def _synthesize_one(self, sentence: str):
        """One sentence to a float32 waveform, or None if it tokenised empty.

        The duration predictor is stochastic, so the same text yields
        slightly different timing each call. We deliberately do not seed
        it: `torch.manual_seed` is global process state, and reaching into
        it from the voice thread would perturb any other torch consumer —
        YOLO shares this process.
        """
        import torch  # lazy: Pi-only, and already resident via transformers

        inputs = self._tokenizer(sentence, return_tensors="pt")
        if inputs["input_ids"].shape[-1] == 0:
            return None

        with self._lock, torch.no_grad():
            waveform = self._model(**inputs).waveform

        return waveform[0].cpu().numpy().astype("float32")
