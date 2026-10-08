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

    mmcli -m any --messaging-create-sms="text='...',number='+639...'"
      -> /org/freedesktop/ModemManager1/SMS/7      (the new object's path)
    mmcli -m any --sms 7 --send
    mmcli -m any --messaging-delete-sms=7            (housekeeping)

The modem stores created messages, so skipping the delete slowly fills
its limited SMS memory until creates start failing — which would surface
much later as emergencies silently not being sent.

The modem index is not stable
-----------------------------

ModemManager hands out a fresh index every time it enumerates a modem, so
the SIM7600 is `/Modem/0` on one boot and `/Modem/3` after a USB glitch,
a modem reset, or a `systemctl restart ModemManager`. Nothing announces
the change; the old index simply stops existing and every call against it
fails with `error: couldn't find modem`.

Discovering once at construction is therefore not enough. A wearable that
has been up for hours would hold a stale index and fail *every* emergency
SMS for the rest of the session, with the backend alert still succeeding
so nothing else looked wrong — the same shape of silent single-channel
failure that `telemetry/sms_alerts.py` exists to surface.

So `_run` re-binds and retries once when, and only when, mmcli says the
modem is gone. Deliberately reactive rather than polled:

- **No background thread, no periodic probe.** Re-discovery costs nothing
  until something actually fails.
- **One retry per call, never a loop.** If `mmcli -L` finds no modem the
  attempt is abandoned and `send` returns a failed `SMSResult`. A modem
  that has been unplugged produces one extra fast `mmcli -L` per send,
  not a retry storm.
- **Only on a stale-handle error.** A send refused by a data-only plan or
  a modem that is still searching for signal re-binds nothing — those are
  not index problems, and retrying them would turn one honest failure
  into two.
- **Off the main loop.** Every send already runs on the SMS fan-out
  thread, so the extra subprocess cannot touch fall detection latency.

Prerequisites on the Pi
-----------------------

ModemManager running (stock on Pi OS Trixie), a SIM with an SMS-capable
plan, the modem registered on the network, and the polkit rule in
`deploy/polkit/` installed — without it ModemManager refuses every create
from a non-interactive session. `mmcli -m any` shows registration state.
Note that a *data-only* plan will accept the create and fail the send.
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

# What mmcli says when the index no longer resolves to a modem. Matched on
# the message rather than the exit code because mmcli returns 1 for every
# kind of failure, and re-binding on all of them would retry a send the
# carrier deliberately rejected.
_STALE_MODEM_MARKERS = ("couldn't find modem", "cannot find modem")


def _is_stale_modem(detail: str) -> bool:
    """Does this mmcli failure mean our modem index no longer exists?"""
    lowered = detail.lower()
    return any(marker in lowered for marker in _STALE_MODEM_MARKERS)


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
        """Create, send, then delete one message. Never raises.

        `retryable=False` only when ModemManager cannot see a modem at
        all. Everything else — a timeout, a refused send, an unparseable
        reply — might work on the next attempt, and the caller is left
        free to try. See `SMSResult`.
        """
        created, gone = self._run(
            [
                f"--messaging-create-sms=text='{self._escape(text)}',number='{number}'",
            ]
        )
        if created is None:
            return SMSResult(number, False, self._no_modem_detail("create failed", gone),
                             retryable=not gone)

        match = _SMS_PATH_RE.search(created)
        if match is None:
            return SMSResult(number, False, f"could not parse SMS index from: {created!r}")
        index = match.group(1)

        sent, gone = self._run([f"--sms={index}", "--send"])
        # Delete regardless of send outcome — a failed message left in
        # modem storage consumes the same limited space as a sent one.
        self._run([f"--messaging-delete-sms={index}"])

        if sent is None:
            return SMSResult(number, False, self._no_modem_detail("send failed", gone),
                             retryable=not gone)
        return SMSResult(number, True)

    @staticmethod
    def _no_modem_detail(base: str, gone: bool) -> str:
        return f"{base} (no modem)" if gone else base

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

    def _run(self, args: list[str]) -> tuple[str | None, bool]:
        """Run one mmcli call, re-binding once if the index went stale.

        Returns `(stdout or None, modem_is_gone)`. The retry is bounded
        to a single attempt and happens only on a stale-handle error —
        see the module docstring for why it is not a loop and not a poll.

        The second element is the one piece of information no layer above
        can recover: a failed re-discovery means ModemManager sees no
        modem at all, so retrying cannot help. Anything else — a timeout,
        a refusal — is worth another attempt, and the caller decides.
        """
        stdout, detail = self._run_once(args)
        if stdout is not None or not _is_stale_modem(detail):
            return stdout, False

        print(
            f"[sms] modem {self._modem_index} is gone — re-discovering.",
            file=sys.stderr,
        )
        if not self._rebind():
            return None, True

        stdout, _ = self._run_once(args)
        return stdout, False

    def _rebind(self) -> bool:
        """Point this sender at whatever modem ModemManager has now.

        False when there is none, which is the genuinely-unplugged case:
        the caller gives up rather than retrying, so a missing modem costs
        one extra `mmcli -L` per send and nothing more.

        Two overlapping alerts can reach this at once — the emergency
        button is pressable twice. Both would discover the same index and
        write the same value, so the race is harmless and not worth a lock
        on a path that must stay fast during an emergency.
        """
        try:
            self._modem_index = self._discover_modem()
        except RuntimeError as exc:
            print(f"[sms] re-discovery failed: {exc}", file=sys.stderr)
            return False
        print(f"[sms] re-bound to modem {self._modem_index}.", file=sys.stderr)
        return True

    def _run_once(self, args: list[str]) -> tuple[str | None, str]:
        """One mmcli invocation: `(stdout or None, error detail)`.

        Split from `_run` so the retry logic can see *why* a call failed.
        The detail is also what gets logged, so a failure is reported once
        regardless of how many attempts it took.
        """
        command = ["mmcli", "-m", str(self._modem_index), *args]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=self._timeout_s,
            )
        except subprocess.TimeoutExpired:
            detail = f"timed out after {self._timeout_s}s"
            print(f"[sms] {detail}: {args}", file=sys.stderr)
            return None, detail
        except OSError as exc:
            detail = f"could not run mmcli: {exc}"
            print(f"[sms] {detail}", file=sys.stderr)
            return None, detail

        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()[:200]
            print(f"[sms] mmcli failed ({completed.returncode}): {detail}", file=sys.stderr)
            return None, detail
        return completed.stdout, ""
