"""Mock telemetry client for tests and Mac-side development.

Records every heartbeat and alert to public lists so tests can assert on
what was sent. Never touches the network. The `succeed` flag lets tests
simulate a failing backend (returns False for all sends) to exercise
error paths.
"""
from indepensense.telemetry.base import AlertEvent, IntervalInformation


class MockTelemetryClient:
    def __init__(self, succeed: bool = True) -> None:
        self.heartbeats: list[IntervalInformation] = []
        self.alerts: list[AlertEvent] = []
        self._succeed = succeed

    def send_heartbeat(self, info: IntervalInformation) -> bool:
        self.heartbeats.append(info)
        return self._succeed

    def send_alert(self, event: AlertEvent) -> bool:
        self.alerts.append(event)
        return self._succeed
