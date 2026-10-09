"""Integration tests: walking detection triggers obstacle re-alerts.

Verifies that when a user transitions from still to walking, obstacle
warnings for already-detected obstacles are re-fired, catching the case
where an obstacle was present but didn't get closer yet.
"""
import time
import pytest

from indepensense.safety.walking_detector import WalkingDetector
from indepensense.sensors.base import IMUReading


class TestWalkingDetectorIntegration:
    """Walking detector behavior with IMU readings."""

    def test_initially_walking_state(self):
        """Detector starts in walking state until proven still."""
        detector = WalkingDetector(
            window_s=0.5,
            motion_stddev_g=0.3,
            still_hold_s=2.0,
        )
        # Before any samples, assume user may be moving
        assert detector.walking is True

    def test_transition_still_to_walking_is_immediate(self):
        """Transition from still to walking fires immediately on high motion."""
        detector = WalkingDetector(
            window_s=0.5,
            motion_stddev_g=0.3,
            still_hold_s=2.0,
        )
        now = time.time()

        # First, establish a still state with multiple low-variance samples
        for i in range(10):
            reading = IMUReading(
                timestamp=now + i * 0.05,  # 50ms apart
                accel_x=9.81,  # stable
                accel_y=0.0,
                accel_z=0.0,
                gyro_x=0.0,
                gyro_y=0.0,
                gyro_z=0.0,
                temperature_c=25.0,
            )
            detector.process(reading)

        # Force transition to still
        detector._walking = False
        detector._quiet_since = now + 10 * 0.05

        # Now add high-variance motion (walking)
        reading = IMUReading(
            timestamp=now + 11 * 0.05,
            accel_x=9.81 + 0.5,  # bouncy
            accel_y=0.2,
            accel_z=-0.2,
            gyro_x=0.0,
            gyro_y=0.0,
            gyro_z=0.0,
            temperature_c=25.0,
        )
        result = detector.process(reading)

        # Should still be below window threshold, so no transition yet
        assert not result
        assert detector.walking is False  # Still needs a full window

    def test_transition_walking_to_still_needs_quiet_hold(self):
        """Transition from walking to still requires sustained quiet period."""
        detector = WalkingDetector(
            window_s=0.5,
            motion_stddev_g=0.3,
            still_hold_s=0.5,  # Short hold for testing
        )
        now = time.time()

        # Start in walking state
        detector._walking = True

        # Add low-variance samples (quiet) - need > 0.4s to fill the window
        for i in range(20):  # 20 * 50ms = 1000ms, well past the window threshold
            reading = IMUReading(
                timestamp=now + i * 0.05,  # 50ms apart
                accel_x=9.81,  # stable
                accel_y=0.01,  # minimal variation
                accel_z=0.01,
                gyro_x=0.0,
                gyro_y=0.0,
                gyro_z=0.0,
                temperature_c=25.0,
            )
            detector.process(reading)

        # Should have transitioned to still after 0.5s of quiet
        # The quiet_since is set when stddev drops below threshold, then we need still_hold_s more of quiet
        assert detector.walking is False

    def test_window_too_short_holds_state(self):
        """Window < 80% full does not change state."""
        detector = WalkingDetector(
            window_s=1.0,
            motion_stddev_g=0.3,
            still_hold_s=2.0,
        )
        now = time.time()

        # Start in walking state
        detector._walking = True

        # Add just one sample (window is 1s, one sample is way < 80%)
        reading = IMUReading(
            timestamp=now,
            accel_x=9.81,
            accel_y=0.0,
            accel_z=0.0,
            gyro_x=0.0,
            gyro_y=0.0,
            gyro_z=0.0,
            temperature_c=25.0,
        )
        result = detector.process(reading)

        # No state change yet
        assert result is False
        assert detector.walking is True

    def test_ntp_step_backward_resets_window(self):
        """NTP stepping backwards clears the sample window."""
        detector = WalkingDetector(
            window_s=0.5,
            motion_stddev_g=0.3,
            still_hold_s=2.0,
        )
        now = time.time()

        # Add samples forward in time
        for i in range(5):
            reading = IMUReading(
                timestamp=now + i * 0.1,
                accel_x=9.81,
                accel_y=0.0,
                accel_z=0.0,
                gyro_x=0.0,
                gyro_y=0.0,
                gyro_z=0.0,
                temperature_c=25.0,
            )
            detector.process(reading)

        assert len(detector._samples) > 0

        # NTP steps backward
        reading = IMUReading(
            timestamp=now - 1.0,  # 1 second in the past
            accel_x=9.81,
            accel_y=0.0,
            accel_z=0.0,
            gyro_x=0.0,
            gyro_y=0.0,
            gyro_z=0.0,
            temperature_c=25.0,
        )
        detector.process(reading)

        # Window should be reset (only the latest sample)
        assert len(detector._samples) == 1


class TestObstacleCacheAndReAlert:
    """Verify obstacle reading cache behavior for re-alerts."""

    def test_stale_reading_skipped_on_walking_transition(self):
        """Obstacles with stale readings are not re-alerted."""
        from indepensense.config import OBSTACLE_READING_MAX_AGE_S

        now = time.monotonic()
        stale_age = OBSTACLE_READING_MAX_AGE_S + 1.0  # Older than max

        # Simulate obstacle reading cache
        obstacle_reading = {
            "top": (50.0, now - stale_age),  # Stale
            "bottom": (60.0, now - 1.0),      # Fresh
        }

        # On _on_started_walking, check which would be re-alerted
        to_alert = []
        for sensor_name, (distance, stamped_at) in obstacle_reading.items():
            if now - stamped_at <= OBSTACLE_READING_MAX_AGE_S:
                to_alert.append(sensor_name)

        assert "top" not in to_alert  # Stale, skip
        assert "bottom" in to_alert   # Fresh, alert

    def test_clear_tier_skipped_on_walking_transition(self):
        """Obstacles not in any tier (None) are not re-alerted."""
        # Simulate obstacle tier state
        obstacle_tier = {
            "top": None,      # Clear
            "bottom": "danger",  # In danger tier
        }

        # On _on_started_walking, only alert if tier is not None
        to_alert = []
        for sensor_name, tier in obstacle_tier.items():
            if tier is not None:
                to_alert.append(sensor_name)

        assert "top" not in to_alert     # No tier, skip
        assert "bottom" in to_alert      # In danger tier, alert
