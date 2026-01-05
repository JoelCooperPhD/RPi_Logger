"""GPS CSV schema validation tests.

This module tests the GPS CSV schema to ensure data files meet the expected
format, including column structure, data types, and value constraints.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from tests.infrastructure.schemas.csv_schema import (
    GPS_SCHEMA,
    validate_csv_file,
)
from tests.infrastructure.fixtures import get_sample_gps_csv


class TestGPSSchema:
    """Tests for GPS CSV schema validation."""

    def test_valid_gps_csv(self):
        """Test validation of valid GPS CSV file."""
        csv_path = get_sample_gps_csv()
        if not csv_path.exists():
            pytest.skip("GPS sample fixture not found")

        result = validate_csv_file(csv_path, GPS_SCHEMA)
        assert result.is_valid, f"GPS validation failed: {result.errors}"
        assert result.row_count > 0

    def test_gps_header_validation(self):
        """Test GPS header matches expected schema."""
        header = GPS_SCHEMA.header
        assert len(header) == 26
        assert header[0] == "trial"
        assert header[5] == "record_time_mono"
        assert header[-1] == "raw_sentence"

    def test_gps_latitude_range(self):
        """Test GPS latitude validation rejects out-of-range values."""
        # Create a temporary CSV with invalid latitude
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, newline='') as f:
            f.write(GPS_SCHEMA.header_string + "\n")
            # Invalid latitude (91 degrees)
            f.write("1,GPS,test,,1704456789.123,100.123,,1704456789.0,91.0,11.5,500,5.0,18.0,10.0,11.5,85.0,1,A,1,8,12,0.9,1.3,1.1,GGA,raw\n")
            temp_path = f.name

        try:
            result = validate_csv_file(Path(temp_path), GPS_SCHEMA)
            assert not result.is_valid
            assert any("latitude_deg" in str(e) for e in result.errors)
        finally:
            os.unlink(temp_path)

    def test_gps_fix_valid_boolean(self):
        """Test GPS fix_valid must be 0 or 1."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, newline='') as f:
            f.write(GPS_SCHEMA.header_string + "\n")
            # Invalid fix_valid (2 instead of 0 or 1)
            f.write("1,GPS,test,,1704456789.123,100.123,,1704456789.0,48.0,11.5,500,5.0,18.0,10.0,11.5,85.0,1,A,2,8,12,0.9,1.3,1.1,GGA,raw\n")
            temp_path = f.name

        try:
            result = validate_csv_file(Path(temp_path), GPS_SCHEMA)
            assert not result.is_valid
            assert any("fix_valid" in str(e) for e in result.errors)
        finally:
            os.unlink(temp_path)
