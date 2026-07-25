from indepensense.feedback.mock import MockBuzzer


def test_on_records_event_and_flips_state():
    b = MockBuzzer()
    assert b.is_on is False
    b.on()
    assert b.events == [("on",)]
    assert b.is_on is True


def test_off_records_event_and_clears_state():
    b = MockBuzzer()
    b.on()
    b.off()
    assert b.events == [("on",), ("off",)]
    assert b.is_on is False


def test_beep_records_pattern_arguments():
    b = MockBuzzer()
    b.beep(times=3, duration_s=0.05, gap_s=0.15)
    assert b.events == [("beep", 3, 0.05, 0.15)]


def test_beep_defaults_are_captured():
    b = MockBuzzer()
    b.beep()
    assert b.events == [("beep", 1, 0.1, 0.1)]


def test_close_records_event_and_clears_state():
    b = MockBuzzer()
    b.on()
    b.close()
    assert b.events == [("on",), ("close",)]
    assert b.is_on is False


def test_multiple_calls_accumulate_in_order():
    b = MockBuzzer()
    b.on()
    b.off()
    b.beep(2, 0.2, 0.2)
    b.on()
    assert b.events == [
        ("on",),
        ("off",),
        ("beep", 2, 0.2, 0.2),
        ("on",),
    ]
