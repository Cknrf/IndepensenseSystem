"""The verification tool must configure the magnetometer like the runtime.

`single_magnetometer_test` is what the calibration is checked against by
eye, at the four cardinals, before `COMPASS_CALIBRATED` is set. If it
builds the driver differently from `App._try_open_magnetometer`, the
check passes on one configuration and the wearable ships another.

That happened: `heading_offset_deg` was added to the driver and wired
into `app.py` but not into the verification tool, so for a while the tool
displayed headings without the mount correction the runtime applies —
about 12° out on this build, and invisible unless you knew to look.

The calibration tools are deliberately NOT included here. They read the
sensor raw, because they exist to produce the numbers the runtime applies
— feeding those same numbers back in would calibrate an already
calibrated reading.
"""
import inspect

from indepensense import app as app_module
from indepensense.sensors.tests.manual import single_magnetometer_test

# Everything `App` passes that changes what a reading means.
_CALIBRATION_ARGUMENTS = (
    "offset_x", "offset_y", "offset_z",
    "scale_x", "scale_y", "scale_z",
    "forward_axis", "left_axis",
    "heading_offset_deg",
)

_CALIBRATION_TOOLS = (
    "magnetometer_calibrate",
    "magnetometer_swing",
    "magnetometer_axes",
    "magnetometer_stability",
)


def _construction_source(source: str) -> str:
    """The text of the `QMC5883P(...)` call in `source`."""
    start = source.index("QMC5883P(")
    depth = 0
    for index in range(start, len(source)):
        if source[index] == "(":
            depth += 1
        elif source[index] == ")":
            depth -= 1
            if depth == 0:
                return source[start:index + 1]
    raise AssertionError("unbalanced QMC5883P( call")


def test_the_verification_tool_matches_the_runtime():
    runtime = _construction_source(
        inspect.getsource(app_module.App._try_open_magnetometer)
    )
    tool = _construction_source(inspect.getsource(single_magnetometer_test))

    for argument in _CALIBRATION_ARGUMENTS:
        assert argument in runtime, f"App stopped passing {argument}"
        assert argument in tool, (
            f"single_magnetometer_test does not pass {argument}, so it "
            "verifies a different configuration from the one that ships"
        )


def test_the_calibration_tools_read_raw():
    """They measure what the correction should be, so applying the
    correction first would fold the answer into its own input."""
    import importlib

    for name in _CALIBRATION_TOOLS:
        module = importlib.import_module(
            f"indepensense.sensors.tests.manual.{name}"
        )
        call = _construction_source(inspect.getsource(module))
        for argument in ("offset_x", "scale_x", "heading_offset_deg"):
            assert argument not in call, (
                f"{name} applies {argument} to readings it is supposed to "
                "be measuring uncorrected"
            )
