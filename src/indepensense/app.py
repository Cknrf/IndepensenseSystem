"""IndepenSense wearable runtime.

The single long-running process that IS the wearable. Loads models once,
then runs a synchronous fall-detection loop while background threads
handle voice, heartbeats, telemetry retry, and GPS caching.

Concurrency model
-----------------

We have a synchronous main loop for sensor polling PLUS several
well-scoped background threads for I/O concerns:

  - Main thread: 100 Hz MPU6050 read → fall detector → alert on event,
    plus polling both DYP-A22 ultrasonic sensors and firing obstacle
    warnings. Cheap sensor reads only — anything blocking (network,
    LLM, TTS, warning-pattern playback) runs elsewhere.
  - PTT button callback (gpiozero thread pool): spawns a voice thread
    per press. Second press while voice is busy is ignored.
  - Voice thread (one at a time, per PTT session): record → STT →
    parse → execute → TTS → play. Emergency signal aborts mid-way.
    Two sub-steps also run here and also block only this thread:
    destination confirmation (speak the choice, wait for a press) and
    turn-to-face orientation (pulse the user round to the route's
    opening bearing). Both are bounded and both abort on emergency.
  - Emergency button callback: sets cancel flag AND runs the emergency
    handler directly. This preempts voice AND fires the alert without
    waiting for the voice thread to finish. Re-pressing within
    `EMERGENCY_REARM_S` suppresses only the re-send; the cancel and the
    haptic acknowledgement still happen on every press.
  - Repeat button callback: stops speech, cancels a voice command in
    flight, or replays the last response — whichever applies. Every
    press answers with a cue, because silence is also what a dead
    device sounds like.
  - Warning-pattern threads (per obstacle event, and per navigation
    haptic): play a vibration + buzzer pattern under a mutex so
    overlapping patterns don't race. Every driver's `pulse`/`beep`
    sleeps for the pattern's duration, so these can never be called
    from the loop directly.
  - Announcer: the single owner of speech that originates on the main
    loop. `_announce(text)` appends and returns; the worker synthesises
    and plays. Navigation cues used to do both inline, which stopped
    fall detection and obstacle polling for ~3-4 s per turn instruction.
    A critical announcement aborts playback, discards pending
    non-critical items, and abandons anything caught mid-synthesis.
  - Heartbeat sender (already built): every N seconds, non-blocking.
  - Telemetry worker (already built): drains queue, retries failures.
  - GPS cache thread: polls SIM7600 GPS at 1 Hz, exposes latest fix to
    all consumers (executor, heartbeat, fall alerts) without serial
    port contention.

Obstacle detection
------------------

Two DYP-A22 sensors mounted on the cane, both forward-facing:

  - TOP sensor: head-level obstacles (branches, low signage). This is
    the wearable's unique value — the user's cane can't sweep the air
    above them. Warning + danger tiers both include a buzzer beep so
    the alert is audible + haptic.
  - BOTTOM sensor: foot-level obstacles (curbs, low walls). Silent
    vibration only — the user's cane already detects most of these by
    touch, so we notify without nagging.

Two thresholds: 100 cm (warning) and 50 cm (danger). Alerts fire on an
obstacle getting *closer*, not on one being present: entering a tier
alerts once, staying in it is silent, and the tier re-arms only once the
obstacle has receded `OBSTACLE_RELEASE_CM` past the threshold it came in
on. The danger tier alone repeats, every `OBSTACLE_DANGER_REPEAT_S`.

That replaced a flat 2 s cooldown which re-fired for as long as anything
stayed in range — on the bench it produced 136 motor pulses in four and a
half minutes against a wall that never moved. Hysteresis rather than a
"did the distance change" test because the cane is held in a hand: the
reading is never still, so only a band wide enough to swallow that sway
distinguishes an approach from a wobble.

`config.OBSTACLE_BUZZER_ENABLED` mutes the TOP sensor's beep for indoor
bench testing — vibration, tiering and latching are untouched. It must
be True on the deployed device.

Shutdown
--------

SIGINT/SIGTERM sets a shutdown event; the main loop notices, calls
`stop()`, which drains the telemetry queue with a bounded timeout,
stops the heartbeat sender, waits briefly for the voice thread, closes
all sensors and feedback devices. Systemd's `TimeoutStopSec=15` gives
us enough headroom without stalling reboots.

Errors
------

Sensor read failures inside the loop are logged and swallowed — the
loop keeps running so a temporary I²C glitch doesn't take down fall
detection permanently. Fatal errors during startup or an uncaught
exception in the loop propagate to `main()`, which exits non-zero;
systemd's `Restart=on-failure` brings us back up after 5 seconds.

Device construction
-------------------

Every device is constructed in an `_open_*` / `_try_open_*` factory
method and nowhere else — `start()` calls those factories but never a
driver constructor directly. That single rule is what lets `app_mock.py`
subclass this class, override only the factories, and run the entire
runtime on a Mac with the loop, threads and decision logic inherited
untouched. If you add a device, add a factory for it; putting the
constructor inline in `start()` silently drops it out of mock coverage.

`_open_*` means the runtime cannot function without that device and a
failure aborts startup. `_try_open_*` means degraded operation is
acceptable — it logs, returns None, and every caller handles None.
"""
import faulthandler
import hashlib
import os
import signal
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from indepensense.config import (
    BACKEND_URL,
    BATTERY_CHECK_INTERVAL_S,
    BATTERY_EMPTY_RAW_PERCENT,
    BUZZER_GPIO,
    CAMERA_FPS,
    CAMERA_HEIGHT,
    CAMERA_WIDTH,
    FALL_FREEFALL_MIN_DURATION_S,
    FALL_FREEFALL_THRESHOLD_G,
    FALL_IMPACT_THRESHOLD_G,
    FALL_IMPACT_WINDOW_S,
    FALL_POSTURE_IMPACT_THRESHOLD_G,
    FALL_POSTURE_TILT_THRESHOLD_DEG,
    FALL_STILLNESS_DURATION_S,
    FALL_STILLNESS_MAX_STDDEV_G,
    CLOUD_LLM_API_KEY_ENV,
    CLOUD_LLM_ENABLED,
    CLOUD_LLM_MAX_TOKENS,
    CLOUD_LLM_MODEL,
    CLOUD_LLM_TIMEOUT_S,
    CLOUD_LLM_URL,
    CLOUD_CONTEXT_TTL_S,
    CLOUD_MAX_RESPONSE_CHARS,
    COMPASS_CALIBRATED,
    CRITICAL_BATTERY_PERCENT,
    CRITICAL_BATTERY_RECOVERY_PERCENT,
    CRITICAL_BATTERY_STATE_PATH,
    DEFAULT_LANGUAGE,
    DESTINATION_CONFIRM_TIMEOUT_S,
    DEVICE_KEY_PATH,
    DYP_A22_BAUDRATE,
    DYP_A22_BOTTOM_PORT,
    DYP_A22_TOP_PORT,
    EMERGENCY_BUTTON_GPIO,
    EMERGENCY_REARM_S,
    GEOCODE_CANDIDATE_LIMIT,
    GRAPHHOPPER_URL,
    GUARDIAN_CACHE_PATH,
    GUARDIAN_FETCH_TIMEOUT_S,
    HEADING_CHECK_INTERVAL_S,
    HEARTBEAT_INTERVAL_S,
    BACKEND_PROBE_URL,
    CLOUD_LLM_PROBE_URL,
    REACHABILITY_PROBE_TIMEOUT_S,
    LOW_BATTERY_PERCENT,
    LOW_BATTERY_RECOVERY_PERCENT,
    LOW_BATTERY_STATE_PATH,
    MAG_ADDRESS,
    MAG_FORWARD_AXIS,
    MAG_HEADING_OFFSET_DEG,
    MAG_I2C_BUS,
    MAG_LEFT_AXIS,
    MAG_OFFSET_X,
    MAG_OFFSET_Y,
    MAG_OFFSET_Z,
    MAG_SCALE_X,
    MAG_SCALE_Y,
    MAG_SCALE_Z,
    MMS_VOICES,
    MPU6050_ADDRESS,
    MPU6050_I2C_BUS,
    NLU_EMBEDDING_BANK_PATH,
    NLU_EMBEDDING_MARGIN_THRESHOLD,
    NLU_EMBEDDING_MODEL,
    NLU_EMBEDDING_SCORE_THRESHOLD,
    NLU_MODEL,
    NLU_PROMPT_PATH,
    NLU_TIMEOUT_S,
    NLU_WARMUP_TIMEOUT_S,
    OBSTACLE_BUZZER_ENABLED,
    OBSTACLE_DANGER_CM,
    OBSTACLE_DANGER_REPEAT_S,
    OBSTACLE_READING_MAX_AGE_S,
    OBSTACLE_RELEASE_CM,
    OBSTACLE_WARNING_CM,
    OLLAMA_URL,
    ORIENTATION_ALIGNED_TOLERANCE_DEG,
    ORIENTATION_BANDS,
    ORIENTATION_MIN_TARGET_DISTANCE_M,
    ORIENTATION_RELEASE_TOLERANCE_DEG,
    ORIENTATION_TIMEOUT_S,
    PHOTON_URL,
    PIPER_VOICES,
    PTT_BUTTON_GPIO,
    PTT_MAX_RECORDING_S,
    SAVED_PLACES_PATH,
    REPEAT_BUTTON_GPIO,
    LANGUAGE_STATE_PATH,
    SIM7600_GPS_PORT,
    SMS_ALERT_EVENT_TYPES,
    SMS_DEFAULT_COUNTRY_CODE,
    SMS_ENABLED,
    SMS_MODEM_INDEX,
    SMS_SEND_TIMEOUT_S,
    SUPPORTED_LANGUAGES,
    TELEMETRY_TIMEOUT_S,
    UPS_HAT_I2C_BUS,
    VIBRATION_FRONT_GPIO,
    VIBRATION_LEFT_GPIO,
    VIBRATION_RIGHT_GPIO,
    OCR_LANGUAGES,
    OCR_MAX_CHARS,
    SHUTDOWN_COMMAND,
    STARTUP_AUDIO_DIR,
    VOICE_TEST_DIR,
    WAITING_CUE_DELAY_S,
    WAITING_CUE_INTERVAL_S,
    VOLUME_DEFAULT_PERCENT,
    VOLUME_MAX_PERCENT,
    VOLUME_MIN_PERCENT,
    VOLUME_STATE_PATH,
    VOLUME_STEP_PERCENT,
    WHISPER_INITIAL_PROMPTS,
    YOLO_CONFIDENCE_THRESHOLD,
    YOLO_MODEL_PATH,
    WHISPER_MODEL_DIR,
    WHISPER_MODELS,
)
from indepensense.feedback.gpio_button import GPIOButton
from indepensense.feedback.gpio_buzzer import GPIOBuzzer
from indepensense.feedback.gpio_vibration import GPIOVibrationMotor
from indepensense.intents import messages
from indepensense.intents.base import Intent, IntentParser, IntentResult
from indepensense.intents.cloud import OfflineGuard
from indepensense.credential import load_device_credential
from indepensense.intents.mistral import MistralAnswerer
from indepensense.intents.executor import IntentExecutor
from indepensense.intents.embeddings import EmbeddingMatcher, build_matcher
from indepensense.intents.parser import OllamaIntentParser
from indepensense.intents.tiered import TieredIntentParser, describe
from indepensense.language import LanguageState
from indepensense.messaging.mmcli_sms import MMCLISMSSender
from indepensense.navigation.monitor import NavigationCue, NavigationMonitor
from indepensense.navigation.orientation import (
    OrientationGuide,
    first_meaningful_point,
)
from indepensense.power.waveshare_ups_e import WaveshareUPSHatE
from indepensense.routing.base import Coordinate, bearing_to
from indepensense.routing.graphhopper import GraphHopperRouter
from indepensense.routing.places import SavedPlaces
from indepensense.routing.photon import PhotonGeocoder
from indepensense.safety.fall_detector import ThresholdFallDetector
from indepensense.sensors.dyp_a22 import DYPA22
from indepensense.sensors.gps import SIM7600GPS
from indepensense.sensors.mpu6050 import MPU6050
from indepensense.sensors.qmc5883p import QMC5883P
from indepensense.telemetry.base import AlertEvent, EventType
from indepensense.telemetry.buffered import BufferedTelemetryClient
from indepensense.telemetry.guardians import GuardianDirectory
from indepensense.telemetry.heartbeat import PeriodicHeartbeatSender
from indepensense.telemetry.nestjs_client import NestJSTelemetryClient
from indepensense.telemetry.null import NullTelemetryClient
from indepensense.telemetry.sms_alerts import (
    SMS_FAILED,
    SMS_NO_NUMBER,
    SMS_SENT,
    AlertDelivery,
    SMSAlertNotifier,
)
from indepensense.vision.detector import YOLOv8Detector
from indepensense.vision.ocr import TesseractOCR
from indepensense.vision.picamera import PiCamera
from indepensense.voice.audio import (
    is_playing,
    play,
    play_busy_cue,
    play_chime,
    play_stop_cue,
    play_waiting_tick,
    record_until_button,
    stop_playback,
)
from indepensense.voice.base import TTSEngine
from indepensense.voice.router import MultiEngineTTS, build_tts
from indepensense.voice.volume import VolumeState
from indepensense.voice.whisper import FasterWhisperSTT


FALL_LOOP_INTERVAL_S = 0.01     # 100 Hz — matches ThresholdFallDetector's tuning

# Messages rendered to WAV ahead of time rather than synthesised when
# needed. Two different reasons, one mechanism:
#
#   startup   TTS does not exist yet when this plays — it is the first
#             thing `start()` does, minutes before the models finish
#             loading, so it can only ever replay a previous boot's file.
#   thinking  TTS does exist, but this sentence sits in front of the
#             device's slowest path. Synthesising it on every cloud
#             question added ~1 s to the exact wait it exists to excuse.
#
# Name -> message key. The name is also the filename prefix, so adding an
# entry here is the whole change.
_PRERENDERED: dict[str, str] = {
    "startup": "system.starting",
    "thinking": "cloud.thinking",
    "not_heard": "voice.nothing_heard",
}

# Obstacle tiers, ordered. `None` is "clear", so comparing ranks answers
# "did this get worse?" without a chain of string equality checks.
_OBSTACLE_RANK: dict[str | None, int] = {None: 0, "warning": 1, "danger": 2}


