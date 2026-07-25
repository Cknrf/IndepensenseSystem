"""Manual end-to-end voice-command test: mic → STT → intent → action → TTS.

Wires every voice-layer module together with the real routing/geocoding
services and (if available) real GPS. This is the closest thing yet to
"actually being a voice assistant."

Push-to-talk is driven by a physical KY-004 button on the GPIO pin
configured by `PTT_BUTTON_GPIO`. Press once to start recording, press
again to stop. A safety cap of 60 s bounds runaway recordings.

If the button hardware is unavailable (running on Mac, GPIO chip busy,
etc.) the script falls back to keyboard Enter so it stays runnable during
development.

Prerequisites (all must be running on the Pi):
    - Ollama with NLU_MODEL pulled  (systemctl status ollama)
    - GraphHopper on port 8989
    - Photon on port 2322
    - USB mic plugged in as the PipeWire default source
    - Bluetooth headset paired for playback (or USB output)
    - GPS enabled if you want location-aware intents (AT+CGPS=1)
    - KY-004 button wired to `PTT_BUTTON_GPIO` (fallback: keyboard Enter)

Run from repo root with:
    python -m indepensense.intents.tests.manual.end_to_end_test

Ctrl-C exits the loop cleanly.
"""
import time
from datetime import datetime

from indepensense.config import (
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
    SYSTEM_LANGUAGE,
    VOICE_TEST_DIR,
    WHISPER_MODEL_DIR,
    WHISPER_MODELS,
)
from indepensense.intents.executor import IntentExecutor
from indepensense.intents.parser import OllamaIntentParser
from indepensense.routing.graphhopper import GraphHopperRouter
from indepensense.routing.photon import PhotonGeocoder
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

    Falls back to None (keyboard mode) when gpiozero can't claim the pin —
    which is what happens on a Mac, or on a Pi without the wiring in place.
    """
    try:
        from indepensense.feedback.gpio_button import GPIOButton
        return GPIOButton(gpio_pin=PTT_BUTTON_GPIO)
    except Exception as exc:
        print(f"  PTT button unavailable ({exc}). Falling back to keyboard Enter.")
        return None


def main():
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
    print("  Opening PTT button...")
    button = _try_open_button()

    executor = IntentExecutor(router=router, geocoder=geocoder, gps=gps)
    trigger = "button" if button is not None else "keyboard"
    print(f"Ready. Active language: {SYSTEM_LANGUAGE}. Trigger: {trigger}.\n")

    try:
        while True:
            if button is not None:
                wait_for_button_press(button, "Press PTT button to START recording (Ctrl-C to quit)...")
            else:
                input("Press Enter to START recording (Ctrl-C to quit): ")

            timestamp = datetime.now().strftime("%B-%d-%Y_%H-%M-%S")
            input_path = VOICE_TEST_DIR / f"{timestamp}_command.wav"
            response_path = VOICE_TEST_DIR / f"{timestamp}_response.wav"

            # 1. Record — push-to-talk style
            print("  Recording... press again to stop." if button is not None
                  else "  Recording... press Enter to stop.")
            t0 = time.time()
            if button is not None:
                duration = record_until_button(button, input_path)
            else:
                duration = record_until_enter(input_path)
            print(f"  ({time.time() - t0:.1f}s wall, {duration:.1f}s audio) saved to {input_path.name}")

            if duration <= 0.2:
                print("  Too short — try again.\n")
                continue

            # 2. Transcribe
            t0 = time.time()
            transcript = stt.transcribe(input_path, language=SYSTEM_LANGUAGE)
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

            # 5. Synthesise + play
            t0 = time.time()
            tts.synthesize(response, response_path, language=SYSTEM_LANGUAGE)
            print(f"  ({time.time() - t0:.1f}s) synthesised {response_path.name}")

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


if __name__ == "__main__":
    main()
