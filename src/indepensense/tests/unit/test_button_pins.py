"""Pin assignments in `config.py` must match what is physically wired.

This file exists because the emergency and repeat buttons got swapped
twice, in opposite directions, and neither swap was visible to anything.

Commit 88aa4d5, "temporary change the button number", set
`EMERGENCY_BUTTON_GPIO = 25` after the assembled unit turned out to be
wired that way. It was correct. But it was labelled temporary and left
its pin comments saying the old thing, so `config.py` ended up asserting
that GPIO 25 is physical pin 18 — which is simply false, GPIO 25 is pin
22. Five days later an audit read that contradiction as evidence of a
bench hack, found `docs/hardware.md` agreeing with the stale comments,
and "restored" the pair — which would have put the guardian alert on the
left-hand button and the repeat on the front.

What makes this class of bug so quiet is that nothing fails. Both buttons
respond; they just do each other's job. Every other test in the suite
takes the config value as its premise rather than as a claim, so none of
them can see it.

So these tests assert the constants against two things config cannot
define for itself:

  * the **Raspberry Pi 40-pin header**, fixed by the hardware and
    reproduced below. This is what catches a GPIO edited without its pin
    comment — the specific inconsistency that made a correct change look
    like a mistake.
  * the **button table in `docs/hardware.md`**, which `CLAUDE.md` names
    the single source of truth for physical connections — with the caveat,
    earned on 2026-10-07, that the doc has itself been wrong once. When
    the two disagree, the assembled unit decides, not whichever file reads
    more confidently.

The expected values are duplicated here on purpose. A test that imported
them from `config.py` would assert that config equals itself and pass
through any swap; the duplication *is* the check. If the enclosure is
rewired, this file is one of the three places to edit — see the comment
above the constants in `config.py`.
"""
import pytest

from indepensense.config import (
    BUZZER_GPIO,
    EMERGENCY_BUTTON_GPIO,
    PTT_BUTTON_GPIO,
    REPEAT_BUTTON_GPIO,
    VIBRATION_FRONT_GPIO,
    VIBRATION_LEFT_GPIO,
    VIBRATION_RIGHT_GPIO,
)

# BCM number -> physical header pin, for every GPIO this project uses.
# Reproduced from the 40-pin diagram in `docs/hardware.md`, which is in
# turn the Raspberry Pi's own fixed pinout. Not exhaustive: the pins we
# touch are the pins worth guarding.
_BCM_TO_PHYSICAL_PIN = {
    17: 11,
    18: 12,
    27: 13,
    22: 15,
    23: 16,
    24: 18,
    25: 22,
}

# (constant, expected GPIO, physical pin, role) exactly as
# `docs/hardware.md` § "3. Push Buttons" records it. Change this table and
# that table together, never one alone.
#
# Emergency and repeat do not run in enclosure order — the FRONT button is
# on the later pin, 22, and the LEFT button on pin 18. That reads like a
# transcription error and is not one; it is how the harness was routed.
# Verified against the assembled unit, which is the only authority that
# settles it.
_BUTTONS = [
    (PTT_BUTTON_GPIO, 23, 16, "PTT"),
    (EMERGENCY_BUTTON_GPIO, 25, 22, "Emergency"),
    (REPEAT_BUTTON_GPIO, 24, 18, "Repeat"),
]


@pytest.mark.parametrize(
    "configured, expected_gpio, expected_pin, role",
    _BUTTONS,
    ids=[row[3] for row in _BUTTONS],
)
def test_each_button_is_on_the_gpio_hardware_md_records(
    configured, expected_gpio, expected_pin, role,
):
    """The assertion that would have failed on the 2026-10-07 "restore".

    Named per button so a failure says which control is affected rather
    than that "a pin changed" — the whole cost of this bug, both times,
    was not knowing which button was doing what.
    """
    assert configured == expected_gpio, (
        f"{role} is on GPIO {configured}, but this test and "
        f"docs/hardware.md expect GPIO {expected_gpio} (physical pin "
        f"{expected_pin}). One of them is wrong and the wearable is firing "
        f"the wrong handler for a button a blind user is told to press. "
        f"Settle it on the assembled unit — `button_test {expected_gpio}` "
        f"— and not by trusting whichever file reads more confidently; "
        f"both have been wrong once."
    )


@pytest.mark.parametrize(
    "configured, expected_gpio, expected_pin, role",
    _BUTTONS,
    ids=[row[3] for row in _BUTTONS],
)
def test_each_button_gpio_matches_its_documented_pin(
    configured, expected_gpio, expected_pin, role,
):
    """GPIO and physical pin must describe the same hole in the header.

    Unlike the GPIO itself, this is not a wiring question with two
    defensible answers — it is arithmetic off the header diagram, and a
    mismatch is always an error.

    It is the check that would have saved five days. 88aa4d5 made the
    right change to `EMERGENCY_BUTTON_GPIO` and left it sitting under the
    comment `physical pin 18`. GPIO 25 is pin 22, so the file now stated
    something false, and that falsehood is what later made a correct value
    look like a bench hack worth reverting.
    """
    assert _BCM_TO_PHYSICAL_PIN[configured] == expected_pin, (
        f"{role}: GPIO {configured} is physical pin "
        f"{_BCM_TO_PHYSICAL_PIN[configured]}, not pin {expected_pin}. "
        f"A GPIO was changed without its pin comment."
    )


def test_the_three_buttons_are_on_distinct_pins():
    """Two buttons sharing a GPIO is one button and one dead control.

    Cheap to assert and impossible to see by reading three lines that each
    look fine on their own — which is exactly how the swap survived review.
    """
    gpios = [PTT_BUTTON_GPIO, EMERGENCY_BUTTON_GPIO, REPEAT_BUTTON_GPIO]
    assert len(set(gpios)) == len(gpios), f"duplicate button GPIO in {gpios}"


def test_no_output_device_shares_a_pin_with_a_button():
    """An input and an output on one pin is a control that fights an actuator.

    The buzzer and the three motors are driven; the buttons are read. A
    collision would mean a press pulling against a transistor base, or the
    emergency buzzer re-triggering its own button.
    """
    inputs = {PTT_BUTTON_GPIO, EMERGENCY_BUTTON_GPIO, REPEAT_BUTTON_GPIO}
    outputs = {
        BUZZER_GPIO,
        VIBRATION_FRONT_GPIO,
        VIBRATION_RIGHT_GPIO,
        VIBRATION_LEFT_GPIO,
    }
    assert not inputs & outputs, (
        f"GPIO {sorted(inputs & outputs)} is wired as both an input and an "
        f"output"
    )


def test_every_output_device_is_on_a_distinct_pin():
    outputs = [
        BUZZER_GPIO,
        VIBRATION_FRONT_GPIO,
        VIBRATION_RIGHT_GPIO,
        VIBRATION_LEFT_GPIO,
    ]
    assert len(set(outputs)) == len(outputs), f"duplicate output GPIO in {outputs}"
