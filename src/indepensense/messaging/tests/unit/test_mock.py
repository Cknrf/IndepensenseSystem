"""Unit tests for MockSMSSender — the contract callers rely on."""
from indepensense.messaging.mock import MockSMSSender


def test_records_number_and_text():
    sender = MockSMSSender()
    result = sender.send("+639171234567", "hello")

    assert result.sent is True
    assert result.number == "+639171234567"
    assert sender.sent == [("+639171234567", "hello")]


def test_configured_failures_report_without_raising():
    """Senders must never raise — failure is reported in the result so a
    caller can carry on to the next recipient."""
    sender = MockSMSSender(fail_numbers={"+639171234567"})
    result = sender.send("+639171234567", "hello")

    assert result.sent is False
    assert result.detail
    assert sender.sent == []


def test_attempts_records_failures_too():
    """`sent` holds deliveries; `attempts` holds everything tried. The
    difference is what makes partial-delivery assertions possible."""
    sender = MockSMSSender(fail_numbers={"+639171234567"})
    sender.send("+639171234567", "hello")
    sender.send("+639281234567", "hello")

    assert sender.attempts == ["+639171234567", "+639281234567"]
    assert sender.sent == [("+639281234567", "hello")]


def test_close_is_observable():
    sender = MockSMSSender()
    sender.close()
    assert sender.closed is True
