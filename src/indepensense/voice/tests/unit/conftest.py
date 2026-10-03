"""Fake `sounddevice` / `soundfile` for the audio tests.

`voice/audio.py` imports both lazily, inside the functions that use them.
That is what makes the whole output path testable on a Mac with no audio
stack installed at all — stub the modules into `sys.modules` and the real
`play`, `play_chime` and `stop_playback` run unmodified.

The fake stream is deliberately strict about lifecycle. It counts starts,
stops, aborts and closes per stream, records which *thread* closed each one,
and tracks how many streams are live at once. Those counters are the whole
point: the bug this file exists to prevent was one thread closing a stream
another thread had opened, which PortAudio turns into a process-killing
double free with no Python-level trace. A fake that merely swallowed the
calls would have happily "passed" against the broken code.
"""
import sys
import threading
import types

import pytest

from indepensense.voice import audio


class _FakeStream:
    """One owned stream, with a lifecycle strict enough to catch misuse."""

    def __init__(self, owner: "_FakeSoundDevice", kwargs: dict):
        self.owner = owner
        self.kwargs = kwargs
        # Which PortAudio lifetime this stream's pointer belongs to.
        self.generation = owner.generation
        self.started = 0
        self.stopped = 0
        self.aborted = 0
        self.closed = 0
        self.closed_by: list[str] = []
        self.blocks: list[int] = []

    # -- real sounddevice streams are context managers: __enter__ starts,
    #    __exit__ stops then closes. Mirrored exactly, because the fix
    #    depends on `with` being the only thing that closes the stream.
    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *_exc):
        self.stop()
        self.close()

    def start(self) -> None:
        # `Pa_Terminate` invalidates every stream built before it. The
        # device reports it exactly like this, and nothing else in the
        # fake would notice — which is how a version that re-initialised
        # *after* building the stream passed every test and then failed
        # on the first cue.
        if self.generation != self.owner.generation:
            raise RuntimeError(
                "Error starting stream: Invalid stream pointer "
                "[PaErrorCode -9988]"
            )
        self.started += 1
        with self.owner.lock:
            self.owner.live += 1
            self.owner.max_live = max(self.owner.max_live, self.owner.live)

    def write(self, data) -> None:
        if self.owner.raise_on_write:
            raise RuntimeError("output device disappeared")
        self.blocks.append(len(data))
        if self.owner.after_write is not None:
            self.owner.after_write()
        if self.owner.write_gate is not None:
            self.owner.write_gate.wait(timeout=5.0)

    def read(self, frames):
        return _FakeAudio(frames, self.kwargs.get("channels", 1)), False

    def stop(self) -> None:
        self.stopped += 1

    def abort(self) -> None:
        self.aborted += 1

    def close(self) -> None:
        self.closed += 1
        self.closed_by.append(threading.current_thread().name)
        with self.owner.lock:
            self.owner.live -= 1


class _FakeAudio:
    """Minimal stand-in for the 2-D array `soundfile.read` returns.

    numpy is a Pi-only dependency and is not installed on the dev machine,
    so the tests cannot use a real array. `_write_blocks` only ever asks for
    `len`, `shape` and a slice, so that is all this provides.
    """

    def __init__(self, frames: int, channels: int = 1):
        self.shape = (frames, channels)

    def __len__(self) -> int:
        return self.shape[0]

    def __getitem__(self, index) -> "_FakeAudio":
        start, stop, _ = index.indices(self.shape[0])
        return _FakeAudio(max(0, stop - start), self.shape[1])

    def copy(self) -> "_FakeAudio":
        # The recording paths copy each block out of the callback buffer,
        # which PortAudio reuses — without it every frame would alias the
        # same memory. Real arrays have this; the fake needs it to let the
        # recording functions run at all.
        return _FakeAudio(self.shape[0], self.shape[1])


