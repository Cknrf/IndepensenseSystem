"""Unit tests for IntentExecutor.

Uses the existing mock Router / mock Geocoder / mock GPS from the sensor
and routing modules — no live LLM, no live services, no hardware.
"""
import time

from indepensense.intents.base import Intent, IntentResult
from indepensense.intents.executor import IntentExecutor
from indepensense.language import LanguageState
from indepensense.navigation.monitor import NavigationMonitor
from indepensense.routing.base import Coordinate, GeocodingResult
from indepensense.routing.mock import MockGeocoder, MockRouter
from indepensense.sensors.base import GPSFix
from indepensense.telemetry.base import EventType
from indepensense.telemetry.mock import MockTelemetryClient


class _StaticGPS:
    """A GPS mock with configurable fix quality (0 = no fix, 1 = GPS)."""

    def __init__(self, lat: float = 14.5824, lon: float = 120.9760, fix_quality: int = 1):
        self._lat = lat
        self._lon = lon
        self._fix_quality = fix_quality

    def read(self) -> GPSFix | None:
        return GPSFix(
            lat=self._lat,
            lon=self._lon,
            altitude_m=15.0,
            speed_knots=0.0,
            course_deg=None,
            satellites=8,
            hdop=1.2,
            fix_quality=self._fix_quality,
            utc_time=None,
            timestamp=time.time(),
        )

    def close(self) -> None:
        pass


def _make_executor(fix_quality: int = 1) -> IntentExecutor:
    return IntentExecutor(
        router=MockRouter(),
        geocoder=MockGeocoder(),
        gps=_StaticGPS(fix_quality=fix_quality),
    )


def test_navigation_start_returns_route_summary():
    executor = _make_executor()
    result = IntentResult(
        intent=Intent.NAVIGATION_START,
        parameters={"location": "Jollibee", "nearest": False},
    )
    response = executor.execute(result)
    assert "Navigating" in response
    assert "Jollibee" in response


def test_navigation_start_without_location_asks_again():
    executor = _make_executor()
    result = IntentResult(Intent.NAVIGATION_START, {"location": "", "nearest": False})
    response = executor.execute(result)
    assert "didn't hear" in response.lower() or "try again" in response.lower()


def test_navigation_start_without_gps_fix_declines():
    executor = _make_executor(fix_quality=0)
    result = IntentResult(
        Intent.NAVIGATION_START, {"location": "Jollibee", "nearest": False}
    )
    response = executor.execute(result)
    assert "gps" in response.lower()


def test_navigation_stop_without_active_route_says_no_active():
    executor = _make_executor()
    response = executor.execute(IntentResult(Intent.NAVIGATION_STOP))
    assert "no" in response.lower() or "don't" in response.lower() or "active" in response.lower()


def test_navigation_stop_after_start_cancels():
    executor = _make_executor()
    executor.execute(IntentResult(
        Intent.NAVIGATION_START, {"location": "Jollibee", "nearest": False}
    ))
    response = executor.execute(IntentResult(Intent.NAVIGATION_STOP))
    assert "cancel" in response.lower()


def test_navigation_repeat_before_anything_said_returns_empty_message():
    executor = _make_executor()
    response = executor.execute(IntentResult(Intent.NAVIGATION_REPEAT))
    assert "nothing" in response.lower() or "repeat" in response.lower()


def test_navigation_repeat_after_start_returns_that_response():
    executor = _make_executor()
    start_response = executor.execute(IntentResult(
        Intent.NAVIGATION_START, {"location": "Jollibee", "nearest": False}
    ))
    repeat_response = executor.execute(IntentResult(Intent.NAVIGATION_REPEAT))
    assert repeat_response == start_response


def test_navigation_repeat_returns_last_response_of_any_intent():
    """Repeat isn't limited to navigation instructions — it replays
    whatever the wearable said last, whether that was a time query,
    location lookup, or error message."""
    executor = _make_executor()
    time_response = executor.execute(IntentResult(Intent.SYSTEM_TIME))
    repeat_response = executor.execute(IntentResult(Intent.NAVIGATION_REPEAT))
    assert repeat_response == time_response


def test_consecutive_repeats_stay_stable():
    """Pressing Repeat twice should not chain — both presses should
    return the same original response, not the wearable repeating
    itself repeating itself..."""
    executor = _make_executor()
    executor.execute(IntentResult(Intent.SYSTEM_TIME))
    first_repeat = executor.execute(IntentResult(Intent.NAVIGATION_REPEAT))
    second_repeat = executor.execute(IntentResult(Intent.NAVIGATION_REPEAT))
    assert first_repeat == second_repeat


