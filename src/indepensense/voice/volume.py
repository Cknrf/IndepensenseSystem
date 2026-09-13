"""Speaker volume, as runtime state backed by the OS audio sink.

Speech is this wearable's only channel to its user, so volume is not a
convenience setting — a device too quiet to hear on a busy road is a
device that has stopped working. Two consequences run through this
module:

  * **There is a floor.** `minimum_percent` is a hard clamp, not a
    suggestion. A user cannot set the volume so low they can no longer
    hear the response that would let them turn it back up, which is a trap
    with no way out on a device with no screen.
  * **Failing to set it is not fatal.** Every OS call is best-effort; a
    missing `wpctl` leaves the wearable at whatever the system default is,
    still talking.

The buzzer is deliberately NOT affected. It is driven straight from GPIO
(`feedback/gpio_buzzer.py`) and never passes through the audio sink, so
obstacle warnings and the emergency acknowledgement keep their loudness
whatever the user does here. Volume control structurally cannot silence a
safety alert.

Why `wpctl`
-----------

Raspberry Pi OS Trixie runs PipeWire, and `wpctl set-volume` is its
supported control surface. `amixer` still exists but talks to ALSA
underneath, which on a PipeWire system adjusts a different mixer than the
one applications actually play through — the classic symptom being a
volume change that appears to work and changes nothing audible.
"""
import subprocess
import sys
from pathlib import Path

# The sink applications play to. `@DEFAULT_AUDIO_SINK@` is a PipeWire alias
# that follows whatever is currently default, so switching between the
# built-in jack, a USB speaker and paired Bluetooth is an OS concern —
# the same reasoning `voice/audio.py` applies to input and output devices.
_DEFAULT_SINK = "@DEFAULT_AUDIO_SINK@"

_COMMAND_TIMEOUT_S = 3.0


class VolumeState:
    """Current speaker volume, clamped, persisted, and pushed to the sink."""

    def __init__(
        self,
        default_percent: int,
        minimum_percent: int,
        maximum_percent: int,
        step_percent: int,
        state_path: Path | None = None,
        apply_on_start: bool = True,
    ):
        if not 0 < minimum_percent <= maximum_percent <= 100:
            raise ValueError(
                f"volume range {minimum_percent}-{maximum_percent} is not a "
                f"valid percentage band"
            )
        self._minimum = minimum_percent
        self._maximum = maximum_percent
        self._step = step_percent
        self._state_path = state_path
        self._current = self.clamp(self._load(default_percent))
        if apply_on_start:
            # The sink keeps whatever the OS last had, which after a reboot
            # is not necessarily what the user chose. Push ours so the
            # stored value is the truth rather than a record of an
            # intention.
            self._apply(self._current)

    # ------------------------------------------------------------------ API

    @property
    def current(self) -> int:
        return self._current

    @property
    def minimum(self) -> int:
        return self._minimum

    @property
    def maximum(self) -> int:
        return self._maximum

    def clamp(self, percent: int) -> int:
        return max(self._minimum, min(self._maximum, percent))

    def set(self, percent: int) -> int:
        """Set the volume, clamped to the allowed band. Returns what took effect.

        Returning the clamped value rather than a success flag is what lets
        the caller say the real number out loud. A user who asked for 10%
        and heard "volume is now 20 percent" has learned the floor exists;
        one who heard "done" would think the device ignored them.
        """
        target = self.clamp(int(percent))
        if target != self._current:
            self._current = target
            self._persist(target)
        self._apply(target)
        return target

    def louder(self) -> int:
        return self.set(self._current + self._step)

    def quieter(self) -> int:
        return self.set(self._current - self._step)

    def at_maximum(self) -> bool:
        return self._current >= self._maximum

    def at_minimum(self) -> bool:
        return self._current <= self._minimum

    # -------------------------------------------------------------- internals

    def _apply(self, percent: int) -> None:
        """Push the value to the audio sink. Best effort, never raises.

        A wearable that refused to start because `wpctl` was missing would
        be a worse outcome than one running at the system default volume.
        """
        try:
            subprocess.run(
                ["wpctl", "set-volume", _DEFAULT_SINK, f"{percent}%"],
                capture_output=True,
                timeout=_COMMAND_TIMEOUT_S,
                check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
            print(
                f"[volume] could not set sink volume to {percent}%: {exc}",
                file=sys.stderr, flush=True,
            )

    def _load(self, default: int) -> int:
        if self._state_path is None or not self._state_path.exists():
            return default
        try:
            return int(self._state_path.read_text().strip())
        except (OSError, ValueError) as exc:
            print(
                f"[volume] could not read {self._state_path}: {exc}; "
                f"using {default}%",
                file=sys.stderr, flush=True,
            )
            return default

    def _persist(self, percent: int) -> None:
        if self._state_path is None:
            return
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            self._state_path.write_text(f"{percent}\n")
        except OSError as exc:
            # Takes effect for this session; it just won't survive a reboot.
            print(
                f"[volume] could not persist to {self._state_path}: {exc}",
                file=sys.stderr, flush=True,
            )
