"""Every supported language has the models it needs, in exactly one place.

`messages.py` enforces that each language has every *string*. Nothing
enforced that each language has a *voice* — which mattered little while
one dict held them all, and matters now that TTS is split across Piper
and MMS. A language in neither dict crashes at first speech; a language in
both silently loads two models and lets the router's insertion order pick
the winner. Both are startup-time mistakes worth catching on a Mac.
"""
from indepensense import config
from indepensense.intents.messages import LANGUAGES


def test_every_language_has_exactly_one_tts_voice():
    for language in LANGUAGES:
        engines = [
            name
            for name, voices in (("Piper", config.PIPER_VOICES), ("MMS", config.MMS_VOICES))
            if language in voices
        ]
        assert engines, f"{language!r} has no TTS voice in PIPER_VOICES or MMS_VOICES"
        assert len(engines) == 1, f"{language!r} is claimed by both {engines}"


def test_no_voice_is_configured_for_an_unsupported_language():
    """A stale entry here loads a model nothing can ever reach."""
    configured = set(config.PIPER_VOICES) | set(config.MMS_VOICES)
    assert configured == set(LANGUAGES)


def test_every_language_has_a_whisper_model():
    for language in LANGUAGES:
        assert language in config.WHISPER_MODELS


def test_every_language_has_an_ocr_language():
    for language in LANGUAGES:
        assert language in config.OCR_LANGUAGES
