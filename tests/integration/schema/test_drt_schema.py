"""DRT CSV schema validation tests.

This module tests the DRT (Detection Response Task) CSV schemas for both
sDRT (simple) and wDRT (wireless) variants, ensuring data files meet the
expected format, including column structure, data types, and value constraints.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from tests.infrastructure.schemas.csv_schema import (
    DRT_SDRT_SCHEMA,
    DRT_WDRT_SCHEMA,
    validate_csv_file,
)
from tests.infrastructure.fixtures import (
    get_sample_drt_sdrt_csv,
    get_sample_drt_wdrt_csv,
)


class TestDRTSchema:
    """Tests for DRT CSV schema validation."""

    def test_valid_sdrt_csv(self):
        """Test validation of valid sDRT CSV file."""
        csv_path = get_sample_drt_sdrt_csv()
        if not csv_path.exists():
            pytest.skip("DRT sDRT sample fixture not found")

        result = validate_csv_file(csv_path, DRT_SDRT_SCHEMA)
        assert result.is_valid, f"sDRT validation failed: {result.errors}"

    def test_valid_wdrt_csv(self):
        """Test validation of valid wDRT CSV file."""
        csv_path = get_sample_drt_wdrt_csv()
        if not csv_path.exists():
            pytest.skip("DRT wDRT sample fixture not found")

        result = validate_csv_file(csv_path, DRT_WDRT_SCHEMA)
        assert result.is_valid, f"wDRT validation failed: {result.errors}"

    def test_sdrt_column_count(self):
        """Test sDRT has 10 columns."""
        assert DRT_SDRT_SCHEMA.column_count == 10

    def test_wdrt_column_count(self):
        """Test wDRT has 11 columns."""
        assert DRT_WDRT_SCHEMA.column_count == 11

    def test_reaction_time_allows_negative_one(self):
        """Test that reaction_time_ms allows -1 for timeouts."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, newline='') as f:
            f.write(DRT_SDRT_SCHEMA.header_string + "\n")
            # -1 is valid for timeout
            f.write("1,DRT,test,,1704456789.123,100.123,12345,,0,-1\n")
            temp_path = f.name

        try:
            result = validate_csv_file(Path(temp_path), DRT_SDRT_SCHEMA)
            assert result.is_valid, f"Timeout value -1 should be valid: {result.errors}"
        finally:
            os.unlink(temp_path)

    def test_battery_percent_range(self):
        """Test wDRT battery_percent must be 0-100."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, newline='') as f:
            f.write(DRT_WDRT_SCHEMA.header_string + "\n")
            # Invalid battery (101%)
            f.write("1,DRT,test,,1704456789.123,100.123,12345,1704456789,1,250,101\n")
            temp_path = f.name

        try:
            result = validate_csv_file(Path(temp_path), DRT_WDRT_SCHEMA)
            assert not result.is_valid
            assert any("battery_percent" in str(e) for e in result.errors)
        finally:
            os.unlink(temp_path)
