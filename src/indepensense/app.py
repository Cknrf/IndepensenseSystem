"""IndepenSense wearable runtime.

The single long-running process that IS the wearable. Loads models once,
then runs a synchronous fall-detection loop while background threads
handle voice, heartbeats, telemetry retry, and GPS caching.

Concurrency model
-----------------

We have a synchronous main loop for sensor polling PLUS several
well-scoped background threads for I/O concerns:

  - Main thread: 100 Hz MPU6050 read → fall detector → alert on event.
    Cheap sensor reads only — anything blocking (network, LLM, TTS)
    runs elsewhere.
  - PTT button callback (gpiozero thread pool): spawns a voice thread
    per press. Second press while voice is busy is ignored.
  - Voice thread (one at a time, per PTT session): record → STT →
    parse → execute → TTS → play. Emergency signal aborts mid-way.
  - Emergency button callback: sets cancel flag AND runs the emergency
    handler directly. This preempts voice AND fires the alert without
    waiting for the voice thread to finish.
  - Repeat button callback: replays the last navigation instruction.
  - Heartbeat sender (already built): every N seconds, non-blocking.
  - Telemetry worker (already built): drains queue, retries failures.
  - GPS cache thread: polls SIM7600 GPS at 1 Hz, exposes latest fix to
    all consumers (executor, heartbeat, fall alerts) without serial
    port contention.

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
"""
import signal
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

