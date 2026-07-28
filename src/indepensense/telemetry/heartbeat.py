"""Periodic heartbeat sender.

Runs a background thread that POSTs an `IntervalInformation` heartbeat
every `interval_s` seconds. Reads current GPS position; falls back to
0.0/0.0 when no fix is available (same policy as the emergency handler
in the intent executor — a "device is alive" heartbeat is more useful
than silence, even when we can't say where the device is).

`battery_health` and `internet_status` are hardcoded to `100` and `True`
for now. Real values will land when:

  - the Waveshare UPS HAT (E) is wired and its INA219 chip is read for
    real battery voltage → percentage
  - connectivity is derived from either a lightweight HTTP HEAD probe
    or the outcome of the previous heartbeat POST

Threading model
---------------

A single background thread runs the loop:

    while not stop:
        info = build current heartbeat
        telemetry.send_heartbeat(info)   # non-blocking with BufferedTelemetryClient
        stop.wait(timeout=interval_s)    # sleep interval or wake early on stop()

The thread is daemon so it doesn't block process exit. `stop()` signals
it and joins with a bounded timeout. `start()` is idempotent — calling
it twice is a no-op.

Observability
-------------

`sent_count` and `failed_count` are public counters that increment as
the loop runs. Useful for thesis-facing charts of connectivity over
time, and for asserting behaviour in unit tests.
"""
import sys
import threading
from datetime import datetime, timezone

from indepensense.power.base import BatteryReader
from indepensense.sensors.base import GPSSensor
from indepensense.telemetry.base import IntervalInformation, TelemetryClient


class PeriodicHeartbeatSender:
    def __init__(
        self,
        telemetry: TelemetryClient,
        gps: GPSSensor | None,
        device_id: str,
        interval_s: float = 30.0,
        battery: BatteryReader | None = None,
    ):
        if interval_s <= 0:
            raise ValueError("interval_s must be > 0")
        self._telemetry = telemetry
        self._gps = gps
        self._battery = battery
        self._device_id = device_id
        self._interval_s = interval_s

        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

        # Observable counters.
        self.sent_count = 0
        self.failed_count = 0

    def start(self) -> None:
        """Start the background heartbeat loop. Idempotent."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="heartbeat-sender",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout_s: float = 5.0) -> None:
        """Signal the loop to exit and wait up to `timeout_s` for it."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout_s)
            self._thread = None

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                info = self._build_current_info()
                success = self._telemetry.send_heartbeat(info)
            except Exception as exc:
                # Never let the loop die from a raising client — a broken
                # telemetry backend or GPS read should not silently take
                # down the whole heartbeat pipeline.
                print(f"[heartbeat] send raised: {exc}", file=sys.stderr)
                self.failed_count += 1
            else:
                if success:
                    self.sent_count += 1
                else:
                    self.failed_count += 1

            # Sleep interval, but wake early if stop() was called.
            self._stop.wait(timeout=self._interval_s)

    def _build_current_info(self) -> IntervalInformation:
        lat, lon = self._read_gps_or_zero()
        return IntervalInformation(
            device_id=self._device_id,
            battery_health=self._read_battery_percent_or_default(),
            internet_status=True,     # TODO: HEAD probe or last-POST outcome
            latitude=lat,
            longitude=lon,
            created_at=datetime.now(timezone.utc),
        )

    def _read_battery_percent_or_default(self) -> int:
        """Read the current battery percentage.

        Returns 100 when no BatteryReader is wired (dev on Mac, HAT not
        installed) so heartbeats still send and the guardian dashboard
        doesn't misread "no reader" as "critical low battery".

        A raising reader is also treated as unknown → 100. The next
        heartbeat will try again.
        """
        if self._battery is None:
            return 100
        try:
            reading = self._battery.read()
        except Exception:
            return 100
        if reading is None:
            return 100
        return max(0, min(100, reading.percentage))

    def _read_gps_or_zero(self) -> tuple[float, float]:
        """Get current lat/lon, or (0.0, 0.0) if GPS is missing or unlocked."""
        if self._gps is None:
            return 0.0, 0.0
        try:
            fix = self._gps.read()
        except Exception:
            # A raising GPS driver shouldn't stop heartbeats. Log-and-swallow.
            return 0.0, 0.0
        if fix is None or fix.fix_quality == 0:
            return 0.0, 0.0
        return fix.lat, fix.lon
