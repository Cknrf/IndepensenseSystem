from indepensense.sensors.dyp_a22 import parse_dyp_frame


def test_parses_500mm_frame():
    # 500 mm -> high=0x01, low=0xF4, checksum=(0xFF+0x01+0xF4)&0xFF=0xF4
    assert parse_dyp_frame(b"\xff\x01\xf4\xf4") == 50.0


def test_parses_1500mm_frame():
    # 1500 mm -> high=0x05, low=0xDC, checksum=(0xFF+0x05+0xDC)&0xFF=0xE0
    assert parse_dyp_frame(b"\xff\x05\xdc\xe0") == 150.0


def test_returns_none_on_bad_header():
    assert parse_dyp_frame(b"\xfe\x01\xf4\xf4") is None


def test_returns_none_on_bad_checksum():
    assert parse_dyp_frame(b"\xff\x01\xf4\x00") is None


def test_returns_none_on_out_of_range_zero():
    # 0 mm means "out of range" per the sensor protocol
    assert parse_dyp_frame(b"\xff\x00\x00\xff") is None


def test_returns_none_on_short_frame():
    assert parse_dyp_frame(b"\xff\x01\xf4") is None
