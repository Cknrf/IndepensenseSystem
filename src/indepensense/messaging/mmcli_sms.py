"""SMS via ModemManager's `mmcli`, on the SIM7600G-H.

Why not raw AT commands
-----------------------

The obvious way to send an SMS is `AT+CMGS` over one of the modem's
serial ports (`/dev/ttyUSB2` or `ttyUSB3`, per `docs/sim7600.md`). We
deliberately do not.

A serial port carries a single conversation with no notion of multiple
speakers. ModemManager already owns those ports — it maintains the LTE
data connection, polls signal, and watches for incoming messages. Writing
AT commands into the same port means two programs interleaving on one
channel: replies get read by the wrong listener. The mild failure is our
SMS silently not sending; the severe one is ModemManager losing track of
the modem state and dropping the data connection — killing the internet
the rest of the system depends on, during the emergency that prompted the
SMS in the first place.

So we ask the owner to send it for us. `mmcli` is ModemManager's CLI:
one owner of the port, no contention, and its retry and state handling
comes along for free.

The sequence
------------

Sending is two steps, because ModemManager models an SMS as an object
that is created and then dispatched:

    mmcli -m 0 --messaging-create-sms="text='...',number='+639...'"
      -> /org/freedesktop/ModemManager1/SMS/7      (the new object's path)
    mmcli -m 0 --sms 7 --send
    mmcli -m 0 --messaging-delete-sms=7            (housekeeping)

The modem stores created messages, so skipping the delete slowly fills
its limited SMS memory until creates start failing — which would surface
much later as emergencies silently not being sent.

Prerequisites on the Pi
-----------------------

ModemManager running (stock on Pi OS Trixie), a SIM with an SMS-capable
plan, and the modem registered on the network. `mmcli -m 0` shows
registration state. Note that a *data-only* plan will accept the create
and fail the send.
"""
import re
import shutil
import subprocess
import sys

from indepensense.messaging.base import SMSResult

# Matches the D-Bus object path mmcli prints after a successful create,
# e.g. "Successfully created new SMS: /org/.../SMS/7". We only need the
# trailing index, which is what `--sms N` takes.
_SMS_PATH_RE = re.compile(r"/SMS/(\d+)")


class MMCLISMSSender:
    def __init__(
        self,
        modem_index: int | None = None,
        timeout_s: float = 30.0,
    ):
        """Bind to a modem.

        `modem_index` of None auto-discovers via `mmcli -L`, which is
        correct unless more than one modem is attached. Raises if `mmcli`
        is missing or no modem is present, so a misconfigured device
        fails loudly at startup rather than at the first emergency.
        """
        if shutil.which("mmcli") is None:
            raise RuntimeError(
                "mmcli not found — ModemManager is not installed. "
                "Install with: sudo apt install -y modemmanager"
            )
        self._timeout_s = timeout_s
        self._modem_index = (
            modem_index if modem_index is not None else self._discover_modem()
        )

    def send(self, number: str, text: str) -> SMSResult:
        """Create, send, then delete one message. Never raises."""
        created = self._run(
            [
                f"--messaging-create-sms=text='{self._escape(text)}',number='{number}'",
            ]
        )
        if created is None:
            return SMSResult(number, False, "create failed")

        match = _SMS_PATH_RE.search(created)
        if match is None:
            return SMSResult(number, False, f"could not parse SMS index from: {created!r}")
        index = match.group(1)

        sent = self._run([f"--sms={index}", "--send"])
        # Delete regardless of send outcome — a failed message left in
        # modem storage consumes the same limited space as a sent one.
        self._run([f"--messaging-delete-sms={index}"])

        if sent is None:
            return SMSResult(number, False, "send failed")
        return SMSResult(number, True)

    def close(self) -> None:
        """Nothing to release — each send is its own subprocess."""

    # -------------------------------------------------------------- internals

    @staticmethod
    def _escape(text: str) -> str:
        """Neutralise the single quote that would close mmcli's quoting.

        The message body is built from our own alert text, not user
        input, but an apostrophe in a place name reaching here would
        otherwise mangle the command.
        """
        return text.replace("'", " ")

    def _discover_modem(self) -> int:
        """First modem index reported by `mmcli -L`."""
        try:
            completed = subprocess.run(
                ["mmcli", "-L"],
                capture_output=True,
                text=True,
                timeout=self._timeout_s,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise RuntimeError(f"could not list modems: {exc}") from exc

        match = re.search(r"/Modem/(\d+)", completed.stdout)
        if match is None:
            raise RuntimeError(
                "no modem found via `mmcli -L`. Check the SIM7600 is attached "
                "and ModemManager is running (systemctl status ModemManager)."
            )
        return int(match.group(1))

    def _run(self, args: list[str]) -> str | None:
        """Run one mmcli call. Returns stdout, or None on any failure."""
        command = ["mmcli", "-m", str(self._modem_index), *args]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=self._timeout_s,
            )
        except subprocess.TimeoutExpired:
            print(f"[sms] timed out after {self._timeout_s}s: {args}", file=sys.stderr)
            return None
        except OSError as exc:
            print(f"[sms] could not run mmcli: {exc}", file=sys.stderr)
            return None

        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()[:200]
            print(f"[sms] mmcli failed ({completed.returncode}): {detail}", file=sys.stderr)
            return None
        return completed.stdout
