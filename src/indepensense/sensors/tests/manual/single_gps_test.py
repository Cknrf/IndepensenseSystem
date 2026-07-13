"""Manual hardware test: stream GPS fixes from the SIM7600G-H.

Requires the external GNSS antenna to be connected to the dongle's `GPS` SMA
port, and GPS to be enabled on the modem first. To enable GPS one time:

    sudo apt install -y minicom
    sudo minicom -D /dev/ttyUSB2 -b 115200
    # then type:  AT+CGPS=1<enter>
    # confirm reply: OK
    # Ctrl-A then X to exit

After that, NMEA sentences stream on /dev/ttyUSB1.

Run from repo root with:
    python -m indepensense.sensors.tests.manual.single_gps_test

Ctrl-C to stop. A cold start with a fresh position can take 30-60 seconds
outdoors — indoors the fix may never lock, which is normal for GPS.
"""
import time

from indepensense.config import SIM7600_GPS_PORT
from indepensense.sensors.gps import SIM7600GPS


def main():
    gps = SIM7600GPS(port=SIM7600_GPS_PORT)
    print(f"Reading GPS on {SIM7600_GPS_PORT}. Ctrl-C to stop.")
    print("(Waiting for first fix — this can take a minute outdoors.)")
    try:
        while True:
            fix = gps.read()
            if fix is not None:
                lat_str = f"{fix.lat:+.6f}"
                lon_str = f"{fix.lon:+.6f}"
                alt_str = f"{fix.altitude_m:.1f} m" if fix.altitude_m is not None else "-"
                sats_str = str(fix.satellites) if fix.satellites is not None else "-"
                hdop_str = f"{fix.hdop:.1f}" if fix.hdop is not None else "-"
                print(
                    f"fix: {lat_str}, {lon_str} | "
                    f"alt {alt_str} | sats {sats_str} | hdop {hdop_str} | "
                    f"quality {fix.fix_quality} | utc {fix.utc_time}"
                )
            else:
                print("no fix yet")
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        gps.close()


if __name__ == "__main__":
    main()
