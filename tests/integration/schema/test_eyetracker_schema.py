"""EyeTracker CSV schema validation tests.

This module tests the EyeTracker CSV schemas for GAZE, IMU, and EVENTS data,
ensuring data files meet the expected format, including column structure,
data types, and value constraints.
"""

from __future__ import annotations

import pytest

from tests.infrastructure.schemas.csv_schema import (
    EYETRACKER_GAZE_SCHEMA,
    EYETRACKER_IMU_SCHEMA,
    EYETRACKER_EVENTS_SCHEMA,
    validate_csv_file,
)
from tests.infrastructure.fixtures import (
    get_sample_eyetracker_gaze_csv,
    get_sample_eyetracker_imu_csv,
    get_sample_eyetracker_events_csv,
)


class TestEyeTrackerSchema:
    """Tests for EyeTracker CSV schema validation."""

    def test_valid_gaze_csv(self):
        """Test validation of valid EyeTracker GAZE CSV file."""
        csv_path = get_sample_eyetracker_gaze_csv()
        if not csv_path.exists():
            pytest.skip("EyeTracker GAZE sample fixture not found")

        result = validate_csv_file(csv_path, EYETRACKER_GAZE_SCHEMA)
        assert result.is_valid, f"GAZE validation failed: {result.errors}"

    def test_valid_imu_csv(self):
        """Test validation of valid EyeTracker IMU CSV file."""
        csv_path = get_sample_eyetracker_imu_csv()
        if not csv_path.exists():
            pytest.skip("EyeTracker IMU sample fixture not found")

        result = validate_csv_file(csv_path, EYETRACKER_IMU_SCHEMA)
        assert result.is_valid, f"IMU validation failed: {result.errors}"

    def test_valid_events_csv(self):
        """Test validation of valid EyeTracker EVENTS CSV file."""
        csv_path = get_sample_eyetracker_events_csv()
        if not csv_path.exists():
            pytest.skip("EyeTracker EVENTS sample fixture not found")

        result = validate_csv_file(csv_path, EYETRACKER_EVENTS_SCHEMA)
        assert result.is_valid, f"EVENTS validation failed: {result.errors}"

    def test_gaze_column_count(self):
        """Test GAZE has 36 columns."""
        assert EYETRACKER_GAZE_SCHEMA.column_count == 36

    def test_imu_column_count(self):
        """Test IMU has 19 columns."""
        assert EYETRACKER_IMU_SCHEMA.column_count == 19

    def test_events_column_count(self):
        """Test EVENTS has 24 columns."""
        assert EYETRACKER_EVENTS_SCHEMA.column_count == 24
