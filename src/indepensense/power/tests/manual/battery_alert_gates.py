"""Why did the low-battery warning not fire?

    python -m indepensense.power.tests.manual.battery_alert_gates

`single_ups_test` shows what the pack is doing. This shows what
`App._check_battery_and_alert` *decides*, which is a different question
and the one that matters when a warning is missing.

It exists because a bench test sat at a reported 30%, then 27%, with no
warning and nothing in the journal to say why — the alert has four
independent gates and a silent device looks identical whichever one is
closed:

  1. the percentage is still above the threshold
  2. the pack is not reported as discharging
  3. the latch is already set from an earlier run
  4. the HAT cannot be read at all

Prints each one with the value behind it, so the answer is read rather
than inferred. Safe to run while the app is running — this only reads.
"""
import sys

from indepensense.config import (
    BATTERY_EMPTY_RAW_PERCENT,
    CRITICAL_BATTERY_PERCENT,
    CRITICAL_BATTERY_RECOVERY_PERCENT,
    CRITICAL_BATTERY_STATE_PATH,
    LOW_BATTERY_PERCENT,
    LOW_BATTERY_RECOVERY_PERCENT,
    LOW_BATTERY_STATE_PATH,
    UPS_HAT_I2C_BUS,
)
from indepensense.power.waveshare_ups_e import WaveshareUPSHatE


def _tier(name, pct, fire, recovery, latch_path, discharging, extra_fire=False):
    latched = latch_path.exists()
    print(f"\n  {name}")
    print(f"    reported {pct}%   fires at or below {fire}%   clears at {recovery}%")

    if latched:
        print(f"    LATCH SET  — {latch_path}")
        if pct >= recovery:
            print(f"    -> would CLEAR now ({pct} >= {recovery})")
        else:
            print(f"    -> SUPPRESSED. Nothing will fire until the pack is "
                  f"back above {recovery}%.")
            print(f"       Delete the file to re-arm:  rm {latch_path}")
        return

    print(f"    latch clear ({latch_path.name} absent)")
    below = pct <= fire
    print(f"    at/below threshold? {below}   ({pct} <= {fire})")
    if not extra_fire:
        print(f"    discharging?       {discharging}")
    if (below and discharging) or extra_fire:
        print("    -> WOULD FIRE")
    elif not below:
        print(f"    -> silent: still above {fire}%.")
    else:
        print("    -> silent: below the threshold, but not reported as "
              "discharging. On mains, or the gauge says 'idle'.")


def main() -> int:
    try:
        ups = WaveshareUPSHatE(
            bus_number=UPS_HAT_I2C_BUS,
            empty_raw_percent=BATTERY_EMPTY_RAW_PERCENT,
        )
    except Exception as exc:
        print(f"Could not open the UPS HAT: {exc}", file=sys.stderr)
        print("Gate 4 is closed — the app logs '[battery] read error' and "
              "returns, so no tier is ever evaluated.", file=sys.stderr)
        return 1

    reading = ups.read()
    if reading is None:
        print("The HAT returned nothing (I2C read failed).", file=sys.stderr)
        print("The app treats this the same way: return, no alert.",
              file=sys.stderr)
        return 1

    print("Battery")
    print(f"    raw gauge        {reading.raw_percentage}%")
    print(f"    reported         {reading.percentage}%   "
          f"(floor against BATTERY_EMPTY_RAW_PERCENT={BATTERY_EMPTY_RAW_PERCENT})")
    print(f"    charging_state   {reading.charging_state!r}")
    print(f"    is_discharging   {reading.is_discharging}   "
          f"(True only for exactly 'discharging')")
    print(f"    current          {reading.current_ma} mA")
    print(f"    pack voltage     {reading.voltage_mv} mV")
    print(f"    cells            "
          f"{', '.join(f'{mv} mV' for mv in reading.cell_voltages_mv)}")
    print(f"    is_critical_low  {reading.is_critical_low}   "
          f"(any cell under the BMS cutoff, and not charging)")

    if not reading.is_discharging:
        print(f"\n  NOTE: charging_state is {reading.charging_state!r}, not "
              f"'discharging'.")
        print("  The LOW tier requires `is_discharging`, so it cannot fire in "
              "this state")
        print("  however low the pack gets. Unplug from mains and re-run. If "
              "it still")
        print("  says 'idle' on battery power, the gauge is the problem, not "
              "the threshold.")

    _tier("LOW", reading.percentage, LOW_BATTERY_PERCENT,
          LOW_BATTERY_RECOVERY_PERCENT, LOW_BATTERY_STATE_PATH,
          reading.is_discharging)

    # The critical tier answers to two signals: the corrected percentage
    # and a cell under the BMS cutoff. Either fires it, so a low cell
    # fires it regardless of what the gauge claims.
    _tier("CRITICAL", reading.percentage, CRITICAL_BATTERY_PERCENT,
          CRITICAL_BATTERY_RECOVERY_PERCENT, CRITICAL_BATTERY_STATE_PATH,
          reading.is_discharging, extra_fire=reading.is_critical_low)
    if reading.is_critical_low:
        print("    (is_critical_low is set — a cell is under the BMS cutoff, "
              "which fires")
        print("     the critical tier on its own, without the percentage.)")

    ups.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
