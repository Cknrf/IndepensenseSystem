from indepensense.feedback.mock import MockVibrationMotor


def test_on_records_event_and_flips_state():
    m = MockVibrationMotor()
    assert m.is_on is False
    m.on()
    assert m.events == [("on",)]
    assert m.is_on is True


def test_off_records_event_and_clears_state():
    m = MockVibrationMotor()
    m.on()
    m.off()
    assert m.events == [("on",), ("off",)]
    assert m.is_on is False


def test_pulse_records_pattern_arguments():
    m = MockVibrationMotor()
    m.pulse(times=3, duration_s=0.25, gap_s=0.2)
    assert m.events == [("pulse", 3, 0.25, 0.2)]


def test_pulse_defaults_are_captured():
    m = MockVibrationMotor()
    m.pulse()
    assert m.events == [("pulse", 1, 0.2, 0.15)]


def test_close_records_event_and_clears_state():
    m = MockVibrationMotor()
    m.on()
    m.close()
    assert m.events == [("on",), ("close",)]
    assert m.is_on is False


def test_multiple_calls_accumulate_in_order():
    m = MockVibrationMotor()
    m.on()
    m.off()
    m.pulse(2, 0.3, 0.1)
    m.on()
    assert m.events == [
        ("on",),
        ("off",),
        ("pulse", 2, 0.3, 0.1),
        ("on",),
    ]