from indepensense.config import (
    BACKEND_URL,
    DEVICE_ID,
    EMERGENCY_BUTTON_GPIO,
    GRAPHHOPPER_URL,
    HEARTBEAT_INTERVAL_S,
    MPU6050_ADDRESS,
    MPU6050_I2C_BUS,
    NLU_MODEL,
    NLU_PROMPT_PATH,
    NLU_TIMEOUT_S,
    NLU_WARMUP_TIMEOUT_S,
    OLLAMA_URL,
    PHOTON_URL,
    PIPER_VOICES,
    PTT_BUTTON_GPIO,
    REPEAT_BUTTON_GPIO,
    SIM7600_GPS_PORT,
    SYSTEM_LANGUAGE,
    TELEMETRY_TIMEOUT_S,
    VOICE_TEST_DIR,
    WHISPER_INITIAL_PROMPTS,
    WHISPER_MODEL_DIR,
    WHISPER_MODELS,
)
from indepensense.feedback.gpio_button import GPIOButton
from indepensense.intents.base import Intent, IntentResult
from indepensense.intents.executor import IntentExecutor
from indepensense.intents.parser import OllamaIntentParser
from indepensense.routing.graphhopper import GraphHopperRouter
from indepensense.routing.photon import PhotonGeocoder
from indepensense.safety.fall_detector import ThresholdFallDetector
from indepensense.sensors.gps import SIM7600GPS
from indepensense.sensors.mpu6050 import MPU6050
from indepensense.telemetry.base import AlertEvent, EventType
from indepensense.telemetry.buffered import BufferedTelemetryClient
from indepensense.telemetry.heartbeat import PeriodicHeartbeatSender
from indepensense.telemetry.nestjs_client import NestJSTelemetryClient
from indepensense.voice.audio import play, record_until_button
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
        self.heartbeat_sender: PeriodicHeartbeatSender | None = None
        self.executor: IntentExecutor | None = None
        self.ptt_button: GPIOButton | None = None
        self.emergency_button: GPIOButton | None = None
        self.repeat_button: GPIOButton | None = None

    # ---------------------------------------------------------------- lifecycle

    def start(self) -> None:
        print("Initialising IndepenSense runtime...", flush=True)

        print("  Opening MPU6050...", flush=True)
        self.imu = MPU6050(bus_number=MPU6050_I2C_BUS, address=MPU6050_ADDRESS)
        self.detector = ThresholdFallDetector()

        print("  Opening GPS...", flush=True)
        try:
            self.gps = SIM7600GPS(port=SIM7600_GPS_PORT)
            self.gps_cache = GPSCache(self.gps, poll_interval_s=GPS_CACHE_INTERVAL_S)
            self.gps_cache.start()
            cached_gps = _CachedGPSAdapter(self.gps_cache)
        except Exception as exc:
            print(f"  GPS unavailable ({exc}). Location intents will be limited.", flush=True)
            cached_gps = None

        print("  Loading Whisper models...", flush=True)
        self.stt = FasterWhisperSTT(models=WHISPER_MODELS, model_dir=WHISPER_MODEL_DIR)

        print("  Loading Piper voices...", flush=True)
        self.tts = PiperTTS(voices=PIPER_VOICES)

        print("  Connecting to Ollama (with warmup)...", flush=True)
        self.parser = OllamaIntentParser(
            model=NLU_MODEL,
            ollama_url=OLLAMA_URL,
            prompt_path=NLU_PROMPT_PATH,
            timeout_s=NLU_TIMEOUT_S,
            warmup=True,
            warmup_timeout_s=NLU_WARMUP_TIMEOUT_S,
        )

        print("  Connecting to GraphHopper + Photon...", flush=True)
        router = GraphHopperRouter(base_url=GRAPHHOPPER_URL)
        geocoder = PhotonGeocoder(base_url=PHOTON_URL)

        print(f"  Building buffered telemetry to {BACKEND_URL}...", flush=True)
        raw_client = NestJSTelemetryClient(
            base_url=BACKEND_URL, timeout_s=TELEMETRY_TIMEOUT_S,
        )
        self.buffered = BufferedTelemetryClient(raw_client)

        self.executor = IntentExecutor(
            router=router,
            geocoder=geocoder,
            gps=cached_gps,
            telemetry=self.buffered,
            device_id=DEVICE_ID,
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

        print("  Starting heartbeat sender...", flush=True)
        self.heartbeat_sender = PeriodicHeartbeatSender(
            telemetry=self.buffered,
            gps=cached_gps,
            device_id=DEVICE_ID,
            interval_s=HEARTBEAT_INTERVAL_S,
        )
        self.heartbeat_sender.start()

        print("Ready. Running fall-detection loop. SIGINT/SIGTERM to stop.", flush=True)

    def run(self) -> None:
        """Main 100 Hz sensor loop. Blocks until shutdown."""
        try:
            while not self._shutdown.is_set():
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

        # Best-effort close on everything else — never fail shutdown.
        for name, resource in (
            ("GPS", self.gps),
            ("MPU6050", self.imu),
            ("PTT button", self.ptt_button),
            ("Emergency button", self.emergency_button),
            ("Repeat button", self.repeat_button),
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
        if self.buffered is not None:
            self.buffered.send_alert(alert)

    # ---------------------------------------------------------------- buttons

    def _on_ptt_press(self) -> None:
        """PTT press handler. First press spawns a voice thread; presses
        while a voice thread is running are ignored (per design)."""
        if self._voice_active.is_set():
            print("[PTT] Voice pipeline busy — press ignored.", flush=True)
            return

        self._voice_active.set()
        self._voice_cancel.clear()
        self._voice_thread = threading.Thread(
            target=self._voice_pipeline, name="voice", daemon=True,
        )
        self._voice_thread.start()

    def _on_emergency_press(self) -> None:
        """Emergency press handler. Cancels any voice work and fires
        the emergency alert immediately."""
        self._voice_cancel.set()
        print("\n[EMERGENCY BUTTON] Pressed. Firing alert...", flush=True)

        try:
            response = self.executor.execute(
                IntentResult(intent=Intent.EMERGENCY_TRIGGER)
            )
            print(f"[EMERGENCY BUTTON] response: {response}", flush=True)

            timestamp = datetime.now().strftime("%B-%d-%Y_%H-%M-%S")
            resp_path = VOICE_TEST_DIR / f"{timestamp}_emergency.wav"
            self.tts.synthesize(response, resp_path, language=SYSTEM_LANGUAGE)
            play(resp_path)
        except Exception as exc:
            print(f"[EMERGENCY BUTTON] handler error: {exc}", file=sys.stderr, flush=True)

    def _on_repeat_press(self) -> None:
        """Repeat press: repeats the last navigation instruction.

        No-op if there's no active navigation — the executor returns a
        clear message the user hears. If the wearable ever grows a
        "repeat any last response" feature, it lives in the executor,
        not here.
        """
        if self._voice_active.is_set():
            print("[REPEAT] Voice pipeline busy — press ignored.", flush=True)
            return
        try:
            response = self.executor.execute(
                IntentResult(intent=Intent.NAVIGATION_REPEAT)
            )
            print(f"[REPEAT] response: {response}", flush=True)

            timestamp = datetime.now().strftime("%B-%d-%Y_%H-%M-%S")
            resp_path = VOICE_TEST_DIR / f"{timestamp}_repeat.wav"
            self.tts.synthesize(response, resp_path, language=SYSTEM_LANGUAGE)
            play(resp_path)
        except Exception as exc:
            print(f"[REPEAT] handler error: {exc}", file=sys.stderr, flush=True)

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
                self.ptt_button, input_path, cancel_event=self._voice_cancel,
            )
            print(f"[PTT] Captured {duration:.1f} s of audio.", flush=True)

            if self._voice_cancel.is_set():
                print("[PTT] Recording preempted by emergency — skipping.", flush=True)
                return
            if duration <= 0.2:
                print("[PTT] Too short — skipping.", flush=True)
                return

            transcript = self.stt.transcribe(
                input_path,
                language=SYSTEM_LANGUAGE,
                initial_prompt=WHISPER_INITIAL_PROMPTS.get(SYSTEM_LANGUAGE) or None,
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

            response = self.executor.execute(intent_result)
            print(f"[PTT] Response: {response}", flush=True)
            if self._voice_cancel.is_set():
                return

            self.tts.synthesize(response, response_path, language=SYSTEM_LANGUAGE)
            if self._voice_cancel.is_set():
                return
            play(response_path)
        except Exception as exc:
            print(f"[PTT] voice pipeline error: {exc}", file=sys.stderr, flush=True)
        finally:
            # Restore our PTT handler — record_until_button overwrote it.
            if self.ptt_button is not None:
                try:
                    self.ptt_button.on("pressed", self._on_ptt_press)
                except Exception:
                    pass
            self._voice_active.clear()

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


def main() -> None:
    VOICE_TEST_DIR.mkdir(parents=True, exist_ok=True)
    app = App()

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


if __name__ == "__main__":
    main()