def test_repeat_reflects_latest_response_not_the_first():
    """When multiple intents have fired, Repeat replays the most
    recent — not the first ever spoken."""
    executor = _make_executor()
    executor.execute(IntentResult(Intent.SYSTEM_TIME))
    location_response = executor.execute(IntentResult(Intent.NAVIGATION_LOCATION))
    repeat_response = executor.execute(IntentResult(Intent.NAVIGATION_REPEAT))
    assert repeat_response == location_response


def test_navigation_location_uses_reverse_geocode():
    executor = _make_executor()
    response = executor.execute(IntentResult(Intent.NAVIGATION_LOCATION))
    assert "You are near" in response or "latitude" in response.lower()


def test_emergency_without_telemetry_acknowledges_locally():
    """When the executor has no telemetry client wired up, the emergency
    handler still returns a sensible message rather than crashing."""
    executor = _make_executor()
    response = executor.execute(IntentResult(Intent.EMERGENCY_TRIGGER))
    assert "emergency" in response.lower() or "guardian" in response.lower()


def test_emergency_with_telemetry_sends_alert():
    telemetry = MockTelemetryClient()
    executor = IntentExecutor(
        router=MockRouter(),
        geocoder=MockGeocoder(),
        gps=_StaticGPS(fix_quality=1),
        telemetry=telemetry,
        device_id="test-device-id",
    )
    executor.execute(IntentResult(Intent.EMERGENCY_TRIGGER))
    assert len(telemetry.alerts) == 1
    alert = telemetry.alerts[0]
    assert alert.event_type is EventType.EMERGENCY_ALERT
    assert alert.device_id == "test-device-id"
    assert alert.latitude == 14.5824       # from _StaticGPS default
    assert alert.longitude == 120.9760


def test_emergency_without_gps_fix_still_sends_alert():
    """Losing GPS is not a reason to swallow an emergency. The alert
    goes out with 0.0/0.0 coordinates; the backend accepts them and the
    guardian sees 'location unknown'."""
    telemetry = MockTelemetryClient()
    executor = IntentExecutor(
        router=MockRouter(),
        geocoder=MockGeocoder(),
        gps=_StaticGPS(fix_quality=0),
        telemetry=telemetry,
        device_id="test-device-id",
    )
    executor.execute(IntentResult(Intent.EMERGENCY_TRIGGER))
    assert len(telemetry.alerts) == 1
    assert telemetry.alerts[0].latitude == 0.0
    assert telemetry.alerts[0].longitude == 0.0


def test_emergency_when_telemetry_send_fails_says_will_retry():
    """When the send returns False (network down, backend rejected), the
    response tells the user we'll keep trying — not that it succeeded."""
    telemetry = MockTelemetryClient(succeed=False)
    executor = IntentExecutor(
        router=MockRouter(),
        geocoder=MockGeocoder(),
        gps=_StaticGPS(fix_quality=1),
        telemetry=telemetry,
        device_id="test-device-id",
    )
    response = executor.execute(IntentResult(Intent.EMERGENCY_TRIGGER))
    assert "could not" in response.lower() or "keep trying" in response.lower()


def test_device_status_gps_with_fix():
    executor = _make_executor(fix_quality=1)
    response = executor.execute(IntentResult(
        Intent.DEVICE_STATUS, {"status_field": "gps"}
    ))
    assert "gps" in response.lower() and "lock" in response.lower()


def test_device_status_gps_without_fix():
    executor = _make_executor(fix_quality=0)
    response = executor.execute(IntentResult(
        Intent.DEVICE_STATUS, {"status_field": "gps"}
    ))
    assert "no fix" in response.lower()


def test_system_time_returns_current_time():
    executor = _make_executor()
    response = executor.execute(IntentResult(Intent.SYSTEM_TIME))
    # response looks like "It's currently 2:34 PM."
    assert "currently" in response.lower()
    assert any(c.isdigit() for c in response)


def test_unknown_intent_asks_user_to_retry():
    executor = _make_executor()
    response = executor.execute(IntentResult(Intent.UNKNOWN))
    assert "didn't understand" in response.lower() or "try again" in response.lower()


# --- candidate ranking reaches the geocoder ---------------------------------
#
# `routing/tests/unit/test_ranking.py` proves the ranking arithmetic. These
# prove the executor actually feeds it — `nearest` was parsed, normalised
# and documented for months while `_handle_navigation_start` never read it.

class _RecordingGeocoder:
    """Records how it was called and returns scripted candidates."""

    def __init__(self, candidates):
        self._candidates = candidates
        self.calls: list[dict] = []

    def geocode(self, query, limit=5, near=None):
        self.calls.append({"query": query, "limit": limit, "near": near})
        return list(self._candidates)

    def reverse(self, coordinate):
        return None


