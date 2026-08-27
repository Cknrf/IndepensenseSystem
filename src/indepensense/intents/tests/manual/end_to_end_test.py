"""Manual end-to-end voice-command test: mic → STT → intent → action → TTS.

Wires every voice-layer module together with the real routing/geocoding
services and (if available) real GPS. This is the closest thing yet to
"actually being a voice assistant."

Two physical buttons drive interaction:

- **PTT (push-to-talk)** on `PTT_BUTTON_GPIO`. Press once to start
  recording, press again to stop. Falls back to keyboard Enter when
  the button isn't wired.
- **Emergency** on `EMERGENCY_BUTTON_GPIO`. Any press immediately fires
  `emergency.trigger` — bypasses STT/LLM entirely and POSTs an alert to
  the guardian backend. Press-fires-instantly is intentional: making an
  emergency wait for a currently-recording PTT session would defeat the
  point.

Concurrency caveat: the emergency handler runs on gpiozero's background
thread. If the user presses emergency mid-recording or mid-playback,
audio-device contention with sounddevice may briefly conflict. This is
acceptable for a manual test — proper cross-thread coordination lands
in `app.py`.

Prerequisites (all must be running on the Pi):
    - Ollama with NLU_MODEL pulled  (systemctl status ollama)
    - GraphHopper on port 8989
    - Photon on port 2322
    - USB mic plugged in as the PipeWire default source
    - Bluetooth headset paired for playback (or USB output)
    - GPS enabled if you want location-aware intents (AT+CGPS=1)
    - KY-004 PTT button on `PTT_BUTTON_GPIO` (fallback: keyboard Enter)
    - KY-004 Emergency button on `EMERGENCY_BUTTON_GPIO` (optional)

Run from repo root with:
    python -m indepensense.intents.tests.manual.end_to_end_test

    # No buttons wired? Drive it from the keyboard instead:
    python -m indepensense.intents.tests.manual.end_to_end_test --keyboard

Ctrl-C exits the loop cleanly.
"""
import argparse
import threading
import time
from datetime import datetime

from indepensense.config import (
    BACKEND_URL,
    DEVICE_KEY_PATH,
    EMERGENCY_BUTTON_GPIO,
    GRAPHHOPPER_URL,
    NLU_MODEL,
    NLU_PROMPT_PATH,
    NLU_TIMEOUT_S,
    NLU_WARMUP_TIMEOUT_S,
    OLLAMA_URL,
    PHOTON_URL,
    PIPER_VOICES,
    PTT_BUTTON_GPIO,
    SIM7600_GPS_PORT,
    DEFAULT_LANGUAGE,
    LANGUAGE_STATE_PATH,
    SUPPORTED_LANGUAGES,
    TELEMETRY_TIMEOUT_S,
    VOICE_TEST_DIR,
    WHISPER_INITIAL_PROMPTS,
    WHISPER_MODEL_DIR,
    WHISPER_MODELS,
)
from indepensense.intents.base import Intent, IntentResult
from indepensense.intents.executor import IntentExecutor
from indepensense.intents.parser import OllamaIntentParser
from indepensense.routing.graphhopper import GraphHopperRouter
from indepensense.routing.photon import PhotonGeocoder
from indepensense.credential import load_device_credential
from indepensense.language import LanguageState
from indepensense.telemetry.nestjs_client import NestJSTelemetryClient
from indepensense.voice.audio import (
    play,
    record_until_button,
    record_until_enter,
    wait_for_button_press,
)
from indepensense.voice.piper import PiperTTS
from indepensense.voice.whisper import FasterWhisperSTT


def _try_open_gps():
    """Try to open the SIM7600 GPS; return None if unavailable."""
    from indepensense.sensors.gps import SIM7600GPS
    try:
        return SIM7600GPS(port=SIM7600_GPS_PORT)
    except Exception as exc:
        print(f"  GPS unavailable ({exc}). Location-based intents will be limited.")
        return None


