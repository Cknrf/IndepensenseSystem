"""Development-only runtime: the real `App` with every device mocked.

    python -m indepensense.app_mock

Why this exists
---------------

`app.py` holds the loop, the background threads, obstacle tiering,
navigation cue firing, battery alerting and the whole voice pipeline —
roughly a thousand lines of decision logic that has nothing to do with
any particular chip. On a Mac none of it could be run at all: `start()`
opens the MPU6050 first and `smbus2` doesn't exist off-device, so the
runtime died on its first line before this file existed.

`MockApp` subclasses `App` and overrides **only the device factories**.
Every line of behaviour is inherited and genuinely executed — this is not
a reimplementation, and there is nothing here to drift out of sync with
production. If you change how obstacles are tiered, you change it once.

Why it is not a flag inside `app.py`
------------------------------------

Because then production would carry the mock branch, and a
mis-configured flag could silently substitute a fake sensor on the real
device — a fall detector that cheerfully reports "no fall" forever. Here
the separation is structural rather than conditional:
`deploy/systemd/indepensense.service` starts `indepensense.app`, which
never imports this module. The deployed system cannot reach a mock, and
that is provable by reading the unit file rather than by auditing a
runtime code path.

What this does and does not cover
---------------------------------

Covered: the 100 Hz loop, fall detection, obstacle warnings, navigation
cues, battery alerting, heartbeats, telemetry buffering, intent parsing
and execution.

Not covered:
  - **Audio in and out.** `voice/audio.py` calls `sounddevice` directly
    rather than through an injected interface, so it isn't mockable from
    here. `pip install -r requirements.txt` gets you working playback and
    recording on a Mac; without it, a PTT press fails at record time
    while the rest of the runtime keeps going.
  - **Real sensor behaviour.** `MockIMU` reports a permanently level,
    stationary device, so the fall detector never fires on its own. Use
    `app.ptt_button.press()` and the other simulation hooks below to
    drive events deliberately.

Driving it
----------

The mock buttons are the real objects the runtime registered its
callbacks on, so pressing one runs the true handler:

    app.ptt_button.press()         # runs the voice pipeline
    app.emergency_button.press()   # fires the emergency path
    app.magnetometer.set_heading(90.0)

`MockBuzzer` and `MockVibrationMotor` record every call to a public
`events` list instead of making noise, so you can assert on what the
runtime tried to do:

    app.buzzer.events   # [("beep", 3, 0.1, 0.1), ...]
"""
import sys

from indepensense.app import App, run_app
from indepensense.config import (
    CAMERA_HEIGHT,
    CAMERA_WIDTH,
    MOCK_ULTRASONIC_MAX_CM,
    MOCK_ULTRASONIC_MIN_CM,
    MOCK_ULTRASONIC_PERIOD_S,
)
from indepensense.feedback.mock import MockButton, MockBuzzer, MockVibrationMotor
from indepensense.intents.mock import MockIntentParser
from indepensense.power.mock import MockBatteryReader
from indepensense.routing.mock import MockGeocoder, MockRouter
from indepensense.sensors.mock import (
    MockGPS,
    MockIMU,
    MockMagnetometer,
    MockUltrasonic,
)
from indepensense.telemetry.mock import MockTelemetryClient
from indepensense.vision.mock import MockCamera, MockDetector, MockOCR
from indepensense.voice.mock import MockSTT, MockTTS


class MockApp(App):
    """`App` with every device factory replaced by its mock.

    Overrides nothing else. If a method appears here that isn't a device
    factory, that's a bug — behaviour must be inherited so that what runs
    on a Mac is what runs on the Pi.
    """

    # --- sensors ---------------------------------------------------------

    def _open_imu(self) -> MockIMU:
        return MockIMU()

    def _try_open_gps(self) -> MockGPS:
        return MockGPS()

    def _try_open_ultrasonic(self, port: str, label: str) -> MockUltrasonic:
        return MockUltrasonic(
            min_cm=MOCK_ULTRASONIC_MIN_CM,
            max_cm=MOCK_ULTRASONIC_MAX_CM,
            period_s=MOCK_ULTRASONIC_PERIOD_S,
        )

    def _try_open_magnetometer(self) -> MockMagnetometer:
        return MockMagnetometer()

    def _try_open_battery(self) -> MockBatteryReader:
        return MockBatteryReader()

    # --- voice + language ------------------------------------------------

    def _open_stt(self) -> MockSTT:
        return MockSTT()

    def _open_tts(self) -> MockTTS:
        return MockTTS()

    def _open_parser(self) -> MockIntentParser:
        """Keyword matcher, not an LLM. Good enough to reach every branch
        of the executor; useless for measuring NLU accuracy — use
        `intents.tests.manual.llm_probe` against real Ollama for that."""
        return MockIntentParser()

    # --- routing + telemetry ---------------------------------------------

    def _open_router(self) -> MockRouter:
        return MockRouter()

    def _open_geocoder(self) -> MockGeocoder:
        return MockGeocoder()

    def _open_telemetry_client(self) -> MockTelemetryClient:
        """Accepts every payload and records it. `start()` still wraps this
        in the real `BufferedTelemetryClient`, so retry and buffering
        behaviour is exercised for real."""
        return MockTelemetryClient()

    # --- feedback --------------------------------------------------------

    def _try_open_button(self, gpio_pin: int, label: str) -> MockButton:
        return MockButton()

    def _try_open_buzzer(self) -> MockBuzzer:
        return MockBuzzer()

    def _try_open_motor(self, gpio_pin: int, label: str) -> MockVibrationMotor:
        return MockVibrationMotor()

    # --- vision ----------------------------------------------------------

    def _try_open_camera(self) -> MockCamera:
        return MockCamera(width=CAMERA_WIDTH, height=CAMERA_HEIGHT)

    def _try_open_detector(self) -> MockDetector:
        return MockDetector()

    def _try_open_ocr(self) -> MockOCR:
        return MockOCR()


def main() -> None:
    print("=" * 68, flush=True)
    print("  MOCK RUNTIME — every sensor is simulated. Not the real system.", flush=True)
    print("=" * 68, flush=True)
    if sys.platform == "linux":
        # Being here on the Pi almost certainly means someone ran the wrong
        # module. Say so loudly rather than letting fake sensor readings
        # look like a working device.
        print(
            "  WARNING: running the mock runtime on Linux. If this is the Pi, "
            "you want `python -m indepensense.app` instead.",
            flush=True,
        )
    run_app(MockApp())


if __name__ == "__main__":
    main()