def _obstacle_tier_for(distance_cm: float, current: str | None) -> str | None:
    """Which tier a reading puts a sensor in, given where it already was.

    Schmitt-trigger behaviour: a tier is *entered* at its threshold but
    only *left* once the obstacle has receded `OBSTACLE_RELEASE_CM`
    further. Without that gap a reading hovering on a threshold flips tier
    on every frame, and since each entry fires a motor pulse, a cane held
    still at 50 cm would buzz at the sensor's 10 Hz frame rate.

    A free function because it is pure arithmetic over two config values
    and its own argument — no device, no clock, no app state — which is
    what lets the hysteresis table be asserted directly instead of
    inferred from how often a mock motor twitched.
    """
    danger_exit = OBSTACLE_DANGER_CM + OBSTACLE_RELEASE_CM
    warning_exit = OBSTACLE_WARNING_CM + OBSTACLE_RELEASE_CM

    if current == "danger":
        if distance_cm < danger_exit:
            return "danger"
        # Receded out of danger, but possibly only into warning. Use the
        # warning tier's *exit* threshold here too: an obstacle leaving
        # should not have to cross a different line than one approaching.
        return "warning" if distance_cm < warning_exit else None

    if current == "warning":
        if distance_cm < OBSTACLE_DANGER_CM:
            return "danger"
        return "warning" if distance_cm < warning_exit else None

    # Clear: both tiers use their entry thresholds.
    if distance_cm < OBSTACLE_DANGER_CM:
        return "danger"
    return "warning" if distance_cm < OBSTACLE_WARNING_CM else None
GPS_CACHE_INTERVAL_S = 1.0       # 1 Hz — GPS itself only emits ~1 Hz NMEA anyway


class GPSCache:
    """Background-polled GPS cache.

    Only one thread touches the SIM7600 serial port (this class's
    worker). Consumers call `latest_fix()` to get the most recent
    successful read, or None if we've never had a fix.

    Rationale: the executor, heartbeat sender, and fall-alert handler
    all want current position. Sharing a single `SIM7600GPS` instance
    across them and calling `.read()` from multiple threads races on
    the serial port. This adapter isolates the serial reader.
    """

    def __init__(self, gps, poll_interval_s: float = 1.0):
        self._gps = gps
        self._poll_interval_s = poll_interval_s
        self._lock = threading.Lock()
        self._latest_fix = None
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._run, name="gps-cache", daemon=True,
        )

    def start(self) -> None:
        self._stop.clear()
        self._thread.start()

    def stop(self, timeout_s: float = 2.0) -> None:
        self._stop.set()
        self._thread.join(timeout=timeout_s)

    def latest_fix(self):
        with self._lock:
            return self._latest_fix

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                fix = self._gps.read()
                if fix is not None and fix.fix_quality > 0:
                    with self._lock:
                        self._latest_fix = fix
            except Exception as exc:
                print(f"[gps-cache] read error: {exc}", file=sys.stderr, flush=True)
            self._stop.wait(timeout=self._poll_interval_s)


class Announcer:
    """Speaks text on its own thread so the caller never waits for audio.

    Synthesis takes ~1 s and playback several more. Both were being run
    straight from the 100 Hz loop by the navigation-cue path, which meant
    fall detection and obstacle polling stopped for the duration of every
    turn instruction — during navigation, which is exactly when the user
    is walking. `say()` appends and returns; this thread does the waiting.

    The obstacle path already worked this way (`_play_warning_pattern` on
    a spawned thread). This is the same idea with one durable worker
    instead of a thread per event, because speech has to be serialised —
    two overlapping announcements on one output device are unintelligible,
    whereas two vibration motors are not.

    Critical alerts preempt
    -----------------------

    Draining the queue only skips speech that has not started. A fall
    happening midway through "in ninety metres, turn left" has to cut that
    off, not queue behind it, so `say(critical=True)` aborts playback via
    `stop_playback()`, drops pending non-critical items, and goes to the
    front.

    Ordering among non-critical items is plain FIFO. A priority queue was
    considered and rejected: once preemption exists the queue almost never
    holds more than one item, and `queue.PriorityQueue` compares payloads
    when priorities tie, which needs a tiebreaker counter purely to avoid
    sorting announcements alphabetically.

    The language is captured per item rather than read at playback time.
    The text was already rendered by `messages.get(key, language)` before
    it got here, so synthesising it with a voice chosen later would pair
    Tagalog words with an English voice if the user switched in between.
    """

    # Bounded so a misbehaving producer cannot grow it without limit. Eight
    # is far above what the upstream cooldowns and latches allow through
    # (obstacle tiers, per-instruction announce latches, off-route and
    # low-battery latches all rate-limit at the source) — it is a backstop,
    # not the rate limiter.
    _MAX_PENDING = 8

    def __init__(self, tts, output_dir: Path):
        self._tts = tts
        self._output_dir = output_dir
        self._pending: list[tuple[str, str, bool]] = []
        self._lock = threading.Lock()
        self._wakeup = threading.Event()
        self._stop = threading.Event()
        # Bumped by every critical alert. The worker captures it before
        # synthesising and re-checks afterwards, so an announcement that
        # was already in flight when the alert arrived is abandoned instead
        # of played. Without this, `stop_playback()` aborts nothing —
        # synthesis has not reached the speaker yet — and the stale
        # announcement plays in full ahead of the alert that preempted it.
        self._preempt_epoch = 0
        self._thread = threading.Thread(
            target=self._run, name="announcer", daemon=True,
        )

    def start(self) -> None:
        self._stop.clear()
        self._thread.start()

    def stop(self, timeout_s: float = 2.0) -> None:
        """Stop the worker, cutting off anything mid-playback.

        `stop_playback()` is what makes the join bounded: without it a
        worker blocked inside `play()` would hold up shutdown for the
        remaining length of the audio.
        """
        self._stop.set()
        self._wakeup.set()
        stop_playback()
        if self._thread.is_alive():
            self._thread.join(timeout=timeout_s)

    def say(self, text: str, language: str, critical: bool = False) -> None:
        """Queue `text` to be spoken. Returns immediately.

        `critical=True` preempts: playback is aborted, pending non-critical
        announcements are dropped, and this goes to the front.
        """
        if not text:
            return

        if critical:
            stop_playback()

        with self._lock:
            if critical:
                self._preempt_epoch += 1
                dropped = [item for item in self._pending if not item[2]]
                if dropped:
                    print(
                        f"[announcer] critical alert dropped {len(dropped)} "
                        f"pending announcement(s)",
                        flush=True,
                    )
                self._pending = [item for item in self._pending if item[2]]
                self._pending.insert(0, (text, language, True))
            else:
                if len(self._pending) >= self._MAX_PENDING:
                    # Drop the oldest rather than the newest: a stale
                    # instruction is worth less than a current one.
                    stale = self._pending.pop(0)
                    print(
                        f"[announcer] queue full, dropped: {stale[0]!r}",
                        file=sys.stderr, flush=True,
                    )
                self._pending.append((text, language, False))
        self._wakeup.set()

    def clear(self) -> None:
        """Drop everything pending. Does not stop what is already playing."""
        with self._lock:
            self._pending.clear()

    def pending_count(self) -> int:
        with self._lock:
            return len(self._pending)

    def _take(self) -> tuple[tuple[str, str, bool], int] | None:
        """Pop the next item along with the preemption epoch it was taken at."""
        with self._lock:
            if not self._pending:
                return None
            return self._pending.pop(0), self._preempt_epoch

    def _preempted_since(self, epoch: int) -> bool:
        with self._lock:
            return self._preempt_epoch != epoch

    def _run(self) -> None:
        while not self._stop.is_set():
            taken = self._take()
            if taken is None:
                self._wakeup.wait(timeout=0.2)
                self._wakeup.clear()
                continue

            (text, language, critical), epoch = taken
            try:
                timestamp = datetime.now().strftime("%B-%d-%Y_%H-%M-%S-%f")
                path = self._output_dir / f"{timestamp}_announce.wav"
                self._tts.synthesize(text, path, language=language)
                if self._stop.is_set():
                    return
                # Synthesis takes about a second, which is long enough for a
                # fall to happen inside it. Abandon what we just built rather
                # than making the alert wait out an instruction the user no
                # longer needs. Critical items are never abandoned.
                if not critical and self._preempted_since(epoch):
                    print(
                        f"[announcer] preempted before speaking: {text!r}",
                        flush=True,
                    )
                    continue
                play(path)
            except Exception as exc:
                # One bad announcement must not kill the worker — every
                # later warning would go unspoken with nothing to show why.
                print(f"[announcer] failed to speak {text!r}: {exc}",
                      file=sys.stderr, flush=True)


class _CachedGPSAdapter:
    """Implements the GPSSensor protocol on top of a GPSCache.

    Given to the IntentExecutor and PeriodicHeartbeatSender so they can
    read the current position without needing a real SIM7600GPS — those
    consumers see a cached fix that GPSCache refreshes in the background.
    """

    def __init__(self, cache: GPSCache):
        self._cache = cache

    def read(self):
        return self._cache.latest_fix()

    def close(self) -> None:
        pass   # cache owns the real GPS device