def _try_open_button():
    """Try to open the PTT button on GPIO; return None if unavailable.

    Returns None only when gpiozero cannot claim the pin at all — which
    happens on a Mac, but NOT on a Pi with nothing wired to the pin.
    gpiozero constructs a `Button` on any valid GPIO regardless of what is
    physically attached; an unconnected input simply never fires. A missing
    button is indistinguishable from an unpressed one in software.

    So on real hardware without the wiring this succeeds, the script
    reports `PTT: button`, and then waits forever for a press that cannot
    come. Use `--keyboard` to force the Enter path.
    """
    try:
        from indepensense.feedback.gpio_button import GPIOButton
        return GPIOButton(gpio_pin=PTT_BUTTON_GPIO)
    except Exception as exc:
        print(f"  PTT button unavailable ({exc}). Falling back to keyboard Enter.")
        return None


def _try_open_emergency_button():
    """Try to open the Emergency button on GPIO; return None if unavailable.

    Unlike PTT there is no fallback — the emergency button is optional
    for the manual test. Voice-triggered emergency ("Help, emergency!")
    still works regardless.
    """
    try:
        from indepensense.feedback.gpio_button import GPIOButton
        return GPIOButton(gpio_pin=EMERGENCY_BUTTON_GPIO)
    except Exception as exc:
        print(f"  Emergency button unavailable ({exc}). Voice emergency still works.")
        return None


def _parse_args():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--keyboard",
        action="store_true",
        help="ignore the GPIO buttons and drive everything from the keyboard: "
             "Enter to start recording, Enter again to stop. Needed on a Pi "
             "where the buttons are not wired yet, since a missing button "
             "cannot be detected in software.",
    )
    return parser.parse_args()


