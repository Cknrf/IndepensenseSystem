"""Manual hardware test: make the SIM7600G-H start its GPS by itself.

`AT+CGPS=1` turns the GNSS receiver on, and it is a *runtime* setting —
it does not survive a modem power cycle. This modem power-cycles more
than you would like: a dmesg two seconds apart shows it drop
`ttyUSB2`-`ttyUSB5` and return as `ttyUSB0`-`ttyUSB4`, and ModemManager's
index walked 8 -> 4 in an hour. Every one of those resets leaves the NMEA
port perfectly openable and streaming nothing, which reads as "GPS has no
fix" and is really "GPS is switched off".

`AT+CGPSAUTO=1` is the fix and it is one command. It writes to the
modem's non-volatile memory, so GNSS starts whenever the modem does, with
no host involvement at all. Nothing in the runtime has to know.

    python -m indepensense.sensors.tests.manual.gps_autostart          # show state
    python -m indepensense.sensors.tests.manual.gps_autostart --enable # set it

Two warnings before you run this
--------------------------------

**Your SSH session probably goes over this modem.** `ip route` shows one
default route, via `wwan0`. Nothing here resets the modem, so the link
should hold — but if you follow up by power-cycling the modem to verify
persistence, you will disconnect yourself. Verify with a Pi reboot
instead, or from a directly attached keyboard.

**ModemManager owns one of the AT ports.** The SIM7600 exposes two
(interfaces 2 and 3); this tries both and uses whichever answers. If both
are busy, stop ModemManager first — but that drops `wwan0`, so see above.
"""
import argparse
import glob
import sys
import time

# Interfaces 2 and 3 are the AT command ports on this module's USB
# composition. Addressed by interface rather than by `ttyUSBn` for the
# reason this whole file exists — see `config.SIM7600_GPS_PORT`.
_AT_PORT_GLOB = "/dev/serial/by-id/usb-SimTech*-if0[23]-port0"

_REPLY_TIMEOUT_S = 3.0


def _send(ser, command: str) -> str:
    """Write one AT command and return everything the modem says back.

    Reads until the modem goes quiet rather than until a fixed marker:
    `AT+CGPSAUTO?` answers with its value *and* an `OK` on separate
    lines, and stopping at the first line would drop the value.
    """
    ser.reset_input_buffer()
    ser.write((command + "\r\n").encode())
    ser.flush()

    deadline = time.monotonic() + _REPLY_TIMEOUT_S
    chunks: list[str] = []
    while time.monotonic() < deadline:
        waiting = ser.in_waiting
        if waiting:
            chunks.append(ser.read(waiting).decode(errors="replace"))
            deadline = time.monotonic() + 0.3      # quiet period ends the reply
        else:
            time.sleep(0.05)
    return "".join(chunks).strip()


def _open_at_port():
    """Open whichever AT port is free. Returns (serial, path) or (None, why)."""
    # Glob before importing pyserial. "The modem is not plugged in" is the
    # common failure and deserves the clear message; an ImportError on a
    # machine with no serial stack would bury it under a traceback.
    candidates = sorted(glob.glob(_AT_PORT_GLOB))
    if not candidates:
        return None, (
            "no AT port found. The modem is not on the USB bus — check "
            "`lsusb | grep -i sim` and `dmesg | tail`, because a dongle that "
            "failed to enumerate cannot be configured."
        )

    import serial  # lazy: only resolvable on the Pi

    for path in candidates:
        try:
            ser = serial.Serial(path, baudrate=115200, timeout=1.0)
        except Exception as exc:
            print(f"  {path.rsplit('-', 2)[-2]}: busy or unusable ({exc})")
            continue
        # An unsolicited `AT` is the cheapest proof the port is a real AT
        # interface and not, say, the diagnostic one.
        if "OK" in _send(ser, "AT"):
            return ser, path
        print(f"  {path.rsplit('-', 2)[-2]}: opened but did not answer AT")
        ser.close()

    return None, (
        "every AT port was busy or silent. ModemManager holds one of them; "
        "if both are taken, `sudo systemctl stop ModemManager` first — note "
        "that drops the cellular data connection."
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Show or set GNSS auto-start on the SIM7600G-H.")
    parser.add_argument("--enable", action="store_true",
                        help="set AT+CGPSAUTO=1 (persists in modem NVRAM)")
    args = parser.parse_args(argv)

    print("Opening an AT port...")
    ser, path_or_reason = _open_at_port()
    if ser is None:
        print(f"\n{path_or_reason}", file=sys.stderr)
        return 1

    try:
        print(f"Using {path_or_reason}\n")
        print(f"  GPS running now   : {_send(ser, 'AT+CGPS?')!r}")
        print(f"  auto-start setting: {_send(ser, 'AT+CGPSAUTO?')!r}")

        if not args.enable:
            print("\nRe-run with --enable to set auto-start.")
            return 0

        print(f"\n  AT+CGPSAUTO=1 -> {_send(ser, 'AT+CGPSAUTO=1')!r}")
        print(f"  AT+CGPS=1     -> {_send(ser, 'AT+CGPS=1')!r}   (on, now)")
        print(f"\n  auto-start setting: {_send(ser, 'AT+CGPSAUTO?')!r}")
        print(
            "\nExpect `+CGPSAUTO: 1`. If it still reads 0, this firmware "
            "spells the command differently — check the SIMCom AT manual for "
            "your revision rather than assuming it worked."
        )
        print(
            "\nTo prove it persists, reboot the Pi (NOT just the modem, which "
            "would drop the SSH session this is probably running over) and "
            "then run single_gps_test without touching AT+CGPS at all."
        )
        return 0
    finally:
        ser.close()


if __name__ == "__main__":
    raise SystemExit(main())
