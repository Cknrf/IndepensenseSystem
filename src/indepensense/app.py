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
  - Emergency button callback: sets cancel flag AND runs the emergency
    handler directly. This preempts voice AND fires the alert without
    waiting for the voice thread to finish.
  - Repeat button callback: replays the last navigation instruction.
  - Warning-pattern threads (per obstacle event): play a vibration +
    buzzer pattern under a mutex so overlapping patterns don't race.
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

Two thresholds: 100 cm (warning) and 50 cm (danger). 2 s cooldown per
(sensor, tier) so a lingering obstacle doesn't spam.

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
import os
import signal
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from indepensense.config import (
    BACKEND_URL,
    BATTERY_CHECK_INTERVAL_S,
    BUZZER_GPIO,
    CAMERA_FPS,
    CAMERA_HEIGHT,
    CAMERA_WIDTH,
    CLOUD_LLM_API_KEY_ENV,
    CLOUD_LLM_ENABLED,
    CLOUD_LLM_MAX_TOKENS,
    CLOUD_LLM_MODEL,
    CLOUD_LLM_TIMEOUT_S,
    CLOUD_LLM_URL,
    CLOUD_MAX_RESPONSE_CHARS,
    DEFAULT_LANGUAGE,
    DEVICE_ID,
    DYP_A22_BAUDRATE,
    DYP_A22_BOTTOM_PORT,
    DYP_A22_TOP_PORT,
    EMERGENCY_BUTTON_GPIO,
    GRAPHHOPPER_URL,
    GUARDIAN_CACHE_PATH,
    GUARDIAN_FETCH_TIMEOUT_S,
    HEADING_CHECK_INTERVAL_S,
    HEARTBEAT_INTERVAL_S,
    INTERNET_PROBE_TIMEOUT_S,
    INTERNET_PROBE_URL,
    LOW_BATTERY_PERCENT,
    LOW_BATTERY_RECOVERY_PERCENT,
    LOW_BATTERY_STATE_PATH,
    MAG_ADDRESS,
    MAG_FORWARD_AXIS,
    MAG_I2C_BUS,
    MAG_LEFT_AXIS,
    MAG_OFFSET_X,
    MAG_OFFSET_Y,
    MAG_OFFSET_Z,
    MAG_SCALE_X,
    MAG_SCALE_Y,
    MAG_SCALE_Z,
    MPU6050_ADDRESS,
    MPU6050_I2C_BUS,
    NLU_MODEL,
    NLU_PROMPT_PATH,
    NLU_TIMEOUT_S,
    NLU_WARMUP_TIMEOUT_S,
    OBSTACLE_COOLDOWN_S,
    OBSTACLE_DANGER_CM,
    OBSTACLE_WARNING_CM,
    OLLAMA_URL,
    PHOTON_URL,
    PIPER_VOICES,
    PTT_BUTTON_GPIO,
    PTT_MAX_RECORDING_S,
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
    VOICE_TEST_DIR,
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
from indepensense.intents.base import Intent, IntentResult
from indepensense.intents.cloud import OfflineGuard
from indepensense.intents.mistral import MistralAnswerer
from indepensense.intents.executor import IntentExecutor
from indepensense.intents.parser import OllamaIntentParser
from indepensense.language import LanguageState
from indepensense.messaging.mmcli_sms import MMCLISMSSender
from indepensense.navigation.monitor import NavigationCue, NavigationMonitor
from indepensense.power.waveshare_ups_e import WaveshareUPSHatE
from indepensense.routing.base import Coordinate
from indepensense.routing.graphhopper import GraphHopperRouter
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
from indepensense.telemetry.sms_alerts import SMSAlertNotifier
from indepensense.vision.detector import YOLOv8Detector
from indepensense.vision.ocr import TesseractOCR
from indepensense.vision.picamera import PiCamera
from indepensense.voice.audio import play, play_chime, record_until_button
from indepensense.voice.piper import PiperTTS
from indepensense.voice.whisper import FasterWhisperSTT


FALL_LOOP_INTERVAL_S = 0.01     # 100 Hz — matches ThresholdFallDetector's tuning
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
        # press while _voice_active is set is ignored. Emergency press
        # sets _voice_cancel to abort an in-progress voice cycle.
        self._voice_active = threading.Event()
        self._voice_cancel = threading.Event()
        self._voice_thread: threading.Thread | None = None

        # Placeholders — filled in by start()
        self.gps: SIM7600GPS | None = None
        self.gps_cache: GPSCache | None = None
        self.imu: MPU6050 | None = None
        self.detector: ThresholdFallDetector | None = None
        self.stt: FasterWhisperSTT | None = None
        self.tts: PiperTTS | None = None
        self.parser: OllamaIntentParser | None = None
        self.buffered: BufferedTelemetryClient | None = None
        # `alert_sink` is what every alert path posts to. It is either
        # `buffered` or `buffered` wrapped in an `SMSAlertNotifier` — the
        # wrapper adds guardian SMS to all three alert paths at once.
        # Heartbeats deliberately keep using `buffered` directly.
        self.alert_sink = None
        self.guardians: GuardianDirectory | None = None
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
        self._obstacle_last_fired: dict[str, float] = {}

        # Mutex around warning playback so two overlapping warnings
        # don't race on the buzzer or motor state.
        self._warning_lock = threading.Lock()

    # ---------------------------------------------------------------- lifecycle

    def start(self) -> None:
        print("Initialising IndepenSense runtime...", flush=True)

        print("  Opening MPU6050...", flush=True)
        self.imu = self._open_imu()
        self.detector = ThresholdFallDetector()

        print("  Opening GPS...", flush=True)
        self.gps = self._try_open_gps()
        cached_gps = None
        if self.gps is not None:
            self.gps_cache = GPSCache(self.gps, poll_interval_s=GPS_CACHE_INTERVAL_S)
            self.gps_cache.start()
            cached_gps = _CachedGPSAdapter(self.gps_cache)

        print("  Loading Whisper models...", flush=True)
        self.stt = self._open_stt()

        print("  Loading Piper voices...", flush=True)
        self.tts = self._open_tts()

        print("  Connecting to Ollama (with warmup)...", flush=True)
        self.parser = self._open_parser()

        print("  Checking cloud LLM fallback...", flush=True)
        self.cloud = self._try_open_cloud_answerer()

        print("  Connecting to GraphHopper + Photon...", flush=True)
        router = self._open_router()
        geocoder = self._open_geocoder()

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
            device_id=DEVICE_ID,
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
                )
        self.alert_sink = alert_sink

        # NB: battery isn't opened yet — wire it after this block. Store
        # the executor construction here anyway so the button handlers
        # can be registered right after. We patch the battery in later.
        self.executor = IntentExecutor(
            router=router,
            geocoder=geocoder,
            gps=cached_gps,
            telemetry=self.alert_sink,
            device_id=DEVICE_ID,
            monitor=self.nav_monitor,
            language=self.language,
            cloud=self.cloud,
            cloud_max_chars=CLOUD_MAX_RESPONSE_CHARS,
            ocr_max_chars=OCR_MAX_CHARS,
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
            device_id=DEVICE_ID,
            interval_s=HEARTBEAT_INTERVAL_S,
            battery=self.battery,
            internet_probe_url=INTERNET_PROBE_URL,
            internet_probe_timeout_s=INTERNET_PROBE_TIMEOUT_S,
        )
        self.heartbeat_sender.start()

        print(
            f"Ready (language: {self.language.current}). Running fall-detection "
            f"loop. SIGINT/SIGTERM to stop.",
            flush=True,
        )
        self._speak_greeting()

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

        # Use current cached GPS fix; fall back to 0.0/0.0 if unknown.
        # The alert goes out regardless — safety > location precision.
        lat, lon = 0.0, 0.0
        if self.gps_cache is not None:
            fix = self.gps_cache.latest_fix()
            if fix is not None:
                lat, lon = fix.lat, fix.lon

        alert = AlertEvent(
            device_id=DEVICE_ID,
            event_type=EventType.FALL_DETECTION,
            latitude=lat,
            longitude=lon,
            occurred_at=datetime.now(timezone.utc),
        )
        if self.alert_sink is not None:
            self.alert_sink.send_alert(alert)

    # ---------------------------------------------------------------- battery

    def _check_battery_and_alert(self) -> None:
        """Poll battery and fire a LOW_BATTERY alert on threshold crossing.

        Called from the 100 Hz main loop but internally rate-limited to
        `BATTERY_CHECK_INTERVAL_S` — battery changes slowly, no reason
        to hammer the I²C bus. Hysteresis (separate fire + recovery
        thresholds) prevents alert flapping when hovering at 15%.
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
                self._set_low_battery_latch(True)

    def latest_heading(self) -> float | None:
        """Most recent compass heading in degrees, or None if unavailable.

        Never touches the I²C bus — returns whatever `_check_heading` last
        cached. `None` means either no magnetometer or no successful read yet.
        """
        return self._last_heading_deg

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
        """Whether we had already alerted before this process started.

        Any read problem is treated as "not alerted". The cost of getting
        that wrong is one extra alert; the cost of the opposite would be a
        low battery that never warns anyone.
        """
        try:
            return LOW_BATTERY_STATE_PATH.exists()
        except OSError as exc:
            print(f"[battery] could not read latch: {exc}", file=sys.stderr, flush=True)
            return False

    def _set_low_battery_latch(self, alerted: bool) -> None:
        """Set the latch and mirror it to disk.

        Presence of the file is the state — no contents to parse, so a
        truncated write cannot be misread. Persistence is best effort: if
        the write fails the latch still holds for this session, it just
        won't survive a restart.
        """
        self._low_battery_alerted = alerted
        try:
            if alerted:
                LOW_BATTERY_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
                LOW_BATTERY_STATE_PATH.touch()
            else:
                LOW_BATTERY_STATE_PATH.unlink(missing_ok=True)
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
            device_id=DEVICE_ID,
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
            cues = self.nav_monitor.check(position)
        except Exception as exc:
            print(f"[nav] monitor error: {exc}", file=sys.stderr, flush=True)
            return

        for cue in cues:
            self._fire_navigation_cue(cue)

    def _fire_navigation_cue(self, cue: NavigationCue) -> None:
        """Route a NavigationCue to its actuator.

        - "announce": speak the text via Piper (skipped if voice pipeline
          is currently busy — we don't want to talk over a user's
          command or a response mid-play).
        - "haptic": pulse the direction-matching motor.
        - "arrive": speak + pulse all motors (louder cue for the finish).
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
                self._speak_error(cue.text)   # reuse the speak helper
            elif cue.kind == "haptic":
                motor = self._motor_for_direction(cue.direction)
                if motor is not None:
                    print(f"[nav] haptic: {cue.direction}", flush=True)
                    motor.pulse(times=2, duration_s=0.2, gap_s=0.1)
            elif cue.kind == "arrive":
                print(f"[nav] arrive: {cue.text}", flush=True)
                with self._warning_lock:
                    self._pulse_all_motors(duration_s=0.4)
                if not self._voice_active.is_set() and cue.text is not None:
                    self._speak_error(cue.text)
            elif cue.kind == "off_route":
                # Deviation warning — spoken + a distinctive all-motor
                # pulse so the user notices even if they missed the
                # audio. Deferred when a voice command is in flight.
                if self._voice_active.is_set():
                    print(
                        f"[nav] deferred off_route (voice busy): {cue.text}",
                        flush=True,
                    )
                    return
                print(f"[nav] off_route: {cue.text}", flush=True)
                with self._warning_lock:
                    self._pulse_all_motors(duration_s=0.3)
                if cue.text is not None:
                    self._speak_error(cue.text)
        except Exception as exc:
            print(f"[nav] fire error: {exc}", file=sys.stderr, flush=True)

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
        """Poll one ultrasonic sensor and fire a warning if in range.

        Called from the main 100 Hz loop. Returns fast when the sensor
        has no fresh frame (which is 9 out of 10 ticks — DYP-A22 emits
        at ~10 Hz). Cooldowns prevent spamming when an obstacle stays
        in a zone.
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
        if distance < OBSTACLE_DANGER_CM:
            tier = "danger"
        elif distance < OBSTACLE_WARNING_CM:
            tier = "warning"
        else:
            return   # safe zone; nothing to fire

        # Cooldown per (sensor, tier). A moving obstacle that crosses
        # from warning into danger will fire "danger" immediately even
        # if "warning" fired a moment ago — different key.
        key = f"{sensor_name}:{tier}"
        now = time.monotonic()
        last_fired = self._obstacle_last_fired.get(key, 0.0)
        if now - last_fired < OBSTACLE_COOLDOWN_S:
            return
        self._obstacle_last_fired[key] = now

        print(
            f"[obstacle:{sensor_name}] {tier} at {distance:.0f} cm",
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
        """
        with self._warning_lock:
            try:
                if sensor_name == "top" and tier == "warning":
                    if self.front_motor is not None:
                        self.front_motor.pulse(times=1, duration_s=0.25)
                    if self.buzzer is not None:
                        self.buzzer.beep(times=1, duration_s=0.1)
                elif sensor_name == "top" and tier == "danger":
                    self._pulse_all_motors(duration_s=0.4)
                    if self.buzzer is not None:
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
            print("[PTT] Voice pipeline busy — press ignored.", flush=True)
            return

        self._voice_active.set()
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
        emergencies SHOULD be loud) + all-motor pulse. Then the existing
        spoken confirmation plays.
        """
        self._voice_cancel.set()
        print("\n[EMERGENCY BUTTON] Pressed. Firing alert...", flush=True)

        # Immediate haptic + audible ack — user needs to know the alert
        # is being sent before waiting for the spoken confirmation.
        self._play_emergency_feedback()

        try:
            response = self.executor.execute(
                IntentResult(intent=Intent.EMERGENCY_TRIGGER)
            )
            print(f"[EMERGENCY BUTTON] response: {response}", flush=True)

            timestamp = datetime.now().strftime("%B-%d-%Y_%H-%M-%S")
            resp_path = VOICE_TEST_DIR / f"{timestamp}_emergency.wav"
            self.tts.synthesize(response, resp_path, language=self.language.current)
            play(resp_path)
        except Exception as exc:
            print(f"[EMERGENCY BUTTON] handler error: {exc}", file=sys.stderr, flush=True)

    def _on_repeat_press(self) -> None:
        """Repeat press: repeats the last navigation instruction.

        No-op if there's no active navigation — the executor returns a
        clear message the user hears. If the wearable ever grows a
        "repeat any last response" feature, it lives in the executor,
        not here.

        Feedback: brief all-motor pulse (same shape as PTT/Emergency
        acks) so the user knows the button was received.
        """
        if self._voice_active.is_set():
            print("[REPEAT] Voice pipeline busy — press ignored.", flush=True)
            return
        self._play_button_ack()
        try:
            response = self.executor.execute(
                IntentResult(intent=Intent.NAVIGATION_REPEAT)
            )
            print(f"[REPEAT] response: {response}", flush=True)

            timestamp = datetime.now().strftime("%B-%d-%Y_%H-%M-%S")
            resp_path = VOICE_TEST_DIR / f"{timestamp}_repeat.wav"
            self.tts.synthesize(response, resp_path, language=self.language.current)
            play(resp_path)
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

    def _play_press_feedback(self, rising_chime: bool) -> None:
        """PTT start/stop feedback: all-motor pulse + audio chime.

        `rising_chime=True` for recording start, `False` for stop. Runs
        the motor pulse and chime in sequence — motor first (brief and
        felt), then chime (heard) — total ~270 ms. This precedes
        recording so the chime isn't captured into the audio file.
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
            print(f"[PTT] Captured {duration:.1f} s of audio.", flush=True)

            if self._voice_cancel.is_set():
                # Emergency preempted us — its own feedback pattern is
                # already playing; skip the PTT stop feedback to avoid
                # audio contention on the same output device.
                print("[PTT] Recording preempted by emergency — skipping.", flush=True)
                return
            if duration <= 0.2:
                print("[PTT] Too short — skipping.", flush=True)
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

            transcript = self.stt.transcribe(
                input_path,
                language=self.language.current,
                initial_prompt=WHISPER_INITIAL_PROMPTS.get(self.language.current) or None,
            )
            print(f"[PTT] Transcript: {transcript.text!r}", flush=True)
            if self._voice_cancel.is_set() or not transcript.text.strip():
                return

            intent_result = self.parser.parse(transcript.text)
            print(
                f"[PTT] Intent: {intent_result.intent.value} "
                f"params={intent_result.parameters}",
                flush=True,
            )

            # A cloud answer takes seconds. A sighted user watches a
            # spinner; this user hears nothing and cannot tell whether
            # the wearable is thinking or dead. Say so before the wait.
            if intent_result.intent is Intent.UNKNOWN and self.cloud is not None:
                self._speak_thinking()
                if self._voice_cancel.is_set():
                    return

            response = self.executor.execute(intent_result)
            print(f"[PTT] Response: {response}", flush=True)
            if self._voice_cancel.is_set():
                return

            self.tts.synthesize(response, response_path, language=self.language.current)
            if self._voice_cancel.is_set():
                return
            play(response_path)
        except Exception as exc:
            print(f"[PTT] voice pipeline error: {exc}", file=sys.stderr, flush=True)
            # Speak a short error so the user isn't left wondering why
            # nothing happened. Wrapped in its own try/except so a
            # broken TTS doesn't cascade into an infinite error loop.
            self._speak_error("Something went wrong. Please try again.")
        finally:
            # Restore our PTT handler — record_until_button overwrote it.
            if self.ptt_button is not None:
                try:
                    self.ptt_button.on("pressed", self._on_ptt_press)
                except Exception:
                    pass
            self._voice_active.clear()

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
        """
        try:
            timestamp = datetime.now().strftime("%B-%d-%Y_%H-%M-%S")
            thinking_path = VOICE_TEST_DIR / f"{timestamp}_thinking.wav"
            self.tts.synthesize(
                messages.get("cloud.thinking", self.language.current),
                thinking_path,
                language=self.language.current,
            )
            play(thinking_path)
        except Exception as exc:
            print(f"[thinking] could not speak: {exc}", file=sys.stderr, flush=True)

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

    def _open_tts(self) -> PiperTTS:
        return PiperTTS(voices=PIPER_VOICES)

    def _open_parser(self) -> OllamaIntentParser:
        return OllamaIntentParser(
            model=NLU_MODEL,
            ollama_url=OLLAMA_URL,
            prompt_path=NLU_PROMPT_PATH,
            timeout_s=NLU_TIMEOUT_S,
            warmup=True,
            warmup_timeout_s=NLU_WARMUP_TIMEOUT_S,
        )

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

        No provider driver exists yet; `intents/cloud.py` documents what
        one has to implement. `OfflineGuard` is applied here rather than
        inside a driver so every future provider inherits it.
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
            probe_url=INTERNET_PROBE_URL,
            probe_timeout_s=INTERNET_PROBE_TIMEOUT_S,
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

    def _open_telemetry_client(self) -> NestJSTelemetryClient:
        """The raw backend client. `start()` wraps whatever this returns in
        a `BufferedTelemetryClient`, so the buffering/retry behaviour is
        exercised identically under mocks."""
        return NestJSTelemetryClient(
            base_url=BACKEND_URL, timeout_s=TELEMETRY_TIMEOUT_S,
        )

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
            return WaveshareUPSHatE(bus_number=UPS_HAT_I2C_BUS)
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
