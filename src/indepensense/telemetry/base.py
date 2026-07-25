"""Telemetry interfaces — pushing heartbeats and alerts to the guardian backend.

The Pi is one half of a two-repo system; the other half is the NestJS
backend + React frontend in `../IndepenSense`. This module is what talks
to that backend.

Wire format details (JSON keys, event-type strings) are documented in
`nestjs_client.py` — this file only defines the language-side types.
"""
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Protocol


class EventType(Enum):
    """Alert categories accepted by the backend.

    The `.value` of each member is the exact string the backend expects
    in the `eventType` field of the alert payload. Don't rename these
    without also updating the backend's whitelist.
    """
    EMERGENCY_ALERT = "Emergency Alert"
    FALL_DETECTION = "Fall Detection"
    LOW_BATTERY = "Low Battery"
    CONNECTIVITY = "Connectivity"


@dataclass(frozen=True)
class IntervalInformation:
    """One periodic heartbeat sample.

    `battery_health` is an integer 0-100. `latitude`/`longitude` are
    decimal degrees. `created_at` is when the sample was captured on the
    Pi — the server also has its own DB-side timestamp as a fallback.
    """
    device_id: str
    battery_health: int
    internet_status: bool
    latitude: float
    longitude: float
    created_at: datetime


@dataclass(frozen=True)
class AlertEvent:
    """One event alert.

    Fired by the on-device safety and voice-command layers when something
    the guardian should see happens (fall detected, emergency invoked,
    low battery, connectivity change).
    """
    device_id: str
    event_type: EventType
    latitude: float
    longitude: float
    occurred_at: datetime


class TelemetryClient(Protocol):
    def send_heartbeat(self, info: IntervalInformation) -> bool:
        """Post a periodic heartbeat. Returns True on success, False on
        any error (network, HTTP 4xx, HTTP 5xx). Errors are logged to
        stderr by the concrete client — callers use the boolean to
        decide whether to retry or queue."""

    def send_alert(self, event: AlertEvent) -> bool:
        """Post an alert. Same return semantics as `send_heartbeat`."""
