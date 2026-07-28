from indepensense.power.mock import MockBatteryReader, make_reading


def test_default_reading_is_full_and_idle():
    r = MockBatteryReader()
    reading = r.read()
    assert reading is not None
    assert reading.percentage == 100
    assert reading.charging_state == "idle"
    assert reading.is_charging is False
    assert reading.is_discharging is False


def test_can_script_a_sequence():
    r = MockBatteryReader(
        readings=[
            make_reading(percentage=80, charging_state="discharging", current_ma=200),
            make_reading(percentage=79, charging_state="discharging", current_ma=200),
            make_reading(percentage=78, charging_state="discharging", current_ma=200),
        ]
    )
    p1 = r.read().percentage
    p2 = r.read().percentage
    p3 = r.read().percentage
    assert (p1, p2, p3) == (80, 79, 78)


def test_sequence_cycles_after_exhaustion():
    r = MockBatteryReader(readings=[make_reading(percentage=50)])
    assert r.read().percentage == 50
    assert r.read().percentage == 50   # loops


def test_none_in_sequence_returns_none():
    r = MockBatteryReader(
        readings=[
            make_reading(percentage=90),
            None,
            make_reading(percentage=88),
        ]
    )
    assert r.read().percentage == 90
    assert r.read() is None
    assert r.read().percentage == 88


def test_is_charging_reflects_state():
    assert make_reading(charging_state="charging").is_charging is True
    assert make_reading(charging_state="fast_charging").is_charging is True
    assert make_reading(charging_state="discharging").is_charging is False
    assert make_reading(charging_state="idle").is_charging is False


def test_critical_low_when_any_cell_below_cutoff_and_not_charging():
    r = make_reading(
        percentage=5,
        cell_voltages_mv=(3200, 3200, 3100, 3200),  # cell 3 below 3150 mV
        current_ma=150,   # discharging
        charging_state="discharging",
    )
    assert r.is_critical_low is True


def test_critical_low_is_false_when_charging_even_if_cell_low():
    r = make_reading(
        percentage=5,
        cell_voltages_mv=(3100, 3100, 3100, 3100),
        current_ma=-500,   # charging
        charging_state="charging",
    )
    assert r.is_critical_low is False


def test_critical_low_is_false_when_all_cells_above_cutoff():
    r = make_reading(
        percentage=20,
        cell_voltages_mv=(3500, 3500, 3500, 3500),
        current_ma=200,
        charging_state="discharging",
    )
    assert r.is_critical_low is False


def test_close_flips_state():
    r = MockBatteryReader()
    assert r.closed is False
    r.close()
    assert r.closed is True
