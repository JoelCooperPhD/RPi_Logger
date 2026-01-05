"""Schema detection tests.

This module tests the automatic schema detection functionality that identifies
which CSV schema applies to a given data file based on its header and content.
"""

from __future__ import annotations

import pytest

from tests.infrastructure.schemas.csv_schema import detect_schema
from tests.infrastructure.fixtures import (
    get_sample_gps_csv,
    get_sample_notes_csv,
)


class TestSchemaDetection:
    """Tests for automatic schema detection."""

    def test_detect_gps_schema(self):
        """Test GPS schema is correctly detected."""
        csv_path = get_sample_gps_csv()
        if not csv_path.exists():
            pytest.skip("GPS sample fixture not found")

        detected = detect_schema(csv_path)
        assert detected is not None
        assert detected.name == "GPS"

    def test_detect_notes_schema(self):
        """Test Notes schema is correctly detected."""
        csv_path = get_sample_notes_csv()
        if not csv_path.exists():
            pytest.skip("Notes sample fixture not found")

        detected = detect_schema(csv_path)
        assert detected is not None
        assert detected.name == "Notes"
