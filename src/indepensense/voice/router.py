"""Dispatch synthesis to the engine that owns each language.

`PiperTTS` already held a voice per language, which was enough while both
voices were Piper's. They no longer are: English is Piper (`en_US-lessac-
medium`) and Tagalog is Meta MMS (`facebook/mms-tts-tgl`), two different
runtimes with different model formats, sample rates and licences. The
per-language map therefore moves up a level, out of the Piper driver and
into an engine that holds engines.

This is the smallest thing that works. It is not a plugin system: it owns
one dict and one lookup, and every caller still sees the plain `TTSEngine`
protocol, so nothing downstream — the announcer, the voice thread,
`app_mock` — knows more than one engine exists.
"""
from dataclasses import dataclass, field
from pathlib import Path

from indepensense.voice.base import TTSEngine
from indepensense.voice.mms import MmsTTS
from indepensense.voice.piper import PiperTTS
from indepensense.voice.remote import ENGINE_NAME, RemoteTTS


@dataclass(frozen=True)
class RemoteSpec:
    """Everything needed to route a language to the remote endpoint.

    One object rather than four loose arguments because `build_tts` and
    `voice_id` both need the whole set and must agree on it — passing
    them separately is how the two drift until clips are filed under a
    voice the router would not have used.

    `voices` maps language to the server's voice name, and an empty map
    means no language is served remotely, which is what
    `REMOTE_TTS_ENABLED = False` produces.
    """
    url: str
    voices: dict[str, str] = field(default_factory=dict)
    model: str = ENGINE_NAME
    timeout_s: float = 60.0
    peak_dbfs: float | None = None


def remote_spec(
    enabled: bool,
    url: str,
    voices: dict[str, str],
    model: str,
    timeout_s: float,
    peak_dbfs: float | None = None,
) -> RemoteSpec | None:
    """A spec, or None when remote TTS is switched off.

    Exists so the `enabled` check lives in one place rather than at each
    caller: `App._open_tts` and `tools/render_messages` must make the
    same decision, and a disagreement means one of them files clips
    under a voice the other will never look for — the whole store misses
    and every message re-synthesises.

    Still takes configuration as arguments rather than importing it, for
    the reason `build_tts` does: the manual test scripts must not be able
    to resolve against a different set than the device.
    """
    if not enabled or not voices:
        return None
    return RemoteSpec(url=url, voices=dict(voices), model=model,
                      timeout_s=timeout_s, peak_dbfs=peak_dbfs)


class MultiEngineTTS:
    def __init__(self, engines: dict[str, TTSEngine]):
        """Map language codes to the engine that speaks them.

        The first language in the dict is the default when `synthesize` is
        called without one — the same convention `PiperTTS` and
        `FasterWhisperSTT` use, so the three read alike.
        """
        if not engines:
            raise ValueError("MultiEngineTTS requires at least one engine")

        self._engines = dict(engines)
        self._default_language = next(iter(engines))

    def engine_for(self, language: str) -> TTSEngine | None:
        """The engine that owns a language, or None. For diagnostics."""
        return self._engines.get(language)

    def synthesize(
        self,
        text: str,
        output_path: Path,
        language: str | None = None,
    ) -> None:
        lang = language or self._default_language
        engine = self._engines.get(lang)
        if engine is None:
            raise ValueError(
                f"No TTS engine loaded for language '{lang}'. "
                f"Available: {sorted(self._engines)}"
            )
        # The language is passed on rather than dropped: the engine
        # registered here may itself hold several voices, as PiperTTS does.
        engine.synthesize(text, output_path, language=lang)


def build_tts(
    piper_voices: dict[str, Path],
    mms_voices: dict[str, Path],
    remote: RemoteSpec | None = None,
) -> MultiEngineTTS:
    """Assemble the configured engines into one router.

    Takes the two maps as arguments rather than reading `config` itself,
    so `App._open_tts` stays the only place configuration becomes a
    device. What this exists for is the manual test scripts: three of them
    used to build `PiperTTS(voices=PIPER_VOICES)` inline, which after the
    split would have quietly given them an English-only engine and let
    Tagalog go untested on the one machine that can test it.
    """
    engines: dict[str, TTSEngine] = {
        language: PiperTTS(voices={language: path})
        for language, path in piper_voices.items()
    }
    for language, model_dir in mms_voices.items():
        engines[language] = MmsTTS(model_dir=model_dir, language=language)
    # Last, so a remotely-served language overrides the local engine for
    # it. `voice_id` applies the same order; the two must agree or clips
    # are filed under a voice the router would not have used.
    for language, voice in (remote.voices if remote else {}).items():
        engines[language] = RemoteTTS(
            url=remote.url, language=language, voice=voice,
            model=remote.model, timeout_s=remote.timeout_s,
            peak_dbfs=remote.peak_dbfs,
        )
    return MultiEngineTTS(engines)


def voice_id(
    language: str,
    piper_voices: dict[str, Path],
    mms_voices: dict[str, Path],
    remote: "RemoteSpec | None" = None,
) -> str:
    """Identity of the voice that will speak `language`, for clip naming.

    Lives beside `build_tts` and mirrors its precedence — MMS overrides
    Piper for any language both declare — because the two must agree.
    If this named a voice the router would not actually use, every clip
    would be filed under the wrong identity and the cache would serve
    audio from one engine while claiming another.

    Derived from the configured *voice file* rather than the engine
    class, so it changes exactly when the audio would: swapping
    `en_US-lessac-medium` for another Piper voice is as much a change as
    swapping Piper for MMS, and both must invalidate.

    Takes the maps as arguments for the same reason `build_tts` does —
    `App._open_tts` stays the only place configuration becomes a device,
    and the manual test scripts cannot accidentally resolve against a
    different set than the one running.

    Computable without loading a model, which `app._boot_clip_names`
    depends on: the boot clips are hashed before the voice stack exists.
    """
    if remote is not None and language in remote.voices:
        return f"{ENGINE_NAME}:{remote.voices[language]}"
    if language in mms_voices:
        return f"mms:{mms_voices[language].name}"
    if language in piper_voices:
        return f"piper:{piper_voices[language].stem}"
    # A language with no configured voice renders nothing, so nothing
    # will ever be filed under this. Named rather than raising because
    # the caller is usually hashing, not synthesising, and a hash of an
    # unspeakable language is harmless.
    return f"none:{language}"