def _candidate(name: str, lat: float, lon: float) -> GeocodingResult:
    return GeocodingResult(
        name=name,
        coordinate=Coordinate(lat=lat, lon=lon),
        country="Philippines",
        city=None,
        feature_type="restaurant",
    )


def test_navigation_start_requests_multiple_candidates():
    """Asking for one result is the bug — you cannot re-rank a list of one."""
    geocoder = _RecordingGeocoder([_candidate("Jollibee", 14.5824, 120.9760)])
    executor = IntentExecutor(
        router=MockRouter(), geocoder=geocoder, gps=_StaticGPS(),
        geocode_candidate_limit=10,
    )

    executor.execute(IntentResult(
        Intent.NAVIGATION_START, {"location": "Jollibee", "nearest": False}
    ))

    assert geocoder.calls[0]["limit"] == 10


def test_navigation_start_passes_the_user_position_as_bias():
    geocoder = _RecordingGeocoder([_candidate("Jollibee", 14.5824, 120.9760)])
    executor = IntentExecutor(
        router=MockRouter(), geocoder=geocoder, gps=_StaticGPS(lat=14.5824, lon=120.9760),
    )

    executor.execute(IntentResult(
        Intent.NAVIGATION_START, {"location": "Jollibee", "nearest": False}
    ))

    assert geocoder.calls[0]["near"] == Coordinate(lat=14.5824, lon=120.9760)


def test_navigation_start_picks_the_nearest_matching_candidate():
    """The Jollibee regression, end to end through the executor."""
    far = _candidate("Jollibee", 11.2444, 125.0048)       # Tacloban
    near = _candidate("Jollibee Manila", 14.5830, 120.9770)
    geocoder = _RecordingGeocoder([far, near])            # geocoder's order: far first
    executor = IntentExecutor(
        router=MockRouter(), geocoder=geocoder, gps=_StaticGPS(lat=14.5824, lon=120.9760),
    )

    response = executor.execute(IntentResult(
        Intent.NAVIGATION_START, {"location": "Jollibee", "nearest": False}
    ))

    assert "Jollibee Manila" in response


def test_nearest_true_overrides_a_better_name_match():
    """`nearest` must change the outcome, or it is still a dead parameter."""
    exact_but_far = _candidate("Pharmacy", 11.2444, 125.0048)
    unnamed_but_close = _candidate("Mercury Drug", 14.5830, 120.9770)
    geocoder = _RecordingGeocoder([exact_but_far, unnamed_but_close])
    executor = IntentExecutor(
        router=MockRouter(), geocoder=geocoder, gps=_StaticGPS(lat=14.5824, lon=120.9760),
    )

    nearest = executor.execute(IntentResult(
        Intent.NAVIGATION_START, {"location": "Pharmacy", "nearest": True}
    ))
    specific = executor.execute(IntentResult(
        Intent.NAVIGATION_START, {"location": "Pharmacy", "nearest": False}
    ))

    assert "Mercury Drug" in nearest
    assert "Pharmacy" in specific


def test_a_missing_nearest_parameter_defaults_to_name_matching():
    """The parser normalises `nearest` in, but a hand-built IntentResult
    (or a future caller) may omit it — that must not raise."""
    geocoder = _RecordingGeocoder([_candidate("Jollibee", 14.5830, 120.9770)])
    executor = IntentExecutor(
        router=MockRouter(), geocoder=geocoder, gps=_StaticGPS(),
    )

    response = executor.execute(IntentResult(
        Intent.NAVIGATION_START, {"location": "Jollibee"}
    ))

    assert "Jollibee" in response


# --- destination confirmation ------------------------------------------------
#
# The executor only decides WHETHER to ask and what to do with the answer.
# Speaking the question and reading the button is `app.py`'s job, injected
# here as a plain callable — see `tests/unit/test_app_confirmation.py`.

class _SpyConfirmer:
    """Records the question it was asked and returns a canned answer."""

    def __init__(self, answer: bool):
        self._answer = answer
        self.questions: list[str] = []

    def __call__(self, question: str) -> bool:
        self.questions.append(question)
        return self._answer


def _confirming_executor(confirmer, candidates=None):
    candidates = candidates or [_candidate("Jollibee Manila", 14.5830, 120.9770)]
    return IntentExecutor(
        router=MockRouter(),
        geocoder=_RecordingGeocoder(candidates),
        gps=_StaticGPS(lat=14.5824, lon=120.9760),
        confirmer=confirmer,
    )


