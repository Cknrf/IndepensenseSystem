"""Manual hardware test: send one real SMS through the SIM7600.

Costs money and reaches a real phone — pass the number explicitly, there
is no default.

    python -m indepensense.messaging.tests.manual.send_sms_test --number +639171234567

To send what a real emergency would say, so you can judge the wording and
check the map link opens correctly on the guardian's phone:

    python -m indepensense.messaging.tests.manual.send_sms_test \\
        --number +639171234567 --emergency-preview

Prerequisites
-------------

    sudo apt install -y modemmanager
    mmcli -L                  # should list the SIM7600
    mmcli -m 0                # 'state: registered' before SMS will work

The SIM must have an SMS-capable plan. A *data-only* plan will accept the
create step and fail the send — if that happens, the failure is the plan,
not this code. Confirm by sending a text from the same SIM in a phone.

What to check afterwards
-----------------------

The message arrives, the sender ID looks right, and the map link opens to
the expected location. Also re-run `mmcli -m 0 --messaging-list-sms` — it
should be empty, because the driver deletes each message after sending.
A growing list there means modem storage is filling up and will
eventually make sends fail.
"""
import argparse
from datetime import datetime, timezone

from indepensense.config import (
    SMS_MODEM_INDEX,
    SMS_SEND_TIMEOUT_S,
)
from indepensense.messaging.mmcli_sms import MMCLISMSSender
from indepensense.telemetry.base import AlertEvent, EventType
from indepensense.telemetry.sms_alerts import compose_alert_sms

# Rizal Park, Manila — a recognisable spot so the map link is obviously
# right or obviously wrong when it opens.
_PREVIEW_LAT = 14.5824
_PREVIEW_LON = 120.9760


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--number", required=True, help="recipient in E.164 form, e.g. +639171234567")
    ap.add_argument(
        "--emergency-preview",
        action="store_true",
        help="send the exact text a real emergency alert would produce",
    )
    ap.add_argument("--text", default="IndepenSense SMS test. No action needed.")
    args = ap.parse_args()

    if args.emergency_preview:
        text = compose_alert_sms(
            AlertEvent(
                device_id="preview",   # local only; never sent
                event_type=EventType.EMERGENCY_ALERT,
                latitude=_PREVIEW_LAT,
                longitude=_PREVIEW_LON,
                occurred_at=datetime.now(timezone.utc),
            )
        )
    else:
        text = args.text

    print(f"Opening modem (index {SMS_MODEM_INDEX or 'auto-discover'})...")
    sender = MMCLISMSSender(modem_index=SMS_MODEM_INDEX, timeout_s=SMS_SEND_TIMEOUT_S)

    print(f"Sending to {args.number}:")
    print(f"  {text}")
    print(f"  ({len(text)} chars — over 160 splits into multiple parts)")

    try:
        result = sender.send(args.number, text)
    finally:
        sender.close()

    if result.sent:
        print("\nSent. Check the handset — delivery can take a few seconds.")
    else:
        print(f"\nFAILED: {result.detail}")
        print("Check `mmcli -m 0` shows 'state: registered', and that the")
        print("SIM's plan actually permits sending SMS.")


if __name__ == "__main__":
    main()