class App:
    def __init__(self):
        self._shutdown = threading.Event()

        # Active language, shared by reference with the executor so a
        # switch it handles is visible here on the very next response.
        # Restored from disk, so a user who switched to English is not
        # greeted in Tagalog after a power cycle.
        self.language = LanguageState(
            default=DEFAULT_LANGUAGE,
            supported=SUPPORTED_LANGUAGES,
            state_path=LANGUAGE_STATE_PATH,
        )

        # Voice concurrency: one voice thread at a time; a second PTT
        # press while _voice_active is set is ignored. `_voice_cancel`
        # aborts an in-progress voice cycle — every pipeline stage checks
        # it and bails — and two buttons now set it: emergency, and repeat
        # used as "stop".
        self._voice_active = threading.Event()
        self._voice_cancel = threading.Event()
        # Why the cycle was abandoned, for the log only. One event rather
        # than two because every stage wants the same answer ("stop now");
        # only the reader of a journal afterwards needs to tell an
        # emergency preemption from a user changing their mind. Always
        # assigned BEFORE `_voice_cancel.set()`, so a thread that observes
        # the event observes a reason that is already current.
        self._voice_cancel_reason: str = ""
        self._voice_thread: threading.Thread | None = None

        # Placeholders — filled in by start()
        self.gps: SIM7600GPS | None = None
        self.gps_cache: GPSCache | None = None
        self.imu: MPU6050 | None = None
        self.detector: ThresholdFallDetector | None = None
        self.stt: FasterWhisperSTT | None = None
        self.tts: TTSEngine | None = None
        self.parser: IntentParser | None = None
        self.places: SavedPlaces | None = None
        self.volume: VolumeState | None = None
        # Owns all speech that originates on the main loop. See `Announcer`.
        self.announcer: Announcer | None = None
        self.buffered: BufferedTelemetryClient | None = None
        # `alert_sink` is what every alert path posts to. It is either
        # `buffered` or `buffered` wrapped in an `SMSAlertNotifier` — the
        # wrapper adds guardian SMS to all three alert paths at once.
        # Heartbeats deliberately keep using `buffered` directly.
        self.alert_sink = None
        self.guardians: GuardianDirectory | None = None
        # Loaded in start(). None means this unit is not provisioned: the
        # backend will reject it, so no telemetry client is built at all.
        self.credential = None
        self.sms: MMCLISMSSender | None = None
        # None means "no cloud fallback": unknown utterances get the
        # local "I didn't catch that" instead of being forwarded.
        self.cloud = None
        self.heartbeat_sender: PeriodicHeartbeatSender | None = None
        self.executor: IntentExecutor | None = None
        self.ptt_button: GPIOButton | None = None
        self.emergency_button: GPIOButton | None = None
        self.repeat_button: GPIOButton | None = None
        self.battery: WaveshareUPSHatE | None = None
        self.magnetometer: QMC5883P | None = None
        self.camera: PiCamera | None = None
        # `object_detector` (YOLO) is deliberately named differently from
        # `self.detector` above — that one is the ThresholdFallDetector
        # for the fall-detection state machine. They live in the same
        # class so the names must NOT collide, or one silently
        # overwrites the other (this bug bit us in commit history — the
        # fall detector was shadowed, so the main loop tried to call
        # YOLO.process(reading) and crashed with AttributeError).
        self.object_detector: YOLOv8Detector | None = None
        self.ocr: TesseractOCR | None = None

        # Navigation monitor: tracks user progress against the active route
        # and returns cues (announce / haptic / arrive) as they get near
        # each turn. Owned here so it can be given to the executor
        # (which calls set_route/clear on intent) AND polled from the
        # main loop (which fires the cues).
        self.nav_monitor = NavigationMonitor()
        self._last_nav_check = 0.0

        # Low-battery alert state: latch true after firing so we don't
        # spam the alert on every check. Cleared when battery recovers
        # past the recovery threshold (hysteresis).
        #
        # Restored from disk so it survives a restart — see
        # `config.LOW_BATTERY_STATE_PATH` for why that matters.
        self._low_battery_alerted = self._load_low_battery_latch()
        self._critical_battery_alerted = self._load_latch(CRITICAL_BATTERY_STATE_PATH)
        self._last_battery_check = 0.0

        # Latest compass heading, refreshed at HEADING_CHECK_INTERVAL_S.
        # None until the first successful read (and stays None when no
        # magnetometer is present). Read it via `latest_heading()`.
        self._last_heading_check = 0.0
        self._last_heading_deg: float | None = None

        # Obstacle detection: two DYP-A22 sensors + haptic + audio feedback.
        self.top_sensor: DYPA22 | None = None
        self.bottom_sensor: DYPA22 | None = None
        self.buzzer: GPIOBuzzer | None = None
        self.front_motor: GPIOVibrationMotor | None = None
        self.right_motor: GPIOVibrationMotor | None = None
        self.left_motor: GPIOVibrationMotor | None = None

        # Cooldowns: last time each (sensor, tier) fired. Prevents spam
        # when an obstacle lingers in a zone. Keys look like
        # "top:warning", "bottom:danger", etc.
        # Per sensor: the tier it is currently in (None = clear) and when
        # that tier last fired. Keyed by sensor rather than by
        # (sensor, tier) — a sensor is in exactly one tier at a time, and
        # the old per-tier key is what let a warning and a danger latch
        # coexist and take turns re-firing.
        self._obstacle_tier: dict[str, str | None] = {}
        self._obstacle_last_fired: dict[str, float] = {}
        # Last distance seen by each sensor, with the monotonic clock
        # reading when it arrived. Cached the way `_last_heading_deg` is:
        # a consumer off the main loop must never touch the UART itself.
        self._obstacle_reading: dict[str, tuple[float, float]] = {}

        # When the emergency alert last went out, on the monotonic clock.
        # Negative infinity rather than 0.0: `time.monotonic()` counts from
        # boot on Linux, so a press in the first ten seconds of uptime
        # would compare against 0.0 and be suppressed as a repeat — the
        # one case where swallowing an alert is least acceptable.
        self._last_emergency_fired: float = float("-inf")
        # Whether "already sent" has been spoken since the last real
        # alert. Without it a run of presses queues one critical utterance
        # each, every one preempting the last, and the user hears a
        # stutter of half-sentences instead of an answer.
        self._already_sent_spoken: bool = False
        # Suspends the waiting blip. Set only by the destination
        # confirmation, which is deliberately silent while it waits for a
        # press — blipping through that question would read as the device
        # talking over itself, and `is_playing()` cannot see it because
        # nothing is playing.
        self._waiting_paused = threading.Event()

        # Set by the executor once the user confirms a shutdown; acted on
        # by the voice thread after the goodbye has finished playing.
        self._shutdown_requested = False

        # Mutex around warning playback so two overlapping warnings
        # don't race on the buzzer or motor state.
        self._warning_lock = threading.Lock()

    # ---------------------------------------------------------------- lifecycle

    def start(self) -> None:
        print("Initialising IndepenSense runtime...", flush=True)

        # Before anything slow: tell the user the device is awake. Startup
        # is 2-3 minutes and every second of it is silent otherwise, which
        # to somebody who cannot see the terminal is indistinguishable from
        # a wearable that failed to boot.
        self._play_startup_notice()

        print("  Opening MPU6050...", flush=True)
        self.imu = self._open_imu()
        # Thresholds passed explicitly. They were previously left to the
        # constructor's defaults, which happened to match `config.py` —
        # so editing config silently changed nothing, exactly the trap
        # rule 5 exists to prevent.
        self.detector = ThresholdFallDetector(
            freefall_threshold_g=FALL_FREEFALL_THRESHOLD_G,
            freefall_min_duration_s=FALL_FREEFALL_MIN_DURATION_S,
            impact_threshold_g=FALL_IMPACT_THRESHOLD_G,
            impact_window_s=FALL_IMPACT_WINDOW_S,
            stillness_max_stddev_g=FALL_STILLNESS_MAX_STDDEV_G,
            stillness_duration_s=FALL_STILLNESS_DURATION_S,
            posture_impact_threshold_g=FALL_POSTURE_IMPACT_THRESHOLD_G,
            posture_tilt_threshold_deg=FALL_POSTURE_TILT_THRESHOLD_DEG,
        )

        print("  Opening GPS...", flush=True)
        self.gps = self._try_open_gps()
        cached_gps = None
        if self.gps is not None:
            self.gps_cache = GPSCache(self.gps, poll_interval_s=GPS_CACHE_INTERVAL_S)
            self.gps_cache.start()
            cached_gps = _CachedGPSAdapter(self.gps_cache)

        print("  Loading Whisper models...", flush=True)
        self.stt = self._open_stt()

        print("  Loading TTS voices (Piper + MMS)...", flush=True)
        self.tts = self._open_tts()

        # Started as soon as TTS exists so anything that wants to speak
        # from the loop has somewhere to put it, for the whole of startup.
        self.announcer = Announcer(self.tts, VOICE_TEST_DIR)
        self.announcer.start()

        self.volume = self._open_volume()
        print(f"  Speaker volume {self.volume.current}%.", flush=True)

        print("  Connecting to Ollama (with warmup)...", flush=True)
        self.parser = self._open_parser()

        print("  Checking cloud LLM fallback...", flush=True)
        self.cloud = self._try_open_cloud_answerer()

        print("  Connecting to GraphHopper + Photon...", flush=True)
        router = self._open_router()
        geocoder = self._open_geocoder()

        self.places = self._open_saved_places()
        print(f"  {len(self.places)} saved place(s).", flush=True)

        print("  Loading device credential...", flush=True)
        self.credential = self._load_credential()
        if self.credential is not None:
            print(f"  Device {self.credential.device_id}", flush=True)

        print(f"  Building buffered telemetry to {BACKEND_URL}...", flush=True)
        self.buffered = BufferedTelemetryClient(self._open_telemetry_client())

        # Guardian numbers + emergency SMS. The notifier decorates the
        # telemetry client, so every alert path — fall detection, low
        # battery, and the emergency intent inside the executor — gets
        # SMS without any of them knowing about it. Heartbeats pass
        # straight through. See `telemetry/sms_alerts.py`.
        print("  Fetching guardian contacts...", flush=True)
        self.guardians = GuardianDirectory(
            base_url=BACKEND_URL,
            credential=self.credential,
            cache_path=GUARDIAN_CACHE_PATH,
            timeout_s=GUARDIAN_FETCH_TIMEOUT_S,
            default_country_code=SMS_DEFAULT_COUNTRY_CODE,
        )
        self.guardians.refresh()

        alert_sink = self.buffered
        if SMS_ENABLED:
            print("  Opening SMS sender (mmcli)...", flush=True)
            self.sms = self._try_open_sms()
            if self.sms is not None:
                alert_sink = SMSAlertNotifier(
                    inner=self.buffered,
                    sms=self.sms,
                    guardians=self.guardians,
                    event_type_values=SMS_ALERT_EVENT_TYPES,
                    on_delivery=self._on_alert_delivery,
                )
        self.alert_sink = alert_sink
        reports_delivery = isinstance(alert_sink, SMSAlertNotifier)

        # NB: battery isn't opened yet — wire it after this block. Store
        # the executor construction here anyway so the button handlers
        # can be registered right after. We patch the battery in later.
        self.executor = IntentExecutor(
            router=router,
            geocoder=geocoder,
            gps=cached_gps,
            telemetry=self.alert_sink,
            device_id=self.device_id(),
            monitor=self.nav_monitor,
            language=self.language,
            cloud=self.cloud,
            # Bound method, resolved at call time — `self.ptt_button` is
            # still None right now and gets opened a few lines below.
            confirmer=self._confirm_destination,
            shutdown=self._request_shutdown,
            places=self.places,
            volume=self.volume,
            heading=self.trusted_heading,
            obstacle_ahead=self.obstacle_ahead_cm,
            cloud_max_chars=CLOUD_MAX_RESPONSE_CHARS,
            cloud_context_ttl_s=CLOUD_CONTEXT_TTL_S,
            ocr_max_chars=OCR_MAX_CHARS,
            geocode_candidate_limit=GEOCODE_CANDIDATE_LIMIT,
            reports_delivery=reports_delivery,
        )

        print("  Opening buttons...", flush=True)
        self.ptt_button = self._try_open_button(PTT_BUTTON_GPIO, "PTT")
        self.emergency_button = self._try_open_button(EMERGENCY_BUTTON_GPIO, "Emergency")
        self.repeat_button = self._try_open_button(REPEAT_BUTTON_GPIO, "Repeat")
        if self.ptt_button is not None:
            self.ptt_button.on("pressed", self._on_ptt_press)
        if self.emergency_button is not None:
            self.emergency_button.on("pressed", self._on_emergency_press)
        if self.repeat_button is not None:
            self.repeat_button.on("pressed", self._on_repeat_press)

        print("  Opening buzzer + vibration motors...", flush=True)
        self.buzzer = self._try_open_buzzer()
        self.front_motor = self._try_open_motor(VIBRATION_FRONT_GPIO, "front")
        self.right_motor = self._try_open_motor(VIBRATION_RIGHT_GPIO, "right")
        self.left_motor = self._try_open_motor(VIBRATION_LEFT_GPIO, "left")

        print("  Opening ultrasonic sensors...", flush=True)
        self.top_sensor = self._try_open_ultrasonic(DYP_A22_TOP_PORT, "TOP")
        self.bottom_sensor = self._try_open_ultrasonic(DYP_A22_BOTTOM_PORT, "BOTTOM")

        print("  Opening UPS HAT (battery)...", flush=True)
        self.battery = self._try_open_battery()

        print("  Opening magnetometer (QMC5883P compass)...", flush=True)
        self.magnetometer = self._try_open_magnetometer()

        print("  Opening camera + YOLO detector...", flush=True)
        self.camera = self._try_open_camera()
        self.object_detector = self._try_open_detector()

        print("  Opening Tesseract OCR...", flush=True)
        self.ocr = self._try_open_ocr()

        # Late-bind battery + camera + detector + ocr into the executor.
        # They weren't ready at executor construction time; injecting
        # them now lets vision.*/device.status work without a bigger
        # startup reshuffle.
        if self.executor is not None:
            self.executor._battery = self.battery
            self.executor._camera = self.camera
            self.executor._detector = self.object_detector
            self.executor._ocr = self.ocr

        print("  Starting heartbeat sender...", flush=True)
        self.heartbeat_sender = PeriodicHeartbeatSender(
            telemetry=self.buffered,
            gps=cached_gps,
            device_id=self.device_id(),
            interval_s=HEARTBEAT_INTERVAL_S,
            battery=self.battery,
            reachability_probe_url=BACKEND_PROBE_URL,
            reachability_probe_timeout_s=REACHABILITY_PROBE_TIMEOUT_S,
        )
        self.heartbeat_sender.start()

        print(
            f"Ready (language: {self.language.current}). Running fall-detection "
            f"loop. SIGINT/SIGTERM to stop.",
            flush=True,
        )
        self._speak_greeting()
        # Now that TTS exists, make sure the next boot can speak at second
        # zero. Deliberately last: it costs a synthesis per language and
        # the user is already up and running by this point.
        self._render_prerendered()

    def run(self) -> None:
        """Main 100 Hz sensor loop. Blocks until shutdown.

        Each tick reads the MPU6050 (for fall detection) and both
        ultrasonic sensors (for obstacle detection). All three drivers
        return quickly — MPU6050 does one I²C burst; DYP-A22 returns
        None if no new UART frame has arrived. No blocking I/O here.

        Battery, navigation and heading are checked on every tick too, but
        each self-throttles internally to its own much slower interval.
        """
        try:
            while not self._shutdown.is_set():
                # Fall detection
                try:
                    if self.imu is not None:
                        reading = self.imu.read()
                        if reading is not None and self.detector is not None:
                            event = self.detector.process(reading)
                            if event is not None:
                                self._on_fall_detected(event)
                except Exception as exc:
                    # Log and continue — a single bad I²C read is not
                    # a reason to take down fall detection permanently.
                    print(f"[fall-loop] read error: {exc}", file=sys.stderr, flush=True)

                # Obstacle detection — poll both sensors. DYP-A22 emits
                # ~10 Hz, so at 100 Hz main-loop rate 9 out of 10 reads
                # return None. That's fine.
                self._check_obstacle_sensor("top", self.top_sensor)
                self._check_obstacle_sensor("bottom", self.bottom_sensor)

                # Battery check — throttled to `BATTERY_CHECK_INTERVAL_S`
                # since battery changes slowly. Rate limiting is inside
                # the method (skips if last check was recent).
                self._check_battery_and_alert()

                # Navigation cues — check every ~1 s against the active
                # route. Fires announce/haptic/arrive as user approaches
                # turns. No-op when there's no active navigation.
                self._check_navigation()

                # Compass heading — throttled to `HEADING_CHECK_INTERVAL_S`.
                # Caches the latest reading; nothing acts on it yet.
                self._check_heading()

                self._shutdown.wait(timeout=FALL_LOOP_INTERVAL_S)
        finally:
            self.stop()

    def stop(self) -> None:
        print("Shutting down...", flush=True)
        self._shutdown.set()

        # Cancel any in-flight voice cycle so the pipeline notices and exits.
        self._voice_cancel.set()

        # Before the telemetry drain: this aborts playback, so a worker
        # part-way through a long announcement doesn't hold up shutdown
        # for the remaining seconds of audio.
        if self.announcer is not None:
            self.announcer.stop(timeout_s=2.0)

        if self.heartbeat_sender is not None:
            self.heartbeat_sender.stop(timeout_s=2.0)

        if self.buffered is not None:
            drained = self.buffered.close(drain_timeout_s=5.0)
            print(f"Telemetry queue drained fully: {drained}", flush=True)

        if self._voice_thread is not None and self._voice_thread.is_alive():
            print("Waiting for voice thread...", flush=True)
            self._voice_thread.join(timeout=2.0)

        if self.gps_cache is not None:
            self.gps_cache.stop(timeout_s=2.0)

        # Turn off any actuator that might still be on (a warning
        # pattern could have been mid-play when shutdown fired).
        for motor in (self.front_motor, self.right_motor, self.left_motor):
            if motor is not None:
                try:
                    motor.off()
                except Exception:
                    pass
        if self.buzzer is not None:
            try:
                self.buzzer.off()
            except Exception:
                pass

        # Best-effort close on everything else — never fail shutdown.
        for name, resource in (
            ("GPS", self.gps),
            ("MPU6050", self.imu),
            ("TOP ultrasonic", self.top_sensor),
            ("BOTTOM ultrasonic", self.bottom_sensor),
            ("UPS HAT", self.battery),
            ("Magnetometer", self.magnetometer),
            ("Camera", self.camera),
            ("OCR", self.ocr),
            ("SMS", self.sms),
            ("Cloud LLM", self.cloud),
            ("PTT button", self.ptt_button),
            ("Emergency button", self.emergency_button),
            ("Repeat button", self.repeat_button),
            ("Buzzer", self.buzzer),
            ("Front motor", self.front_motor),
            ("Right motor", self.right_motor),
            ("Left motor", self.left_motor),
        ):
            if resource is None:
                continue
            try:
                resource.close()
            except Exception as exc:
                print(f"  [{name}] close error: {exc}", file=sys.stderr, flush=True)

        print("Shutdown complete.", flush=True)

    # ---------------------------------------------------------------- fall

    def _on_fall_detected(self, event) -> None:
        print(
            f"[FALL DETECTED] impact={event.impact_magnitude_g:.2f} g "
            f"freefall={event.freefall_duration_s * 1000:.0f} ms",
            flush=True,
        )

        # Tell the wearer, not only the guardian. Until this existed, the
        # person who had just fallen over was the one party not informed —
        # they had no way to know whether anyone had been alerted.
        #
        # Critical, so it interrupts a turn instruction or scene
        # description already in progress; and queued rather than spoken
        # here, because this runs on the 100 Hz loop and speaking inline
        # would stop fall detection for the length of the sentence.
        self._announce(
            messages.get("fall.detected", self.language.current), critical=True,
        )

        # Use current cached GPS fix; fall back to 0.0/0.0 if unknown.
        # The alert goes out regardless — safety > location precision.
        lat, lon = 0.0, 0.0
        if self.gps_cache is not None:
            fix = self.gps_cache.latest_fix()
            if fix is not None:
                lat, lon = fix.lat, fix.lon

        alert = AlertEvent(
            device_id=self.device_id(),
            event_type=EventType.FALL_DETECTION,
            latitude=lat,
            longitude=lon,
            occurred_at=datetime.now(timezone.utc),
        )
        if self.alert_sink is not None:
            self.alert_sink.send_alert(alert)

    # ---------------------------------------------------------------- battery

    def _check_battery_and_alert(self) -> None:
        """Poll battery, warn the wearer, and alert guardians on crossing.

        Called from the 100 Hz main loop but internally rate-limited to
        `BATTERY_CHECK_INTERVAL_S` — battery changes slowly, no reason
        to hammer the I²C bus. Hysteresis (separate fire + recovery
        thresholds) prevents alert flapping when hovering at a threshold.

        Two tiers, and they notify different people:

          - `LOW_BATTERY_PERCENT` (15%) — guardians get the HTTP alert and
            an SMS, and the wearer is told to charge soon. Until this
            existed only the guardians knew; the person actually carrying
            the device found out when it died.
          - `CRITICAL_BATTERY_PERCENT` (5%) — spoken only, and critical so
            it interrupts. No second guardian alert: they were told at 15%
            over two channels and a repeat says nothing they can act on.

        Each tier owns an independent latch so neither can clear the other.
        """
        if self.battery is None:
            return

        now = time.monotonic()
        if now - self._last_battery_check < BATTERY_CHECK_INTERVAL_S:
            return
        self._last_battery_check = now

        try:
            reading = self.battery.read()
        except Exception as exc:
            print(f"[battery] read error: {exc}", file=sys.stderr, flush=True)
            return
        if reading is None:
            return

        pct = reading.percentage

        # The critical tier answers to two signals, not one.
        #
        # `percentage` is a calibration against one pack
        # (`BATTERY_EMPTY_RAW_PERCENT`), and the whole reason that
        # constant exists is that the gauge cannot be trusted — so keying
        # every warning to a corrected version of the same untrusted
        # number leaves no cross-check. `is_critical_low` is a cell under
        # 3.15 V, the BMS's own cutoff: measured rather than estimated,
        # and still right if the calibration is wrong. It was written
        # when the driver was, and read by nothing until now.
        #
        # Either fires it. BOTH must be clear to release it — a latch
        # cleared on percentage alone would re-fire the voltage warning
        # every check for as long as a cell stayed low while the gauge
        # read healthy, which is precisely the pair of states this
        # cross-check exists to catch.
        voltage_critical = reading.is_critical_low

        # Hysteresis: only fire if we haven't already alerted, and we're
        # below the fire threshold. Clear the latch once we recover
        # above the recovery threshold (typically higher — e.g. 20% —
        # so quick sags near 15% don't retrigger).
        if self._low_battery_alerted:
            if pct >= LOW_BATTERY_RECOVERY_PERCENT:
                print(
                    f"[battery] recovered to {pct}% — LOW_BATTERY latch cleared",
                    flush=True,
                )
                self._set_low_battery_latch(False)
        else:
            if pct < LOW_BATTERY_PERCENT and reading.is_discharging:
                print(
                    f"[battery] {pct}% — firing LOW_BATTERY alert",
                    flush=True,
                )
                self._fire_low_battery_alert(pct)
                self._announce(
                    messages.get(
                        "battery.low_warning", self.language.current, percent=pct,
                    )
                )
                self._set_low_battery_latch(True)

        # Critical tier, checked independently — a device that boots below
        # 5% has both latches unset and should still say the urgent thing.
        if self._critical_battery_alerted:
            if pct >= CRITICAL_BATTERY_RECOVERY_PERCENT and not voltage_critical:
                print(
                    f"[battery] recovered to {pct}% — CRITICAL latch cleared",
                    flush=True,
                )
                self._set_critical_battery_latch(False)
        else:
            gauge_critical = pct < CRITICAL_BATTERY_PERCENT and reading.is_discharging
            if gauge_critical or voltage_critical:
                print(
                    f"[battery] critical, warning the wearer — "
                    f"gauge {pct}% (raw {reading.raw_percentage}%), "
                    f"lowest cell {min(reading.cell_voltages_mv)} mV",
                    flush=True,
                )
                self._announce(
                    messages.get(
                        "battery.critical_warning",
                        self.language.current,
                        percent=pct,
                    ),
                    critical=True,
                )
                self._set_critical_battery_latch(True)

    def obstacle_ahead_cm(self) -> float | None:
        """Distance to whatever the forward sensor sees, or None.

        Exists so `vision.describe` can answer with *something* when YOLO
        recognises nothing. The wearable used to say "I don't see anything
        I recognize" while a sensor on the same device had an obstacle at
        42 cm — two subsystems that never spoke to each other.

        The TOP sensor only. BOTTOM points at foot level and therefore
        sees the ground on most readings, so folding it in would answer
        "something is 80 centimetres away" to almost every question — true,
        useless, and the cane already covers that height anyway. TOP is
        the one looking where the camera looks.

        None rather than a number in three cases, each of which would
        otherwise produce a confident wrong answer:
          - no sensor, or no reading yet
          - the reading is older than `OBSTACLE_READING_MAX_AGE_S`; the
            DYP-A22 emits at ~10 Hz, so anything older means the sensor
            has stopped reporting and the user has since moved
          - nothing is within `OBSTACLE_WARNING_CM`, i.e. there is no
            obstacle to describe
        """
        reading = self._obstacle_reading.get("top")
        if reading is None:
            return None
        distance, stamped_at = reading
        if time.monotonic() - stamped_at > OBSTACLE_READING_MAX_AGE_S:
            return None
        return distance if distance < OBSTACLE_WARNING_CM else None

    def latest_heading(self) -> float | None:
        """Most recent compass reading in degrees, calibrated or not.

        Never touches the I²C bus — returns whatever `_check_heading` last
        cached. `None` means either no magnetometer or no successful read
        yet.

        This is the *raw* value, for bring-up and for anything that wants
        to see what the sensor is saying. **Navigation must not use it** —
        see `trusted_heading`.
        """
        return self._last_heading_deg

    def trusted_heading(self) -> float | None:
        """Heading a consumer may actually act on, or None.

        The same cached reading, but withheld entirely until
        `config.COMPASS_CALIBRATED` says the compass has been calibrated on
        the assembled unit.

        The distinction exists because of how this sensor fails. With
        identity offsets and the flat-board axis defaults, it does not
        produce an obviously broken heading — it produces a *plausible* one
        that may be mirrored or tens of degrees out, and a bearing like
        that sends the user the wrong way with nothing to show them it is
        wrong. Returning None means every consumer falls back to the
        behaviour it had before the compass existed, which is merely less
        helpful rather than actively misleading.

        This is the accessor navigation is wired to. `latest_heading` stays
        raw so bring-up and the calibration sweep are unaffected.
        """
        if not COMPASS_CALIBRATED:
            return None
        return self.latest_heading()

    def _check_heading(self) -> None:
        """Refresh the cached compass heading.

        Called from the 100 Hz main loop but internally rate-limited to
        `HEADING_CHECK_INTERVAL_S` — heading changes on human timescales and
        the I²C bus is shared with the IMU, both ultrasonics and the UPS HAT.

        Caching rather than acting: no consumer uses heading yet. Wiring it
        into navigation turn verification needs a trustworthy compass first,
        and `MAG_OFFSET_X/Y/Z` and `MAG_SCALE_X/Y/Z` are still at their
        identity values — calibration has never been run. See
        `magnetometer_calibrate` in sensors/tests/manual.

        A stale reading is kept on failure. That is deliberate: heading is
        advisory, and a transient I²C glitch should not blank it.
        """
        if self.magnetometer is None:
            return

        now = time.monotonic()
        if now - self._last_heading_check < HEADING_CHECK_INTERVAL_S:
            return
        self._last_heading_check = now

        try:
            reading = self.magnetometer.read()
        except Exception as exc:
            print(f"[heading] read error: {exc}", file=sys.stderr, flush=True)
            return
        if reading is None:
            return

        self._last_heading_deg = reading.heading_deg

    def _load_low_battery_latch(self) -> bool:
        """Whether we had already alerted before this process started."""
        return self._load_latch(LOW_BATTERY_STATE_PATH)

    def _load_latch(self, path: Path) -> bool:
        """Read a presence-is-the-state latch file.

        Any read problem is treated as "not alerted". The cost of getting
        that wrong is one extra alert; the cost of the opposite would be a
        low battery that never warns anyone.
        """
        try:
            return path.exists()
        except OSError as exc:
            print(f"[battery] could not read latch: {exc}", file=sys.stderr, flush=True)
            return False

    def _set_low_battery_latch(self, alerted: bool) -> None:
        self._low_battery_alerted = alerted
        self._write_latch(LOW_BATTERY_STATE_PATH, alerted)

    def _set_critical_battery_latch(self, alerted: bool) -> None:
        self._critical_battery_alerted = alerted
        self._write_latch(CRITICAL_BATTERY_STATE_PATH, alerted)

    def _write_latch(self, path: Path, alerted: bool) -> None:
        """Mirror a latch to disk.

        Presence of the file is the state — no contents to parse, so a
        truncated write cannot be misread. Persistence is best effort: if
        the write fails the latch still holds for this session, it just
        won't survive a restart.
        """
        try:
            if alerted:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
            else:
                path.unlink(missing_ok=True)
        except OSError as exc:
            print(f"[battery] could not persist latch: {exc}", file=sys.stderr, flush=True)

    def _fire_low_battery_alert(self, percentage: int) -> None:
        """POST a Low Battery alert to the guardian backend."""
        lat, lon = 0.0, 0.0
        if self.gps_cache is not None:
            fix = self.gps_cache.latest_fix()
            if fix is not None:
                lat, lon = fix.lat, fix.lon
        alert = AlertEvent(
            device_id=self.device_id(),
            event_type=EventType.LOW_BATTERY,
            latitude=lat,
            longitude=lon,
            occurred_at=datetime.now(timezone.utc),
        )
        if self.alert_sink is not None:
            self.alert_sink.send_alert(alert)

    # ---------------------------------------------------------------- navigation

    def _check_navigation(self) -> None:
        """Poll the navigation monitor and fire any resulting cues.

        Throttled to ~1 Hz — GPS updates once per second at best, so
        checking faster wastes cycles on identical data. Skips entirely
        when there's no active navigation OR no GPS fix (nothing useful
        to compare against).
        """
        if not self.nav_monitor.is_active():
            return
        if self.gps_cache is None:
            return
        now = time.monotonic()
        if now - self._last_nav_check < 1.0:
            return
        self._last_nav_check = now

        fix = self.gps_cache.latest_fix()
        if fix is None:
            return

        position = Coordinate(lat=fix.lat, lon=fix.lon)
        try:
            # Heading is None until the compass is calibrated, which turns
            # turn verification off and leaves every other cue unchanged.
            cues = self.nav_monitor.check(
                position, heading=self.trusted_heading(),
            )
        except Exception as exc:
            print(f"[nav] monitor error: {exc}", file=sys.stderr, flush=True)
            return

        for cue in cues:
            self._fire_navigation_cue(cue)

    def _fire_navigation_cue(self, cue: NavigationCue) -> None:
        """Route a NavigationCue to its actuator, without blocking.

        - "announce": speak the text (skipped if the voice pipeline is
          busy — we don't want to talk over a user's command or a
          response mid-play).
        - "haptic": pulse the direction-matching motor.
        - "arrive": speak + pulse all motors (louder cue for the finish).
        - "off_route": speak + a distinctive all-motor pulse.

        **This runs on the 100 Hz loop, so nothing here may block.** It
        used to: speech went through `_speak_error` (~3-4 s of synthesis
        and playback) and the motor pulses slept inline (~0.3-0.5 s), which
        stopped fall detection and obstacle polling for the whole of every
        turn instruction. Speech now goes to the `Announcer`; haptics go to
        a spawned thread under `_warning_lock`, matching what
        `_check_obstacle_sensor` has always done.
        """
        try:
            if cue.kind == "announce":
                if self._voice_active.is_set():
                    print(
                        f"[nav] deferred announce (voice busy): {cue.text}",
                        flush=True,
                    )
                    return
                print(f"[nav] announce: {cue.text}", flush=True)
                self._announce(cue.text)
            elif cue.kind == "haptic":
                motor = self._motor_for_direction(cue.direction)
                if motor is not None:
                    print(f"[nav] haptic: {cue.direction}", flush=True)
                    self._spawn_haptic(
                        f"nav-haptic-{cue.direction}",
                        lambda m=motor: m.pulse(times=2, duration_s=0.2, gap_s=0.1),
                    )
            elif cue.kind == "arrive":
                print(f"[nav] arrive: {cue.text}", flush=True)
                self._spawn_haptic(
                    "nav-arrive", lambda: self._pulse_all_motors(duration_s=0.4),
                )
                if not self._voice_active.is_set() and cue.text is not None:
                    self._announce(cue.text)
            elif cue.kind == "missed_turn":
                # The compass says they carried straight on. Say so and
                # pulse the side they should have gone, so the correction
                # is available through both channels. Off-route detection
                # is still running underneath as the slower backstop.
                if self._voice_active.is_set():
                    print(
                        f"[nav] deferred missed_turn (voice busy): {cue.text}",
                        flush=True,
                    )
                    return
                print(f"[nav] missed_turn: {cue.text}", flush=True)
                motor = self._motor_for_direction(cue.direction)
                if motor is not None:
                    self._spawn_haptic(
                        f"nav-missed-{cue.direction}",
                        lambda m=motor: m.pulse(times=3, duration_s=0.15, gap_s=0.1),
                    )
                self._announce(
                    messages.get(
                        "nav.missed_turn",
                        self.language.current,
                        instruction=cue.text or "",
                    )
                )
            elif cue.kind == "off_route":
                if self._voice_active.is_set():
                    print(
                        f"[nav] deferred off_route (voice busy): {cue.text}",
                        flush=True,
                    )
                    return
                print(f"[nav] off_route: {cue.text}", flush=True)
                self._spawn_haptic(
                    "nav-off-route", lambda: self._pulse_all_motors(duration_s=0.3),
                )
                if cue.text is not None:
                    self._announce(cue.text)
        except Exception as exc:
            print(f"[nav] fire error: {exc}", file=sys.stderr, flush=True)

    def _announce(self, text: str, critical: bool = False) -> None:
        """Speak `text` without waiting for it. Safe from the main loop.

        `critical=True` cuts off whatever is playing and discards pending
        non-critical announcements — for events the user must hear now,
        not after the turn instruction ahead of them in the queue.

        A missing announcer (a test that never called `start()`) is a
        no-op rather than an error: losing an announcement is not worth
        taking down the loop that detects falls.

        **Never raises**, the same contract `_speak_error` carries, and for
        a sharper reason here. Callers interleave this with work that must
        happen regardless: `_on_fall_detected` sends the alert that summons
        help, and `_check_battery_and_alert` sets the latch that stops the
        guardian SMS re-firing every ten seconds. An exception escaping
        this would silently skip whichever of those came after it.
        """
        if self.announcer is None:
            return
        try:
            self.announcer.say(text, self.language.current, critical=critical)
        except Exception as exc:
            print(f"[announce] could not queue {text!r}: {exc}",
                  file=sys.stderr, flush=True)

    def _spawn_haptic(self, name: str, action) -> None:
        """Run a blocking motor/buzzer pattern off the calling thread.

        The same shape `_check_obstacle_sensor` uses: every driver's
        `pulse`/`beep` sleeps for the pattern's duration, so calling one
        from the main loop stalls it. `_warning_lock` serialises overlapping
        patterns so two events don't leave a motor stuck on.
        """
        def _run() -> None:
            with self._warning_lock:
                try:
                    action()
                except Exception as exc:
                    print(f"[haptic:{name}] error: {exc}", file=sys.stderr, flush=True)

        threading.Thread(target=_run, name=name, daemon=True).start()

    def _motor_for_direction(self, direction: str | None):
        """Map a direction string to the motor that should fire.

        Returns None for unknown directions or when the motor is not
        available (e.g. running without hardware).
        """
        if direction == "left":
            return self.left_motor
        if direction == "right":
            return self.right_motor
        if direction == "straight":
            return self.front_motor
        return None

    # ---------------------------------------------------------------- obstacles

    def _check_obstacle_sensor(self, sensor_name: str, sensor: DYPA22 | None) -> None:
        """Poll one ultrasonic sensor and alert on a *newly* closer obstacle.

        Called from the main 100 Hz loop. Returns fast when the sensor has
        no fresh frame (which is 9 out of 10 ticks — DYP-A22 emits at
        ~10 Hz).

        Fires on **escalation**, not on presence. Entering a tier alerts
        once; staying in it is silent; receding past the release threshold
        re-arms it. The one exception is the danger tier, which repeats
        every `OBSTACLE_DANGER_REPEAT_S` so a standing hazard is not
        announced once and then forgotten.

        This replaced a fixed two-second cooldown that re-fired for as
        long as anything stayed in range — a field log shows `danger at
        42 cm` every two seconds for minutes, each one a motor pulse.
        Hysteresis is what makes "newly closer" survive a cane that is
        never quite still; see `OBSTACLE_RELEASE_CM`.

        A de-escalation is deliberately silent. Dropping from danger back
        to warning means the hazard is receding, and announcing that with
        the warning pattern would spend the user's attention to tell them
        something is getting better.
        """
        if sensor is None:
            return
        try:
            reading = sensor.read()
        except Exception as exc:
            print(f"[obstacle:{sensor_name}] read error: {exc}", file=sys.stderr, flush=True)
            return
        if reading is None:
            return

        distance = reading.distance_cm
        # Cached for `obstacle_ahead_cm`, which lets `vision.describe`
        # answer with a distance when the camera recognised nothing.
        # Stamped with the clock rather than just stored: a reading is
        # only worth repeating while it is still roughly true.
        self._obstacle_reading[sensor_name] = (distance, time.monotonic())

        previous = self._obstacle_tier.get(sensor_name)
        tier = _obstacle_tier_for(distance, previous)
        self._obstacle_tier[sensor_name] = tier

        if tier is None:
            # Clear. The re-arm already happened by storing None above.
            if previous is not None:
                print(
                    f"[obstacle:{sensor_name}] clear at {distance:.0f} cm",
                    flush=True,
                )
            return

        now = time.monotonic()
        escalated = _OBSTACLE_RANK[tier] > _OBSTACLE_RANK[previous]
        if escalated:
            reason = "entered"
        elif tier == "danger" and (
            now - self._obstacle_last_fired.get(sensor_name, 0.0)
            >= OBSTACLE_DANGER_REPEAT_S
        ):
            reason = "still"
        else:
            return

        self._obstacle_last_fired[sensor_name] = now
        print(
            f"[obstacle:{sensor_name}] {tier} at {distance:.0f} cm ({reason})",
            flush=True,
        )

        # Play the warning pattern in a background thread so the main
        # loop keeps ticking. A single mutex serialises overlapping
        # warnings — if TOP and BOTTOM fire simultaneously, one waits.
        threading.Thread(
            target=self._play_warning_pattern,
            args=(sensor_name, tier),
            name=f"warn-{sensor_name}-{tier}",
            daemon=True,
        ).start()

    def _play_warning_pattern(self, sensor_name: str, tier: str) -> None:
        """Play the feedback pattern for a given sensor+tier.

        Held under `_warning_lock` so overlapping calls play in sequence
        instead of racing on the buzzer or motor state.

        Feedback matrix (see docstring at top of module):

          TOP + warning  → front motor pulse + one short beep
          TOP + danger   → all 3 motors + two rapid beeps
          BOTTOM + warn  → front motor pulse (silent — cane covers this)
          BOTTOM + danger→ all 3 motors (silent)

        Both TOP beeps are suppressed when `OBSTACLE_BUZZER_ENABLED` is
        False (bench mute); the vibration half of each pattern still plays.
        """
        with self._warning_lock:
            try:
                if sensor_name == "top" and tier == "warning":
                    if self.front_motor is not None:
                        self.front_motor.pulse(times=1, duration_s=0.25)
                    if OBSTACLE_BUZZER_ENABLED and self.buzzer is not None:
                        self.buzzer.beep(times=1, duration_s=0.1)
                elif sensor_name == "top" and tier == "danger":
                    self._pulse_all_motors(duration_s=0.4)
                    if OBSTACLE_BUZZER_ENABLED and self.buzzer is not None:
                        self.buzzer.beep(times=2, duration_s=0.08, gap_s=0.05)
                elif sensor_name == "bottom" and tier == "warning":
                    if self.front_motor is not None:
                        self.front_motor.pulse(times=1, duration_s=0.25)
                elif sensor_name == "bottom" and tier == "danger":
                    self._pulse_all_motors(duration_s=0.4)
            except Exception as exc:
                print(f"[warning-pattern] error: {exc}", file=sys.stderr, flush=True)

    def _pulse_all_motors(self, duration_s: float) -> None:
        """Turn all three motors on for `duration_s`, then off.

        Simpler than three concurrent `.pulse()` calls (which would each
        spawn their own timing). One coordinated on/sleep/off keeps the
        three motors in phase.
        """
        motors = [m for m in (self.front_motor, self.right_motor, self.left_motor) if m is not None]
        for m in motors:
            m.on()
        time.sleep(duration_s)
        for m in motors:
            m.off()

    # ---------------------------------------------------------------- buttons

    def _on_ptt_press(self) -> None:
        """PTT press handler. First press spawns a voice thread; presses
        while a voice thread is running are ignored (per design).

        Feedback on press: brief all-motor pulse + rising audio chime so
        the user knows the mic is now live. Feedback runs BEFORE
        recording starts so the chime isn't captured in the audio.
        """
        if self._voice_active.is_set():
            # Answer the press even though it is refused. A button that
            # produces nothing at all is indistinguishable from a button
            # that is broken, and this is the one the user reaches for
            # when they think the device has stopped listening.
            print("[PTT] Voice pipeline busy — press ignored.", flush=True)
            self._play_cue(play_busy_cue)
            return

        self._voice_active.set()
        self._voice_cancel_reason = ""
        self._voice_cancel.clear()
        self._play_press_feedback(rising_chime=True)
        self._voice_thread = threading.Thread(
            target=self._voice_pipeline, name="voice", daemon=True,
        )
        self._voice_thread.start()

    def _on_emergency_press(self) -> None:
        """Emergency press handler. Cancels any voice work and fires
        the emergency alert immediately.

        Feedback: buzzer three fast beeps (buzzer is loud on purpose here —
        emergencies SHOULD be loud) + all-motor pulse. Then the spoken
        confirmation, queued as critical so it cuts off anything mid-
        sentence rather than waiting behind it.

        The confirmation used to be synthesised and played right here, on
        gpiozero's callback thread. That made this a second, uncoordinated
        speaker — it could talk over the announcer — and it tied up a
        callback thread for the length of the sentence. Going through the
        announcer fixes both.

        **Re-pressing within `EMERGENCY_REARM_S` does not re-send.** A
        field log shows three presses in a row producing three guardian
        notifications, three SMS attempts and three spoken confirmations
        talking over each other, all describing one event. Someone who has
        just pressed a panic button presses it again; that is what the
        button is for and it must not multiply the alert.

        What a suppressed press still does matters as much as what it
        stops:

        - **It cancels voice work.** An emergency press must always
          interrupt, and the user may have started a new command since the
          first press cleared the flag.
        - **It buzzes and vibrates, every time.** Not a token motor pulse:
          the full emergency pattern. The buzzer is deliberately loud
          because it is the only part of this device a *bystander* can
          perceive, so someone who needs attention now must be able to
          lean on the button and keep it sounding. Suppressing that to
          avoid "spam" would remove the one channel that reaches the
          people actually standing nearby.
        - **It says so, once per window.** Repeating "already sent" on
          every press would be worse than silence: it is spoken as
          critical, so each utterance preempts the last and the user hears
          a stutter of half-sentences.

        The feedback is spawned rather than played inline so a burst of
        presses neither delays the alert behind ~0.4 s of buzzing nor
        blocks gpiozero's callback thread. `_warning_lock` inside
        `_spawn_haptic` serialises the patterns, so held-down presses
        queue into continuous sound instead of overlapping into mush.
        """
        # Outside the re-arm check on purpose: see the docstring.
        self._voice_cancel_reason = "emergency"
        self._voice_cancel.set()

        # Before the re-arm check, so every press is felt and heard.
        self._spawn_haptic("emergency-ack", self._play_emergency_feedback)

        now = time.monotonic()
        since_last = now - self._last_emergency_fired
        if since_last < EMERGENCY_REARM_S:
            print(
                f"[EMERGENCY BUTTON] Pressed again {since_last:.0f}s after the "
                f"last alert — not re-sending.",
                flush=True,
            )
            # Once per window, and only into silence. Mid-announcement
            # this would be a *critical* utterance, which preempts — so it
            # would cut off the confirmation the user pressed again to
            # hear, and a run of presses would leave only fragments.
            if not self._already_sent_spoken and not is_playing():
                self._already_sent_spoken = True
                self._announce(
                    messages.get("emergency.already_sent", self.language.current),
                    critical=True,
                )
            return

        self._last_emergency_fired = now
        self._already_sent_spoken = False
        print("\n[EMERGENCY BUTTON] Pressed. Firing alert...", flush=True)

        try:
            response = self.executor.execute(
                IntentResult(intent=Intent.EMERGENCY_TRIGGER)
            )
            print(f"[EMERGENCY BUTTON] response: {response}", flush=True)
            self._announce(response, critical=True)
        except Exception as exc:
            print(f"[EMERGENCY BUTTON] handler error: {exc}", file=sys.stderr, flush=True)

    # Alerts whose delivery outcome the wearer is told about. Low battery
    # is deliberately absent even though it texts guardians: the wearer
    # already heard `battery.low_warning`, and following every one with a
    # delivery report would be noise on a non-urgent event. These two are
    # the ones where believing help is coming — and being wrong — is the
    # whole failure.
    _DELIVERY_REPORTED_EVENTS = frozenset({
        EventType.EMERGENCY_ALERT,
        EventType.FALL_DETECTION,
    })

    # (backend reached, SMS state) -> what to say. The both-succeeded case
    # is absent on purpose: it is the only outcome that needs no
    # correction, and `_on_alert_delivery` stays silent for it rather than
    # repeating a sentence the wearer heard moments ago.
    _DELIVERY_MESSAGES = {
        (True, SMS_FAILED):      "emergency.delivery.sms_failed",
        (True, SMS_NO_NUMBER):   "emergency.delivery.no_number",
        (False, SMS_SENT):       "emergency.delivery.backend_failed",
        (False, SMS_FAILED):     "emergency.delivery.all_failed",
        (False, SMS_NO_NUMBER):  "emergency.delivery.all_failed",
    }

    def _on_alert_delivery(
        self, event: AlertEvent, delivery: AlertDelivery,
    ) -> None:
        """Tell the wearer which channels actually carried an alert.

        Runs on the SMS fan-out thread, seconds after the alert was
        dispatched and after the wearable has already acknowledged it.
        Speaking goes through `_announce` like everything else, so this
        thread never touches the speaker itself.

        Critical, because it corrects something the wearer is currently
        acting on. Someone who believes a guardian has been told will wait
        where they are; someone who knows nobody was told will shout, or
        find a phone. Queueing that behind an obstacle warning would delay
        the one announcement with a time cost attached to it.

        Silent when everything worked. The acknowledgement already said
        the alert was going out, so the only thing left worth the
        interruption is news that it did not.
        """
        if event.event_type not in self._DELIVERY_REPORTED_EVENTS:
            return
        if delivery.backend_ok and delivery.sms == SMS_SENT:
            print("[alert] delivered on both channels.", flush=True)
            return

        if not delivery.backend_ok and delivery.sms != SMS_SENT:
            # Nobody was told. Re-arm the emergency button immediately so
            # pressing again retries instead of being swallowed as a
            # duplicate — the one situation where a user mashing it is
            # doing exactly the right thing, and the only one where the
            # debounce would otherwise work against them.
            self._last_emergency_fired = float("-inf")
            print("[alert] nobody reached — emergency button re-armed.",
                  file=sys.stderr, flush=True)

        key = self._DELIVERY_MESSAGES.get((delivery.backend_ok, delivery.sms))
        if key is None:
            # An `sms` state this map does not know. Reaching here means a
            # state was added to `sms_alerts.py` without a message, and
            # staying quiet about a failed emergency alert is the worst
            # possible response — say the most pessimistic thing instead.
            print(
                f"[alert] unmapped delivery state {delivery!r} — "
                f"reporting total failure.",
                file=sys.stderr, flush=True,
            )
            key = "emergency.delivery.all_failed"

        print(
            f"[alert] {event.event_type.value}: backend="
            f"{'ok' if delivery.backend_ok else 'FAILED'} sms={delivery.sms}",
            file=sys.stderr, flush=True,
        )
        self._announce(messages.get(key, self.language.current), critical=True)

    def _on_repeat_press(self) -> None:
        """Dual-purpose: stop talking if it is talking, otherwise repeat.

        The two meanings are companions — both are about the last thing the
        wearable said — so one button carries them without ambiguity. The
        prototype has three buttons and all were already assigned, so a
        dedicated stop button was never an option, but this reads better
        than one anyway: there is no state in which the user wants both.

        **Stop.** Until now nothing could interrupt speech. `vision.read`
        on a menu is thirty seconds of Piper the user had to wait out, and
        `sd.play` is blocking with no interrupt. A press now aborts
        playback and drops the queue.

        Stopping discards pending *critical* announcements too. The
        alternative — a warning resuming a moment after the user asked for
        silence — makes the button feel broken, and the guardian alert has
        already gone out by then regardless, so what is lost is a
        notification the user has chosen not to hear.

        **Repeat.** Unchanged: replays the executor's last response,
        whatever produced it. A response cut short by a stop press is still
        the last response, so pressing again replays the one just
        cancelled — which is what someone who stopped it for a passing
        jeepney would expect.

        **Stop means the whole exchange, not just the audio.** A press
        used to abort playback only, so a press during the three to seven
        seconds of transcription and classification did nothing at all —
        no sound, no haptic, and the answer still arrived afterwards
        whether or not it was still wanted. There was no way to take back
        a question except by triggering a real emergency alert to a
        guardian, which is not a cancel button. It now sets
        `_voice_cancel`, the same flag the emergency path uses, so every
        stage of the pipeline bails for the same reason it already bails
        for an emergency.

        **It always answers.** Interrupting is silent by design — silence
        is what was asked for — but silence is also exactly what a dead
        device produces, and the two were indistinguishable. A short stop
        cue says the press landed. It is a tone and not a sentence
        because the user just asked it to stop talking, and replying with
        more talking both contradicts the request and invites a second
        press to stop *that*.
        """
        speaking = is_playing()
        working = self._voice_active.is_set()

        if speaking:
            print("[REPEAT] Stopping playback.", flush=True)
            stop_playback()
            if self.announcer is not None:
                self.announcer.clear()

        if working:
            # Checked after `is_playing` and acted on independently: a
            # pipeline that is mid-playback is both, and "stop" has to
            # mean both or the response resumes from the next stage.
            print("[REPEAT] Cancelling the voice command in flight.", flush=True)
            self._voice_cancel_reason = "user"
            self._voice_cancel.set()

        if speaking or working:
            self._play_cue(play_stop_cue)
            return

        self._play_button_ack()
        try:
            response = self.executor.execute(
                IntentResult(intent=Intent.NAVIGATION_REPEAT)
            )
            print(f"[REPEAT] response: {response}", flush=True)
            self._announce(response)
        except Exception as exc:
            print(f"[REPEAT] handler error: {exc}", file=sys.stderr, flush=True)

    # ---------------------------------------------------------------- feedback

    def _play_button_ack(self) -> None:
        """All-motor pulse for a generic button-press acknowledgment.

        Blocking (~150 ms). Guarded by the same warning-lock as obstacle
        alerts so concurrent haptic events don't leave motors on.
        """
        with self._warning_lock:
            try:
                self._pulse_all_motors(duration_s=0.15)
            except Exception as exc:
                print(f"[feedback] motor-ack error: {exc}", file=sys.stderr, flush=True)

    @contextmanager
    def _waiting_cue(self):
        """Blip softly while the user waits, for the duration of the block.

        The gap between the stop chime and the answer is 3-7 s of silence
        on the Pi — Whisper, then a 1.7B model on a CPU — and from the
        user's side that is indistinguishable from a device that died.
        "Let me think about that" only ever covered the cloud path, and
        only *after* the local model had already spent its seconds.

        A context manager because the one thing that must never happen is
        the blip outliving the wait. The pipeline has several early
        returns inside this block (cancelled, empty transcript, emergency)
        and a `finally` is the only way all of them stop it.

        Separate blips rather than one sustained tone: `play` holds the
        audio lock for a whole utterance, so a continuous waiting sound
        would make the answer — and any obstacle warning — queue behind
        it. Each blip holds the lock for 45 ms and leaves it free the
        rest of the time.

        Skips a blip whenever speech is on the speaker, which is what
        keeps it out of the way of "let me think about that" and of an
        obstacle warning, without either of them needing to know it
        exists. `_waiting_paused` covers the one case that check cannot:
        the destination confirmation, which is *silent on purpose* while
        it waits for a button press.
        """
        stop = threading.Event()

        def _run() -> None:
            # A command answered faster than the delay never blips at all.
            if stop.wait(WAITING_CUE_DELAY_S):
                return
            while True:
                if not is_playing() and not self._waiting_paused.is_set():
                    try:
                        play_waiting_tick()
                    except Exception as exc:
                        # No audio stack, or the device went away. Stop
                        # rather than retry every interval for the rest of
                        # the wait — one log line, not twenty.
                        print(f"[waiting] cue stopped: {exc}",
                              file=sys.stderr, flush=True)
                        return
                if stop.wait(WAITING_CUE_INTERVAL_S):
                    return

        threading.Thread(target=_run, name="waiting-cue", daemon=True).start()
        try:
            yield
        finally:
            stop.set()

    def _cancel_reason(self) -> str:
        """Why the current voice cycle was abandoned, for the log.

        Falls back to "unknown" rather than asserting: this is read on the
        voice thread after observing `_voice_cancel`, and a reason that
        somehow never got written must not turn a clean abort into an
        exception inside the pipeline's own error handling.
        """
        return self._voice_cancel_reason or "unknown"

    def _play_cue(self, cue) -> None:
        """Play a short audio cue, never raising. ~200 ms.

        Audio only, no motors. The three vibration motors already carry
        two meanings — turn direction and obstacle proximity — and a third
        overlaid on the same hardware would be unreadable to someone
        decoding it by feel while walking.

        Deliberately not inside `_warning_lock`, unlike the press and
        emergency feedback: those hold it because they pulse motors, and
        taking it here would make a stop cue queue behind a warning
        pattern the user has just asked to interrupt. `play_cue` takes the
        audio layer's own lock, which is the only serialisation it needs.
        """
        try:
            cue()
        except Exception as exc:
            print(f"[feedback] cue error: {exc}", file=sys.stderr, flush=True)

    def _reclaim_ptt_button(self) -> None:
        """Point the PTT button back at `_on_ptt_press`. Never raises.

        Four things borrow that button and must hand it back:
        `record_until_button`, the destination confirmation, the
        turn-to-face orientation, and the pipeline's own `finally` as a
        backstop. Idempotent, so calling it twice costs nothing and the
        backstop stays safe.

        A missing button is not an error — the wearable runs without one
        in degraded setups — and a failure here must not propagate,
        because every caller is in a `finally` cleaning up after
        something else.
        """
        if self.ptt_button is None:
            return
        try:
            self.ptt_button.on("pressed", self._on_ptt_press)
        except Exception as exc:
            print(f"[PTT] could not reclaim the button: {exc}",
                  file=sys.stderr, flush=True)

    def _reclaim_repeat_button(self) -> None:
        """Point the repeat button back at `_on_repeat_press`. Never raises.

        Only the destination confirmation borrows this one, where it
        serves as "no". Same contract as `_reclaim_ptt_button`: idempotent,
        tolerant of a missing button, and silent on failure because the
        caller is a `finally` cleaning up after something else.

        Failing to hand this back would leave the user with no way to stop
        the wearable talking, which is the one control a person who cannot
        see the device most needs to keep.
        """
        if self.repeat_button is None:
            return
        try:
            self.repeat_button.on("pressed", self._on_repeat_press)
        except Exception as exc:
            print(f"[REPEAT] could not reclaim the button: {exc}",
                  file=sys.stderr, flush=True)

    def _play_press_feedback(self, rising_chime: bool) -> None:
        """PTT start/stop feedback: all-motor pulse + audio chime.

        `rising_chime=True` for recording start, `False` for stop. Runs
        the motor pulse and chime in sequence — motor first (brief and
        felt), then chime (heard) — total ~270 ms. This precedes
        recording so the chime isn't captured into the audio file.

        **The chime is outside `_warning_lock` and must stay outside it.**
        That lock serialises motor and buzzer patterns; every other block
        holding it touches nothing else. This was the one exception, and
        it coupled the haptics to the audio layer: `play_chime` waits on
        the audio lock, which the announcer holds for a whole utterance —
        thirty seconds on an OCR read. A press during one left this
        method holding `_warning_lock` the entire time, and with it:

          * gpiozero's callback thread, so PTT stopped responding
          * `_play_emergency_feedback`, so the emergency buzzer could not
            fire — the one output that has to work when nothing else does
          * every obstacle warning pattern

        Sequential either way, so the ordering the docstring promises is
        unchanged; only the lock's scope shrinks to what it is for.
        """
        with self._warning_lock:
            try:
                self._pulse_all_motors(duration_s=0.15)
            except Exception as exc:
                print(f"[feedback] motor-ack error: {exc}", file=sys.stderr, flush=True)

        try:
            play_chime(rising=rising_chime)
        except Exception as exc:
            print(f"[feedback] chime error: {exc}", file=sys.stderr, flush=True)

    def _play_emergency_feedback(self) -> None:
        """Emergency-press feedback: 3 fast buzzer beeps + all-motor pulse.

        The buzzer is used here (unlike PTT) because emergencies SHOULD
        be loud — a bystander who hears the buzzer will know something
        is happening even if the guardian hasn't answered the alert yet.
        """
        with self._warning_lock:
            # Fire motors + buzzer roughly simultaneously so the user
            # feels the acknowledgment while it's audible.
            try:
                self._pulse_all_motors(duration_s=0.2)
            except Exception as exc:
                print(f"[feedback] motor-ack error: {exc}", file=sys.stderr, flush=True)
            try:
                if self.buzzer is not None:
                    self.buzzer.beep(times=3, duration_s=0.1, gap_s=0.06)
            except Exception as exc:
                print(f"[feedback] buzzer error: {exc}", file=sys.stderr, flush=True)

    # ---------------------------------------------------------------- voice

    def _voice_pipeline(self) -> None:
        """The blocking part of PTT: record → STT → parse → execute → TTS → play.

        Runs on its own thread so the main fall-detection loop keeps
        ticking. Any emergency-button press during execution flips
        `_voice_cancel`; each pipeline stage checks it and bails.

        `record_until_button` internally overwrites the PTT button's
        press handler with its own "stop recording" handler. We restore
        our `_on_ptt_press` handler in the `finally` block so the next
        press starts a new cycle correctly.
        """
        # Per-stage wall clock, reported as one line in the `finally`.
        #
        # One line rather than a print per stage: the obstacle poller
        # writes to the same console several times a second, so six
        # scattered timings are unreadable in a journal, and a cycle that
        # returns early still reports what it spent before bailing.
        #
        # Recording is excluded — that is the user speaking, it is
        # already logged as "Captured N s", and including it would hide
        # the number that matters behind however long they talked. The
        # total is therefore the wait *after* the user stops: the thing
        # the waiting blip covers, and the thing to defend in the viva.
        stages: list[tuple[str, float]] = []

        try:
            timestamp = datetime.now().strftime("%B-%d-%Y_%H-%M-%S")
            input_path = VOICE_TEST_DIR / f"{timestamp}_command.wav"
            response_path = VOICE_TEST_DIR / f"{timestamp}_response.wav"

            print("[PTT] Recording (press PTT again to stop)...", flush=True)
            duration = record_until_button(
                self.ptt_button,
                input_path,
                cancel_event=self._voice_cancel,
                max_duration_s=PTT_MAX_RECORDING_S,
            )
            # Take the button back immediately, not in the `finally`.
            #
            # `record_until_button` replaces the handler with its own
            # "stop recording" closure, and that closure is dead the
            # moment it returns. Restoring only at the end left the
            # button pointing at it for the whole 3-7 s of transcription
            # and classification — the one press in the system that
            # produced no sound, no log and no effect whatsoever, during
            # the exact wait that makes a user press something.
            #
            # Safe here rather than later: the press that ended the
            # recording has already been consumed, gpiozero debounces at
            # 50 ms, and `_voice_active` is still set, so a further press
            # now reaches `_on_ptt_press` and is answered with the busy
            # cue. The `finally` keeps its own call as the backstop for
            # the paths that never reach this line.
            self._reclaim_ptt_button()
            print(f"[PTT] Captured {duration:.1f} s of audio.", flush=True)

            if self._voice_cancel.is_set():
                # Whichever button fired has already made its own sound —
                # the emergency pattern, or the stop cue — so the PTT stop
                # feedback is skipped to avoid two cues contending for the
                # one output device.
                print(
                    f"[PTT] Recording cancelled ({self._cancel_reason()}) "
                    f"— skipping.",
                    flush=True,
                )
                return
            if duration <= 0.2:
                # Too brief to hold speech — a double-press, or a bounce.
                # Say so: the user has had their press chime and would
                # otherwise get nothing back at all.
                print("[PTT] Too short — nothing to transcribe.", flush=True)
                self._speak_prerendered("not_heard")
                return

            # If the recording hit the max-duration cap, the user
            # probably forgot to press PTT to stop. Log it so the
            # behaviour is visible; downstream pipeline runs normally.
            if duration >= PTT_MAX_RECORDING_S - 0.5:
                print(
                    f"[PTT] Recording auto-stopped at {PTT_MAX_RECORDING_S:.0f}s cap "
                    f"(user did not press PTT to end).",
                    flush=True,
                )

            # Recording ended cleanly (second PTT press or timeout).
            # Play the falling stop-chime + motor pulse to signal "I
            # got your command, processing now."
            self._play_press_feedback(rising_chime=False)

            # Everything from here to the answer is silent work the user
            # cannot see: transcription, classification, whatever the
            # executor has to fetch, and finally synthesis. The blip is
            # what distinguishes that from a device that has died.
            with self._waiting_cue():
                _t0 = time.monotonic()
                transcript = self.stt.transcribe(
                    input_path,
                    language=self.language.current,
                    initial_prompt=(
                        WHISPER_INITIAL_PROMPTS.get(self.language.current) or None
                    ),
                )
                stages.append(("stt", time.monotonic() - _t0))
                print(f"[PTT] Transcript: {transcript.text!r}", flush=True)
                # Split from the empty-transcript case below: a cancelled
                # cycle has already been answered by the stop cue, and
                # following that with "I didn't hear anything" would
                # contradict a user who knows perfectly well why it
                # stopped — they stopped it.
                if self._voice_cancel.is_set():
                    return
                if not transcript.text.strip():
                    # Whisper heard noise, or nothing. Either way the user
                    # spoke and got silence back, which is the shape of a
                    # device that has died.
                    print("[PTT] Empty transcript — nothing to classify.", flush=True)
                    self._speak_prerendered("not_heard")
                    return

                _t0 = time.monotonic()
                intent_result = self.parser.parse(transcript.text)
                stages.append((f"nlu:{intent_result.source}", time.monotonic() - _t0))
                print(
                    f"[PTT] Intent: {describe(intent_result)} "
                    f"params={intent_result.parameters}",
                    flush=True,
                )

                # A cloud answer takes seconds on top of everything above.
                # The blip says the device is alive; this says an answer is
                # coming and roughly why it is slow, which a tone cannot.
                #
                # `failure is None` mirrors the executor's own gate: a parse
                # failure never reaches the cloud, so promising a wait that is
                # not coming would have the wearable say "let me think" and
                # then immediately "I didn't catch that".
                # Checked here and not only after the cue: classification
                # is the longest uninterruptible stage in the pipeline
                # (~5 s for the LLM path), so a press at the start of it
                # was observed by the check below only *after* the device
                # had already said "let me think about that" — speech from
                # a cycle the user had cancelled, which then needed a
                # second press to stop. Cancelling has to mean silence
                # from the moment it is noticed, not one sentence later.
                if self._voice_cancel.is_set():
                    return

                if (
                    intent_result.intent is Intent.UNKNOWN
                    and intent_result.failure is None
                    and self.cloud is not None
                ):
                    self._speak_thinking()
                    if self._voice_cancel.is_set():
                        return

                _t0 = time.monotonic()
                response = self.executor.execute(intent_result)
                stages.append(("exec", time.monotonic() - _t0))
                print(f"[PTT] Response: {response}", flush=True)
                if self._voice_cancel.is_set():
                    return

                _t0 = time.monotonic()
                self.tts.synthesize(
                    response, response_path, language=self.language.current,
                )
                stages.append(("tts", time.monotonic() - _t0))
            if self._voice_cancel.is_set():
                return
            _t0 = time.monotonic()
            play(response_path)
            stages.append(("play", time.monotonic() - _t0))

            # The goodbye has now been heard, so it is safe to cut power.
            # Before `play()` would truncate it mid-word; from the user's
            # side that is indistinguishable from the device crashing.
            if self._shutdown_requested:
                self._perform_shutdown()
                return

            # Navigation just started: point the user the right way before
            # they take a step. Deliberately after the response has been
            # heard, so "Navigating to Jollibee, four hundred metres" lands
            # first and the buzzing that follows has a context.
            #
            # Here rather than inside the executor because orienting needs
            # the compass, the motors and the speaker — all app-level — and
            # the route is already reachable through `nav_monitor`.
            if (intent_result.intent is Intent.NAVIGATION_START
                    and self.nav_monitor.is_active()):
                self._orient_towards_route()
        except Exception as exc:
            print(f"[PTT] voice pipeline error: {exc}", file=sys.stderr, flush=True)
            # Speak a short error so the user isn't left wondering why
            # nothing happened. Wrapped in its own try/except so a
            # broken TTS doesn't cascade into an infinite error loop.
            self._speak_error("Something went wrong. Please try again.")
        finally:
            if stages:
                spent = " | ".join(f"{name} {secs:.1f}s" for name, secs in stages)
                # `wait` excludes playback deliberately. Playback is the
                # user being served, not kept waiting, and folding it in
                # made a short answer to a slow question look identical
                # to a fast answer that happens to be long — two
                # different problems with two different fixes. `wait` is
                # the silence the blip covers; `play` is how much the
                # device talks, which is a message-length question.
                wait = sum(secs for name, secs in stages if name != "play")
                print(
                    f"[PTT] timing: {spent} | wait {wait:.1f}s",
                    flush=True,
                )
            # Backstop: every path that reached the recorder has already
            # reclaimed the button, but the ones that failed before it
            # have not.
            self._reclaim_ptt_button()
            self._voice_active.clear()

    def _orient_towards_route(self) -> None:
        """Turn the user to face the start of the route before they walk.

        GraphHopper opens with "Head north on Rizal Street", which a user
        who cannot see has no way to act on — and every cue after it
        assumes they set off roughly correctly. This is what makes that
        assumption true.

        Runs on the voice thread, right after `nav.started` is spoken, so
        the 100 Hz loop keeps detecting falls and obstacles while the user
        stands in the street turning around.

        The turning itself is silent: a motor pulses on the side to turn
        toward, faster as they come round. Only the finish is spoken. See
        `navigation/orientation.py` for why rate-coded haptics rather than
        a spoken angle.

        Returns without doing anything when the compass cannot be trusted,
        which is every run until `config.COMPASS_CALIBRATED` is set — so
        this is inert today and the wearable behaves exactly as it did.

        Four ways out, and none of them leave the user stuck:
          - aligned: front pulse + "walk straight ahead"
          - `ORIENTATION_TIMEOUT_S` elapsed: "start walking, I'll guide you"
          - PTT pressed: the user already knows the way
          - emergency: abandon everything
        """
        # A press means "I know which way I'm going" — borrow the button
        # for the duration and hand it back, as the confirmation does.
        skipped = threading.Event()

        try:
            # Everything from here is inside the guard, including the
            # preconditions: a compass that raises on the very first read
            # must cost the user their orientation cue, not surface as
            # "something went wrong" over the route they just asked for.
            if self.trusted_heading() is None:
                return
            route = self.nav_monitor.route()
            if route is None or not route.points:
                return

            fix = self.gps_cache.latest_fix() if self.gps_cache is not None else None
            if fix is None:
                return
            origin = Coordinate(lat=fix.lat, lon=fix.lon)

            target = first_meaningful_point(
                route.points, origin, ORIENTATION_MIN_TARGET_DISTANCE_M,
            )
            if target is None:
                return
            bearing = bearing_to(origin, target)

            guide = OrientationGuide(
                aligned_tolerance_deg=ORIENTATION_ALIGNED_TOLERANCE_DEG,
                release_tolerance_deg=ORIENTATION_RELEASE_TOLERANCE_DEG,
                bands=ORIENTATION_BANDS,
            )

            if self.ptt_button is not None:
                self.ptt_button.on("pressed", skipped.set)

            print(f"[orient] bearing to route start: {bearing:.0f}°", flush=True)
            deadline = time.monotonic() + ORIENTATION_TIMEOUT_S
            while time.monotonic() < deadline:
                if self._voice_cancel.is_set() or skipped.is_set():
                    return

                heading = self.trusted_heading()
                if heading is None:
                    # The compass dropped out mid-turn. Better to let them
                    # walk than to buzz at them with nothing behind it.
                    break

                cue = guide.cue(heading, bearing)
                if cue.aligned:
                    print(f"[orient] aligned at {heading:.0f}°", flush=True)
                    self._spawn_haptic(
                        "orient-aligned",
                        lambda: self._pulse_all_motors(duration_s=0.3),
                    )
                    self._announce(
                        messages.get(
                            "nav.walk_straight_ahead", self.language.current,
                        )
                    )
                    return

                motor = self._motor_for_direction(cue.direction)
                if motor is not None:
                    motor.pulse(times=1, duration_s=0.08)
                # Sleeping on the cancel event rather than `time.sleep` so
                # an emergency press is felt within the pulse gap rather
                # than after it.
                self._voice_cancel.wait(timeout=cue.pulse_interval_s)

            print("[orient] gave up — letting them walk.", flush=True)
            self._announce(
                messages.get("nav.orientation_gave_up", self.language.current)
            )
        except Exception as exc:
            # This is guidance, not safety. A compass or motor failure here
            # must not cost the user the route they just asked for.
            print(f"[orient] error: {exc}", file=sys.stderr, flush=True)
        finally:
            self._reclaim_ptt_button()

    def _confirm_destination(self, question: str) -> bool:
        """Speak `question`, then wait for a PTT press meaning "yes".

        Given to the `IntentExecutor` as its `confirmer`, so it runs on the
        voice thread inside `navigation.start` — between choosing a
        destination and asking the router for a path.

        **Right confirms, left declines, silence still declines.** This
        used to say that all three buttons were spoken for and a timeout
        was therefore the only way to decline. That was wrong about the
        repeat button: during a confirmation it has nothing to do, because
        its everyday job — stop talking, abandon the command — is what
        "no" means here. Leaving the decline to a timeout cost a user in
        the field the full `DESTINATION_CONFIRM_TIMEOUT_S` of standing
        still to reject a destination they had already heard was wrong.

        The timeout stays as the backstop, and still fails in the right
        direction: the two ways this can go wrong — the user did not hear
        the question, or is not holding the device — should both end in
        not walking anywhere.

        Both handlers are swapped for the duration and restored afterwards,
        the same borrow-and-return `record_until_button` performs. The press
        that ends recording cannot leak into this window: several seconds of
        speech separate them.

        Returns False if an emergency press lands mid-question. The
        emergency path is already speaking and alerting by then, and
        starting turn-by-turn navigation on top of it would be absurd.
        """
        if self.ptt_button is None:
            # No button means no way to ask. Reachable only in degraded
            # setups — a PTT press is what starts a voice command in the
            # first place, so in practice this button exists whenever this
            # code runs. Proceed rather than making navigation impossible.
            print("[nav] no PTT button — skipping confirmation.", flush=True)
            return True

        # The silence after the question is the user's turn, not a wait
        # for the device — blipping through it would read as the wearable
        # talking over its own question. `is_playing()` cannot see this
        # because, by design, nothing is playing.
        self._waiting_paused.set()

        self._speak_error(question)   # reuse the best-effort speak helper
        if self._voice_cancel.is_set():
            self._waiting_paused.clear()
            return False

        confirmed = threading.Event()
        declined = threading.Event()
        try:
            self.ptt_button.on("pressed", confirmed.set)
            # Borrowed the same way, and for the same window. The repeat
            # button is idle here: its everyday job is to stop speech and
            # abandon the running command, which is exactly what "no"
            # means at a confirmation prompt, so there is nothing for it
            # to do that this displaces.
            #
            # A local event rather than letting its normal handler set
            # `_voice_cancel`. Declining already worked that way by
            # accident — and because the pipeline treats that flag as
            # "abandon this cycle", the "please say where you want to go"
            # that follows was swallowed. Waiting out the timeout got the
            # user a spoken reply; pressing the button got them silence,
            # which is the wrong way round.
            if self.repeat_button is not None:
                self.repeat_button.on("pressed", declined.set)

            deadline = time.monotonic() + DESTINATION_CONFIRM_TIMEOUT_S
            while time.monotonic() < deadline:
                if confirmed.wait(timeout=0.05):
                    break
                if declined.is_set():
                    break
                if self._voice_cancel.is_set():
                    return False
        finally:
            self._waiting_paused.clear()
            # Hand both buttons back even if speaking or waiting blew up,
            # or the next press would land on a dead handler.
            self._reclaim_ptt_button()
            self._reclaim_repeat_button()

        if confirmed.is_set():
            print("[nav] destination confirmed.", flush=True)
            return True
        if declined.is_set():
            print("[nav] declined by button.", flush=True)
            return False
        print("[nav] confirmation timed out — cancelling.", flush=True)
        return False

    def _prerendered_path(self, name: str, language: str) -> Path:
        """Where the pre-rendered clip `name` for `language` lives.

        The message text is hashed into the filename, so editing it in
        `messages.py` points this at a file that does not exist yet and
        the stale recording is simply never played again. Without that,
        the wearable would keep speaking a sentence that is no longer
        anywhere in the source — the kind of drift that costs an
        afternoon to find.
        """
        text = messages.get(_PRERENDERED[name], language)
        digest = hashlib.sha256(text.encode()).hexdigest()[:8]
        return STARTUP_AUDIO_DIR / f"{name}_{language}_{digest}.wav"

    def _play_startup_notice(self) -> None:
        """Play the pre-rendered startup message. Never raises.

        Runs as the first thing in `start()`, before any model is loaded —
        which is the whole point, and also the constraint: TTS is not
        available yet, so this can only replay something rendered on a
        previous boot. The very first boot after installation (or after
        the message text changes) is therefore silent here, and
        `_render_prerendered` fixes that for every boot after.

        Playback is blocking, and deliberately so: it is a few seconds at
        the head of a 2-3 minute startup, and letting model loading talk
        over the greeting would defeat it.
        """
        path = self._prerendered_path("startup", self.language.current)
        if not path.exists():
            print(
                f"  (no startup clip yet at {path.name} — it will be "
                f"rendered at the end of this boot)",
                flush=True,
            )
            return
        try:
            play(path)
        except Exception as exc:
            print(f"[startup] could not play notice: {exc}", file=sys.stderr, flush=True)

    def _render_prerendered(self) -> None:
        """Render every pre-rendered clip in every language. Never raises.

        Every language, not just the active one, because the user can
        switch with a voice command: the next boot must greet them in
        whatever they chose, by which point TTS is again unavailable, and
        a cloud question asked in Tagalog must not pay for synthesis the
        English boot already did.

        Stale clips for the same name and language are removed, so an
        edited message leaves one file rather than a growing pile of
        recordings of sentences nobody says any more.
        """
        for name in _PRERENDERED:
            for language in self.language.supported:
                path = self._prerendered_path(name, language)
                if path.exists():
                    continue
                try:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    self.tts.synthesize(
                        messages.get(_PRERENDERED[name], language),
                        path,
                        language=language,
                    )
                    for stale in path.parent.glob(f"{name}_{language}_*.wav"):
                        if stale != path:
                            stale.unlink()
                    print(f"  Rendered '{name}' clip for '{language}'.", flush=True)
                except Exception as exc:
                    print(
                        f"[prerender] could not render '{name}' for "
                        f"'{language}': {exc}",
                        file=sys.stderr, flush=True,
                    )

    def _request_shutdown(self) -> None:
        """Arm the power-off. Called by the executor after the user confirms.

        Only sets a flag. The goodbye still has to be synthesised and
        played by `_voice_pipeline`, and cutting power before it finishes
        would leave the user unsure the device heard them at all.
        """
        print("[shutdown] confirmed — powering off after the goodbye.", flush=True)
        self._shutdown_requested = True

    def _perform_shutdown(self) -> None:
        """Actually power the machine off. Never raises.

        Split from `_request_shutdown` so the goodbye is spoken first, and
        kept out of the executor because the executor must stay free of
        anything that touches this host.

        Needs one sudoers line (see `config.SHUTDOWN_COMMAND`). A failure
        is spoken rather than swallowed: a user who asked to turn the
        device off and heard "goodbye" would otherwise walk away believing
        a still-running wearable was off, and find it flat later.
        """
        print(f"[shutdown] running {' '.join(SHUTDOWN_COMMAND)}", flush=True)
        try:
            completed = subprocess.run(
                SHUTDOWN_COMMAND, capture_output=True, text=True, timeout=10,
            )
            if completed.returncode == 0:
                return
            detail = (completed.stderr or completed.stdout or "").strip()[:200]
            print(
                f"[shutdown] failed (exit {completed.returncode}): {detail}",
                file=sys.stderr, flush=True,
            )
        except Exception as exc:
            print(f"[shutdown] failed: {exc}", file=sys.stderr, flush=True)

        self._shutdown_requested = False
        self._announce(messages.get("shutdown.failed", self.language.current),
                       critical=True)

    def _speak_greeting(self) -> None:
        """Announce readiness in the active language. Never raises.

        This is how a user who cannot see a screen learns which language
        the wearable came up in — hearing Tagalog tells them the switch
        command must be spoken in Tagalog. Best-effort: a device that
        boots without working audio must still boot.
        """
        try:
            timestamp = datetime.now().strftime("%B-%d-%Y_%H-%M-%S")
            greeting_path = VOICE_TEST_DIR / f"{timestamp}_greeting.wav"
            self.tts.synthesize(
                messages.get("language.greeting", self.language.current),
                greeting_path,
                language=self.language.current,
            )
            play(greeting_path)
        except Exception as exc:
            print(f"[greeting] could not speak: {exc}", file=sys.stderr, flush=True)

    def _speak_thinking(self) -> None:
        """Tell the user we're working before a slow cloud call. Never raises.

        Deliberately spoken rather than a tone: "let me think about that"
        conveys both that the wearable heard them and that an answer is
        coming, which a beep does not. It plays synchronously on the voice
        thread — that costs a second, but overlapping it with the answer
        would mean two voices talking at once.

        Pre-rendered at startup. It used to be synthesised on every cloud
        question, which put ~1 s of TTS in front of the slowest path the
        device has — adding to the exact wait this sentence exists to
        excuse.
        """
        self._speak_prerendered("thinking")

    def _speak_prerendered(self, name: str) -> None:
        """Play a pre-rendered clip in the active language. Never raises.

        Falls back to live synthesis when the file is missing, which is
        the first boot after that message's text changes. Slower, but a
        sentence arriving late beats a sentence that never arrives — every
        caller here is covering a silence the user would otherwise read as
        a dead device.
        """
        language = self.language.current
        try:
            path = self._prerendered_path(name, language)
            if not path.exists():
                print(
                    f"[{name}] no pre-rendered clip at {path.name} — "
                    f"synthesising.",
                    file=sys.stderr, flush=True,
                )
                timestamp = datetime.now().strftime("%B-%d-%Y_%H-%M-%S")
                path = VOICE_TEST_DIR / f"{timestamp}_{name}.wav"
                self.tts.synthesize(
                    messages.get(_PRERENDERED[name], language),
                    path,
                    language=language,
                )
            play(path)
        except Exception as exc:
            print(f"[{name}] could not speak: {exc}", file=sys.stderr, flush=True)

    def _speak_error(self, message: str) -> None:
        """Best-effort audible error message. Never raises."""
        try:
            timestamp = datetime.now().strftime("%B-%d-%Y_%H-%M-%S")
            error_path = VOICE_TEST_DIR / f"{timestamp}_error.wav"
            self.tts.synthesize(message, error_path, language=self.language.current)
            play(error_path)
        except Exception as exc:
            print(f"[error-speech] failed to speak: {exc}", file=sys.stderr, flush=True)

    # ------------------------------------------------------- device factories
    #
    # Every device the runtime talks to is constructed in one of the
    # methods below and nowhere else. This is what makes `MockApp` in
    # `app_mock.py` possible: it subclasses `App` and overrides only
    # these, inheriting the loop, the threads and all the decision logic
    # unchanged. Keep `start()` free of direct driver constructor calls
    # or the mock runtime silently stops covering that device.
    #
    # Two naming conventions, and the difference is deliberate:
    #   `_open_*`     — the runtime cannot do its job without this. A
    #                   failure propagates and aborts startup.
    #   `_try_open_*` — degraded operation is acceptable. Logs and
    #                   returns None; callers already handle None.

    def _open_imu(self) -> MPU6050:
        """Open the IMU. Fatal on failure — no IMU means no fall detection,
        which is a safety guarantee we will not start up pretending to have."""
        return MPU6050(bus_number=MPU6050_I2C_BUS, address=MPU6050_ADDRESS)

    def _try_open_gps(self) -> SIM7600GPS | None:
        try:
            return SIM7600GPS(port=SIM7600_GPS_PORT)
        except Exception as exc:
            print(
                f"  GPS unavailable ({exc}). Location intents will be limited.",
                flush=True,
            )
            return None

    def _open_stt(self) -> FasterWhisperSTT:
        return FasterWhisperSTT(models=WHISPER_MODELS, model_dir=WHISPER_MODEL_DIR)

    def _open_tts(self) -> MultiEngineTTS:
        """English through Piper, Tagalog through MMS, behind one interface.

        Both are loaded up front rather than on first use. Loading either
        takes seconds, and the first thing that speaks is the startup
        greeting — a lazy load would put that cost in front of the user
        every time they switched language instead.
        """
        return build_tts(piper_voices=PIPER_VOICES, mms_voices=MMS_VOICES)

    def _open_parser(self) -> TieredIntentParser:
        """The intent parser: semantic fast path in front of the LLM.

        `_open_*` rather than `_try_open_*` because the LLM stage is not
        optional — a wearable that cannot classify speech has no voice
        interface at all. The *fast path* is optional, and that is
        handled one level down by `_try_open_embedding_matcher`.
        """
        return TieredIntentParser(
            matcher=self._try_open_embedding_matcher(),
            llm=OllamaIntentParser(
                model=NLU_MODEL,
                ollama_url=OLLAMA_URL,
                prompt_path=NLU_PROMPT_PATH,
                timeout_s=NLU_TIMEOUT_S,
                warmup=True,
                warmup_timeout_s=NLU_WARMUP_TIMEOUT_S,
            ),
        )

    def _try_open_embedding_matcher(self) -> EmbeddingMatcher | None:
        """Semantic fast path, or None to send every utterance to the LLM.

        `_try_open_*` because failing to load it degrades the device to
        exactly the behaviour it had before this layer existed: slower,
        fully correct. Aborting startup over a missing model file would
        trade a working device for a dead one.

        Constructed here rather than lazily on first use. The bank is
        encoded at build time, and that cost belongs in startup next to
        the Ollama warmup rather than in front of the user's first
        command — which is the cost this whole layer exists to remove.
        """
        return build_matcher(
            model_name=NLU_EMBEDDING_MODEL,
            bank_path=NLU_EMBEDDING_BANK_PATH,
            score_threshold=NLU_EMBEDDING_SCORE_THRESHOLD,
            margin_threshold=NLU_EMBEDDING_MARGIN_THRESHOLD,
        )

    def _open_volume(self) -> VolumeState:
        """Speaker volume, restored from disk and pushed to the sink.

        Not `_try_open_*`: it cannot fail in a way worth aborting for.
        Every OS call inside is best effort, so a Pi without `wpctl`
        simply runs at the system default and still talks.
        """
        return VolumeState(
            default_percent=VOLUME_DEFAULT_PERCENT,
            minimum_percent=VOLUME_MIN_PERCENT,
            maximum_percent=VOLUME_MAX_PERCENT,
            step_percent=VOLUME_STEP_PERCENT,
            state_path=VOLUME_STATE_PATH,
        )

    def _open_saved_places(self) -> SavedPlaces:
        """Load the user's own places. Not a device, so not `_try_open_*`.

        Cannot fail in a way worth aborting for: a missing file is the
        normal first-boot case and an unreadable one degrades to an empty
        list, both handled inside `SavedPlaces`.
        """
        return SavedPlaces(SAVED_PLACES_PATH)

    def _open_router(self) -> GraphHopperRouter:
        return GraphHopperRouter(base_url=GRAPHHOPPER_URL)

    def _open_geocoder(self) -> PhotonGeocoder:
        return PhotonGeocoder(base_url=PHOTON_URL)

    def _try_open_cloud_answerer(self):
        """Open the cloud LLM fallback, or None when it isn't configured.

        Returns None whenever `CLOUD_LLM_ENABLED` is False or no key is
        present in the environment, and the wearable then answers unknown
        utterances exactly as it did before — a missing key must degrade,
        never abort startup.

        The provider is `MistralAnswerer`. `OfflineGuard` wraps it here
        rather than living inside the driver, so the offline path is
        identical whichever provider is in use — `intents/cloud.py`
        documents the contract a replacement would have to meet.

        In practice the thing that decides whether this is live is the
        API key: with `CLOUD_LLM_ENABLED` already True, an empty
        `INDEPENSENSE_CLOUD_API_KEY` is the only reason the wearable
        answers "I didn't catch that" instead of forwarding the question.
        See `.env.example`.
        """
        if not CLOUD_LLM_ENABLED:
            return None

        api_key = os.environ.get(CLOUD_LLM_API_KEY_ENV)
        if not api_key:
            print(
                f"  Cloud LLM enabled but {CLOUD_LLM_API_KEY_ENV} is not set. "
                f"Unknown commands will not be forwarded.",
                flush=True,
            )
            return None

        try:
            answerer = MistralAnswerer(
                api_key=api_key,
                model=CLOUD_LLM_MODEL,
                url=CLOUD_LLM_URL,
                timeout_s=CLOUD_LLM_TIMEOUT_S,
                max_tokens=CLOUD_LLM_MAX_TOKENS,
            )
        except Exception as exc:
            print(f"  Cloud LLM unavailable ({exc}).", flush=True)
            return None

        print(f"  Cloud LLM ready ({CLOUD_LLM_MODEL}).", flush=True)
        # The guard wraps every provider rather than living inside one, so
        # the offline path is identical whichever driver is in use.
        return OfflineGuard(
            answerer,
            probe_url=CLOUD_LLM_PROBE_URL,
            probe_timeout_s=REACHABILITY_PROBE_TIMEOUT_S,
        )

    def _try_open_sms(self) -> MMCLISMSSender | None:
        """Open the SMS sender. Tolerant: the device still works without
        it, HTTP alerts still reach the backend, and refusing to boot
        because SMS is unavailable would be a worse outcome than losing
        the redundant notification path."""
        try:
            return MMCLISMSSender(
                modem_index=SMS_MODEM_INDEX,
                timeout_s=SMS_SEND_TIMEOUT_S,
            )
        except Exception as exc:
            print(
                f"  SMS unavailable ({exc}). Guardians will only be "
                f"notified over the data connection.",
                flush=True,
            )
            return None

    def _load_credential(self):
        """Read the per-device credential, or None if this unit has none.

        Not fatal. An unprovisioned unit still does everything that does
        not involve the dashboard: fall detection, obstacle warnings,
        navigation, voice, and — importantly — emergency SMS, which is the
        channel that works when data does not.
        """
        return load_device_credential(DEVICE_KEY_PATH)

    def _open_telemetry_client(self):
        """The raw backend client, or a discarding one when unprovisioned.

        `start()` wraps whatever this returns in a
        `BufferedTelemetryClient`, so buffering and retry behaviour is
        exercised identically in every mode.

        Returns `NullTelemetryClient` rather than raising when there is no
        credential: `NestJSTelemetryClient` requires one, and building a
        client whose every request is a guaranteed 401 would fill the
        retry queue with sends that can never succeed.
        """
        if self.credential is None:
            print(
                "  No device credential — backend telemetry disabled. "
                "SMS alerts still work.",
                flush=True,
            )
            return NullTelemetryClient()
        return NestJSTelemetryClient(
            base_url=BACKEND_URL,
            credential=self.credential,
            timeout_s=TELEMETRY_TIMEOUT_S,
        )

    def device_id(self) -> str:
        """This unit's UUID, from the credential.

        `"unprovisioned"` when there is none. Only used locally — in logs
        and in the `AlertEvent`/`IntervalInformation` dataclasses — since
        the wire format no longer carries a device id at all.
        """
        if self.credential is None:
            return "unprovisioned"
        return self.credential.device_id

    # ---------------------------------------------------------------- helpers

    def _try_open_button(self, gpio_pin: int, label: str) -> GPIOButton | None:
        try:
            return GPIOButton(gpio_pin=gpio_pin)
        except Exception as exc:
            print(
                f"  {label} button unavailable ({exc}). Continuing without it.",
                flush=True,
            )
            return None

    def _try_open_buzzer(self) -> GPIOBuzzer | None:
        try:
            return GPIOBuzzer(gpio_pin=BUZZER_GPIO)
        except Exception as exc:
            print(f"  Buzzer unavailable ({exc}).", flush=True)
            return None

    def _try_open_motor(self, gpio_pin: int, label: str) -> GPIOVibrationMotor | None:
        try:
            return GPIOVibrationMotor(gpio_pin=gpio_pin)
        except Exception as exc:
            print(f"  {label} motor unavailable ({exc}).", flush=True)
            return None

    def _try_open_ultrasonic(self, port: str, label: str) -> DYPA22 | None:
        try:
            return DYPA22(port, baudrate=DYP_A22_BAUDRATE)
        except Exception as exc:
            print(f"  {label} ultrasonic unavailable ({exc}).", flush=True)
            return None

    def _try_open_battery(self) -> WaveshareUPSHatE | None:
        try:
            return WaveshareUPSHatE(
                bus_number=UPS_HAT_I2C_BUS,
                empty_raw_percent=BATTERY_EMPTY_RAW_PERCENT,
            )
        except Exception as exc:
            print(
                f"  UPS HAT unavailable ({exc}). Heartbeats will report 100%.",
                flush=True,
            )
            return None

    def _try_open_magnetometer(self) -> QMC5883P | None:
        try:
            return QMC5883P(
                bus_number=MAG_I2C_BUS,
                address=MAG_ADDRESS,
                offset_x=MAG_OFFSET_X,
                offset_y=MAG_OFFSET_Y,
                offset_z=MAG_OFFSET_Z,
                scale_x=MAG_SCALE_X,
                scale_y=MAG_SCALE_Y,
                scale_z=MAG_SCALE_Z,
                forward_axis=MAG_FORWARD_AXIS,
                left_axis=MAG_LEFT_AXIS,
                heading_offset_deg=MAG_HEADING_OFFSET_DEG,
            )
        except Exception as exc:
            print(
                f"  Magnetometer unavailable ({exc}). Heading verification "
                f"will not be active.",
                flush=True,
            )
            return None

    def _try_open_camera(self) -> PiCamera | None:
        try:
            return PiCamera(width=CAMERA_WIDTH, height=CAMERA_HEIGHT, fps=CAMERA_FPS)
        except Exception as exc:
            print(
                f"  Camera unavailable ({exc}). vision.describe will report unavailable.",
                flush=True,
            )
            return None

    def _try_open_detector(self) -> YOLOv8Detector | None:
        try:
            return YOLOv8Detector(
                model_path=YOLO_MODEL_PATH,
                confidence_threshold=YOLO_CONFIDENCE_THRESHOLD,
            )
        except Exception as exc:
            print(
                f"  YOLO detector unavailable ({exc}). "
                f"vision.describe will report unavailable.",
                flush=True,
            )
            return None

    def _try_open_ocr(self) -> TesseractOCR | None:
        try:
            return TesseractOCR(language_map=OCR_LANGUAGES)
        except Exception as exc:
            print(
                f"  Tesseract OCR unavailable ({exc}). "
                f"vision.read will report unavailable.",
                flush=True,
            )
            return None