def test_confirmed_destination_starts_navigation():
    confirmer = _SpyConfirmer(answer=True)
    response = _confirming_executor(confirmer).execute(IntentResult(
        Intent.NAVIGATION_START, {"location": "Jollibee", "nearest": False}
    ))

    assert len(confirmer.questions) == 1
    assert "Navigating" in response


def test_a_declined_destination_does_not_navigate():
    confirmer = _SpyConfirmer(answer=False)
    executor = _confirming_executor(confirmer)

    response = executor.execute(IntentResult(
        Intent.NAVIGATION_START, {"location": "Jollibee", "nearest": False}
    ))

    assert "cancelled" in response.lower()
    assert "Navigating" not in response


def test_declining_leaves_no_route_behind():
    """A cancelled confirmation must not arm the navigation monitor, or the
    wearable would start calling out turns to a place the user refused."""
    monitor = NavigationMonitor()
    executor = IntentExecutor(
        router=MockRouter(),
        geocoder=_RecordingGeocoder([_candidate("Jollibee", 14.5830, 120.9770)]),
        gps=_StaticGPS(lat=14.5824, lon=120.9760),
        monitor=monitor,
        confirmer=_SpyConfirmer(answer=False),
    )

    executor.execute(IntentResult(
        Intent.NAVIGATION_START, {"location": "Jollibee", "nearest": False}
    ))

    assert not monitor.is_active()


def test_the_question_names_the_place_the_distance_and_the_button():
    """All three have to be there: the place so a wrong branch is audible,
    the distance because that is what gives it away, and the button because
    the user cannot see which one to press."""
    confirmer = _SpyConfirmer(answer=True)
    _confirming_executor(
        confirmer, [_candidate("Jollibee Manila", 14.5830, 120.9770)],
    ).execute(IntentResult(
        Intent.NAVIGATION_START, {"location": "Jollibee", "nearest": False}
    ))

    question = confirmer.questions[0]
    assert "Jollibee Manila" in question
    assert "meters away" in question
    assert "left button" in question


def test_navigation_without_a_confirmer_behaves_as_before():
    """No confirmation channel must not mean no navigation."""
    response = _confirming_executor(confirmer=None).execute(IntentResult(
        Intent.NAVIGATION_START, {"location": "Jollibee", "nearest": False}
    ))

    assert "Navigating" in response


def test_a_raising_confirmer_is_treated_as_a_decline():
    """It touches audio and GPIO on the voice thread, so it can fail in ways
    the executor cannot interpret. Proceeding on a question the user may
    never have heard is the worse guess."""
    def _broken(question: str) -> bool:
        raise OSError("audio device gone")

    response = _confirming_executor(_broken).execute(IntentResult(
        Intent.NAVIGATION_START, {"location": "Jollibee", "nearest": False}
    ))

    assert "cancelled" in response.lower()


def test_confirmation_is_not_asked_when_nothing_was_found():
    """No point asking the user to approve a destination that doesn't exist."""
    confirmer = _SpyConfirmer(answer=True)
    executor = IntentExecutor(
        router=MockRouter(),
        geocoder=_RecordingGeocoder([]),
        gps=_StaticGPS(),
        confirmer=confirmer,
    )

    executor.execute(IntentResult(
        Intent.NAVIGATION_START, {"location": "Nowhere", "nearest": False}
    ))

    assert confirmer.questions == []


# --- help --------------------------------------------------------------------

def test_help_describes_what_the_wearable_can_do():
    """A user who cannot see a screen cannot read a manual either — this
    response is the only place the capabilities exist in their reach."""
    response = _make_executor().execute(IntentResult(Intent.SYSTEM_HELP))

    assert "IndepenSense" in response
    assert len(response) > 40


def test_help_does_not_depend_on_device_state():
    """"What can you do?" is what a confused user asks. Answering it must
    not depend on whether GPS has a fix."""
    with_gps = _make_executor(fix_quality=1).execute(IntentResult(Intent.SYSTEM_HELP))
    without = _make_executor(fix_quality=0).execute(IntentResult(Intent.SYSTEM_HELP))

    assert with_gps == without


def test_help_answers_in_the_active_language():
    language = LanguageState(default="en", supported=("en", "tl"))
    executor = IntentExecutor(
        router=MockRouter(), geocoder=MockGeocoder(), language=language,
    )

    english = executor.execute(IntentResult(Intent.SYSTEM_HELP))
    language.set("tl")
    tagalog = executor.execute(IntentResult(Intent.SYSTEM_HELP))

    assert english != tagalog


def test_help_can_be_repeated():
    """It is long, and a first-time user will want it twice."""
    executor = _make_executor()
    helped = executor.execute(IntentResult(Intent.SYSTEM_HELP))

    assert executor.execute(IntentResult(Intent.NAVIGATION_REPEAT)) == helped
