"""The "let me think" cue must not precede "I need an internet connection".

`cloud.thinking` exists to buy patience for the slowest path the device
has. Playing it and then immediately refusing spends the user's
attention asking them to wait for something that was never going to
arrive — and `OfflineGuard`'s own docstring gives avoiding exactly that
as the reason it checks connectivity up front. The check was there; the
cue just ran first.
"""
import pytest

import indepensense.app as app_module


class Guard:
    """Stands in for `OfflineGuard`, which owns the real decision."""

    def __init__(self, reason):
        self._reason = reason

    def _unavailable_reason(self):
        return self._reason


@pytest.fixture
def app():
    return app_module.App.__new__(app_module.App)


def test_the_cue_is_skipped_when_the_cloud_cannot_answer(app):
    app.cloud = Guard("offline")

    assert app._cloud_is_worth_waiting_for() is False


def test_the_cue_is_skipped_when_the_provider_is_backing_off(app):
    """Also true for a rate limit or a rejected key: the question is not
    going to be answered, so asking for patience is misleading however
    the failure is spoken afterwards."""
    app.cloud = Guard("error")

    assert app._cloud_is_worth_waiting_for() is False


def test_the_cue_plays_when_the_cloud_is_available(app):
    app.cloud = Guard(None)

    assert app._cloud_is_worth_waiting_for() is True


def test_a_provider_without_the_hook_still_gets_its_cue(app):
    """A `CloudAnswerer` is not required to expose this — the protocol in
    `base.py` has one method. An answerer without it is treated as
    available, because the guard still makes the real decision."""
    class Bare:
        def answer(self, question, language, previous=None):
            raise AssertionError("not reached")

    app.cloud = Bare()

    assert app._cloud_is_worth_waiting_for() is True


def test_a_raising_hook_never_costs_the_user_the_cue(app):
    """This decides a cue, not an action. It must not be able to fail the
    utterance around it."""
    class Broken:
        def _unavailable_reason(self):
            raise RuntimeError("boom")

    app.cloud = Broken()

    assert app._cloud_is_worth_waiting_for() is True