class _FakeSoundDevice(types.ModuleType):
    """Hands out `_FakeStream`s and refuses to be used the old way.

    `play`, `rec` and `stop` are the module-level API that routes through
    sounddevice's single global context. `audio.py` must never call them
    again, so they record the attempt instead of working — a test asserting
    on `global_calls` fails loudly rather than mysteriously.
    """

    def __init__(self):
        super().__init__("sounddevice")
        self.streams: list[_FakeStream] = []
        self.live = 0
        self.max_live = 0
        self.lock = threading.Lock()
        self.write_gate: threading.Event | None = None
        self.after_write = None
        self.raise_on_write = False
        self.global_calls: list[str] = []
        self.reinits = 0
        self.unsafe_reinits: list[int] = []
        self._initialized = 1        # as `import sounddevice` leaves it
        self.generation = 0          # bumped by every _initialize
        self.fail_initialize = False

    # Present because `audio.py` calls them before every stream, and a
    # fake without them sends the real `_reinitialise_portaudio` down its
    # except branch — which still works, but prints a warning per sound
    # and would bury a genuine regression in the noise.
    #
    # A re-init with a stream live is the double free. It is *recorded*
    # rather than raised because `_reinitialise_portaudio` swallows every
    # exception by design, so an assertion thrown here would be caught
    # and the test would pass anyway.
    #
    # `_initialized` mirrors PortAudio's reference count and raising
    # `paNotInitialized` below mirrors what the real library does when it
    # is already down. Both are the reason `_reinitialise_portaudio` is
    # shaped the way it is; a fake without them leaves its recovery path
    # completely untested, which is how it shipped broken once already.
    def _terminate(self) -> None:
        if self._initialized <= 0:
            raise RuntimeError(
                "Error terminating PortAudio: PortAudio not initialized "
                "[PaErrorCode -10000]"
            )
        if self.live:
            self.unsafe_reinits.append(self.live)
        self._initialized -= 1
        self.reinits += 1

    def _initialize(self) -> None:
        if self.fail_initialize:
            raise RuntimeError("Error initializing PortAudio [PaErrorCode -9986]")
        self._initialized += 1
        self.generation += 1

    def OutputStream(self, **kwargs) -> _FakeStream:     # noqa: N802 — mirrors sounddevice
        if self._initialized <= 0:
            raise RuntimeError("Error querying device -1")
        stream = _FakeStream(self, kwargs)
        with self.lock:
            self.streams.append(stream)
        return stream

    def InputStream(self, **kwargs) -> _FakeStream:      # noqa: N802 — mirrors sounddevice
        return self.OutputStream(**kwargs)

    def play(self, *_args, **_kwargs):
        self.global_calls.append("play")

    def rec(self, *_args, **_kwargs):
        self.global_calls.append("rec")

    def stop(self, *_args, **_kwargs):
        self.global_calls.append("stop")


class _FakeSoundFile(types.ModuleType):
    def __init__(self):
        super().__init__("soundfile")
        self.frames = audio._BLOCK_FRAMES      # one block unless a test says otherwise
        self.samplerate = 22050

    def read(self, _path, dtype=None, always_2d=False):
        return _FakeAudio(self.frames, 1), self.samplerate

    def write(self, *_args, **_kwargs):
        pass


@pytest.fixture
def fake_sf(monkeypatch) -> _FakeSoundFile:
    sf = _FakeSoundFile()
    monkeypatch.setitem(sys.modules, "soundfile", sf)
    return sf


@pytest.fixture
def fake_sd(monkeypatch, fake_sf) -> _FakeSoundDevice:
    sd = _FakeSoundDevice()
    monkeypatch.setitem(sys.modules, "sounddevice", sd)
    # Module-level flags are process-wide; a test that left one set would
    # silently change the meaning of every test after it.
    audio._playing.clear()
    audio._stop_requested.clear()
    audio._portaudio_streams = 0
    yield sd
    audio._playing.clear()
    audio._stop_requested.clear()
    audio._portaudio_streams = 0
    assert not sd.unsafe_reinits, (
        f"PortAudio was re-initialised with {sd.unsafe_reinits} stream(s) "
        "live — that is the double free, not a clipped cue"
    )


@pytest.fixture
def wav(tmp_path):
    path = tmp_path / "speech.wav"
    path.write_bytes(b"")           # the fake reader never looks at it
    return path
