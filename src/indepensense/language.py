"""The system's active language, as runtime state.

Language was previously `config.SYSTEM_LANGUAGE`, a constant read at
import time. Everything downstream — Whisper's model choice, Piper's
voice, Tesseract's language pack, the NLU prompt hint, and every spoken
response — already selects by language code, so the only thing standing
between that and runtime switching was the constant itself.

Why a small class instead of a string on `App`
----------------------------------------------

Because more than one object needs to see the *current* value, not a
copy taken at construction. `IntentExecutor` is built once at startup but
must speak whatever language is active when a command arrives, and it is
also what handles the switch request. A plain `str` attribute passed by
value would leave the executor permanently on the startup language. This
holds the value in one place, everyone keeps a reference, and the
persistence and validation live with it rather than being duplicated.

Persistence
-----------

The choice is written to a small text file so it survives a reboot. A
user who switched to English does not want to be greeted in Tagalog after
a power cycle. A missing or unreadable file falls back to the configured
default — never a crash, since an unstartable wearable is worse than one
speaking the wrong language.
"""
import sys
from pathlib import Path


class LanguageState:
    def __init__(
        self,
        default: str,
        supported: tuple[str, ...],
        state_path: Path | None = None,
    ):
        if default not in supported:
            raise ValueError(
                f"default language {default!r} is not in supported {supported!r}"
            )
        self._supported = supported
        self._state_path = state_path
        self._current = self._load(default)

    @property
    def current(self) -> str:
        return self._current

    @property
    def supported(self) -> tuple[str, ...]:
        return self._supported

    def is_supported(self, language: str) -> bool:
        return language in self._supported

    def set(self, language: str) -> bool:
        """Switch language and persist. False if unsupported or unchanged.

        Returning False for an unchanged language lets the caller say
        "I am already speaking English" rather than confirming a switch
        that did nothing.
        """
        if language not in self._supported or language == self._current:
            return False
        self._current = language
        self._persist(language)
        return True

    # -------------------------------------------------------------- internals

    def _load(self, default: str) -> str:
        if self._state_path is None or not self._state_path.exists():
            return default
        try:
            stored = self._state_path.read_text().strip()
        except OSError as exc:
            print(f"[language] could not read {self._state_path}: {exc}", file=sys.stderr)
            return default
        if stored not in self._supported:
            # A stale file from before a language was removed, or a
            # hand-edit typo. Fall back rather than fail.
            print(
                f"[language] stored value {stored!r} is not supported; "
                f"falling back to {default!r}",
                file=sys.stderr,
            )
            return default
        return stored

    def _persist(self, language: str) -> None:
        if self._state_path is None:
            return
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            self._state_path.write_text(language + "\n")
        except OSError as exc:
            # The switch still takes effect for this session; it just
            # won't survive a reboot.
            print(
                f"[language] could not persist to {self._state_path}: {exc}",
                file=sys.stderr,
            )
