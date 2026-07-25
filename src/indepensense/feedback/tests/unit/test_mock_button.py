from indepensense.feedback.mock import MockButton


def test_press_fires_pressed_handler_only():
    events: list[str] = []
    b = MockButton()
    b.on("pressed", lambda: events.append("pressed"))
    b.on("released", lambda: events.append("released"))
    b.press()
    assert events == ["pressed"]


def test_release_fires_released_handler_only():
    events: list[str] = []
    b = MockButton()
    b.on("pressed", lambda: events.append("pressed"))
    b.on("released", lambda: events.append("released"))
    b.release()
    assert events == ["released"]


def test_no_handler_registered_does_not_raise():
    b = MockButton()
    b.press()      # no handler yet
    b.release()    # no handler yet


def test_close_clears_handlers():
    events: list[str] = []
    b = MockButton()
    b.on("pressed", lambda: events.append("pressed"))
    b.close()
    b.press()
    assert events == []


def test_reregister_replaces_previous_handler():
    events: list[str] = []
    b = MockButton()
    b.on("pressed", lambda: events.append("first"))
    b.on("pressed", lambda: events.append("second"))
    b.press()
    assert events == ["second"]