def run_app(app: App) -> None:
    """Install signal handlers, start the runtime, and block in the loop.

    Takes the app as an argument so `app_mock.py` can run a `MockApp`
    through the exact same startup and shutdown path as production.
    """
    VOICE_TEST_DIR.mkdir(parents=True, exist_ok=True)

    def _signal_handler(signum, _frame):
        print(f"\nReceived signal {signum}. Shutting down...", flush=True)
        app._shutdown.set()

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    # `kill -USR1 <pid>` dumps every thread's stack to stderr, which under
    # systemd lands in the journal alongside the rest of the device's
    # output.
    #
    # This exists because the failure it diagnoses is invisible by
    # construction. A thread wedged in a socket read prints nothing, logs
    # nothing and raises nothing — the device simply stops answering its
    # buttons, because `_voice_active` is cleared in a `finally` that a
    # blocked thread never reaches. No amount of added logging finds that;
    # only a stack does, and the device is headless with no debugger
    # attached.
    #
    # SIGUSR1 rather than SIGQUIT: SIGQUIT's default action kills the
    # process and dumps core, so a mistyped signal on a wearable someone
    # is relying on would take it down. SIGUSR1 has no default action at
    # all, which is what makes it safe to send to a device in the field.
    faulthandler.register(signal.SIGUSR1, all_threads=True, chain=False)

    try:
        app.start()
        app.run()
    except Exception as exc:
        print(f"Fatal error: {exc}", file=sys.stderr, flush=True)
        sys.exit(1)


def main() -> None:
    run_app(App())


if __name__ == "__main__":
    main()