def main():
    args = _parse_args()
    print("Initialising voice + intent stack...")
    print("  Loading Whisper models...")
    stt = FasterWhisperSTT(models=WHISPER_MODELS, model_dir=WHISPER_MODEL_DIR)
    print("  Loading Piper voices...")
    tts = PiperTTS(voices=PIPER_VOICES)
    print("  Connecting to Ollama...")
    parser = OllamaIntentParser(
        model=NLU_MODEL,
        ollama_url=OLLAMA_URL,
        prompt_path=NLU_PROMPT_PATH,
        timeout_s=NLU_TIMEOUT_S,
        warmup=True,
        warmup_timeout_s=NLU_WARMUP_TIMEOUT_S,
    )
    print("  Connecting to GraphHopper + Photon...")
    router = GraphHopperRouter(base_url=GRAPHHOPPER_URL)
    geocoder = PhotonGeocoder(base_url=PHOTON_URL)
    print("  Opening GPS...")
    gps = _try_open_gps()
    if args.keyboard:
        print("  Keyboard mode (--keyboard): skipping both GPIO buttons.")
        button = None
        emergency_button = None
    else:
        print("  Opening PTT button...")
        button = _try_open_button()
        print("  Opening Emergency button...")
        emergency_button = _try_open_emergency_button()
    print(f"  Connecting telemetry to {BACKEND_URL}...")
    credential = load_device_credential(DEVICE_KEY_PATH)
    if credential is None:
        print(f"No usable credential at {DEVICE_KEY_PATH} — see stderr above.")
        raise SystemExit(1)
    telemetry = NestJSTelemetryClient(
        credential=credential,
        base_url=BACKEND_URL, timeout_s=TELEMETRY_TIMEOUT_S
    )

    # Shared by reference with the executor, and read fresh at every STT
    # and TTS call below — the same arrangement as `app.py`. Without this
    # the executor built its own state defaulting to English while STT and
    # TTS stayed pinned to DEFAULT_LANGUAGE, so `system.language` appeared
    # to do nothing: the switch happened somewhere nothing else could see.
    #
    # Persists to the same file the app uses, so a switch made here is
    # still in effect the next time the wearable boots.
    language = LanguageState(
        default=DEFAULT_LANGUAGE,
        supported=SUPPORTED_LANGUAGES,
        state_path=LANGUAGE_STATE_PATH,
    )

    executor = IntentExecutor(
        router=router,
        geocoder=geocoder,
        gps=gps,
        telemetry=telemetry,
        device_id=credential.device_id,
        language=language,
    )

    # Shared cancel flag: emergency callback sets it to signal any
    # in-progress PTT recording/processing that it should abort. The
    # main loop clears it at the top of every fresh PTT cycle.
    cancel_recording = threading.Event()

    # Wire the emergency button. Its handler runs on gpiozero's background
    # thread and fires the emergency.trigger intent immediately —
    # bypassing recording and STT entirely. Setting `cancel_recording`
    # aborts any in-progress PTT recording so the mic and speaker don't
    # contend with the emergency's TTS output.
    if emergency_button is not None:
        def _on_emergency_press() -> None:
            cancel_recording.set()
            print("\n[EMERGENCY BUTTON] Pressed. Firing alert...", flush=True)
            timestamp = datetime.now().strftime("%B-%d-%Y_%H-%M-%S")
            resp_path = VOICE_TEST_DIR / f"{timestamp}_emergency.wav"
            try:
                response = executor.execute(IntentResult(intent=Intent.EMERGENCY_TRIGGER))
                print(f"[EMERGENCY BUTTON] response: {response}", flush=True)
                tts.synthesize(response, resp_path, language=language.current)
                play(resp_path)
            except Exception as exc:
                print(f"[EMERGENCY BUTTON] handler error: {exc}", flush=True)

        emergency_button.on("pressed", _on_emergency_press)

    trigger = "button" if button is not None else "keyboard"
    emerg = "wired" if emergency_button is not None else "not wired"
    print(f"Ready. Active language: {language.current}. PTT: {trigger}. Emergency button: {emerg}.\n")

    try:
        while True:
            # Fresh cycle — clear any lingering emergency-cancel signal.
            cancel_recording.clear()

            if button is not None:
                wait_for_button_press(button, "Press PTT button to START recording (Ctrl-C to quit)...")
            else:
                input("Press Enter to START recording (Ctrl-C to quit): ")

            timestamp = datetime.now().strftime("%B-%d-%Y_%H-%M-%S")
            input_path = VOICE_TEST_DIR / f"{timestamp}_command.wav"
            response_path = VOICE_TEST_DIR / f"{timestamp}_response.wav"

            # 1. Record — push-to-talk style, cancellable by the emergency button.
            print("  Recording... press again to stop." if button is not None
                  else "  Recording... press Enter to stop.")
            t0 = time.time()
            if button is not None:
                duration = record_until_button(button, input_path, cancel_event=cancel_recording)
            else:
                duration = record_until_enter(input_path)
            print(f"  ({time.time() - t0:.1f}s wall, {duration:.1f}s audio) saved to {input_path.name}")

            if cancel_recording.is_set():
                print("  Recording preempted by emergency — skipping this cycle.\n")
                continue

            if duration <= 0.2:
                print("  Too short — try again.\n")
                continue

            # 2. Transcribe — hint Whisper with local proper nouns so the
            # tiny English model stops mishearing "Jollibee" as "Jalebi" etc.
            t0 = time.time()
            transcript = stt.transcribe(
                input_path,
                language=language.current,
                initial_prompt=WHISPER_INITIAL_PROMPTS.get(language.current) or None,
            )
            print(f"  ({time.time() - t0:.1f}s) transcript: {transcript.text or '(silence)'}")

            if not transcript.text.strip():
                print("  Empty transcript — try again.\n")
                continue

            # 3. Parse intent
            t0 = time.time()
            intent_result = parser.parse(transcript.text)
            print(f"  ({time.time() - t0:.1f}s) intent: {intent_result.intent.value} "
                  f"params: {intent_result.parameters}")
            if intent_result.raw_llm_response:
                print(f"    raw LLM: {intent_result.raw_llm_response}")

            # 4. Execute
            t0 = time.time()
            response = executor.execute(intent_result)
            print(f"  ({time.time() - t0:.1f}s) response: {response}")

            # 5. Synthesise + play — check cancel one more time so we don't
            # step on the emergency's TTS output at the speaker.
            t0 = time.time()
            tts.synthesize(response, response_path, language=language.current)
            print(f"  ({time.time() - t0:.1f}s) synthesised {response_path.name}")

            if cancel_recording.is_set():
                print("  Playback preempted by emergency — skipping this cycle.\n")
                continue

            print("  Playing back...")
            play(response_path)
            print()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        if gps is not None:
            gps.close()
        if button is not None:
            button.close()
        if emergency_button is not None:
            emergency_button.close()


if __name__ == "__main__":
    main()
