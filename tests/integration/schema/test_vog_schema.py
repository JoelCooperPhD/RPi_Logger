"""VOG CSV schema validation tests.

This module tests the VOG (Video Oculography) CSV schemas for both
sVOG (simple) and wVOG (wireless) variants, ensuring data files meet the
expected format, including column structure, data types, and value constraints.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from tests.infrastructure.schemas.csv_schema import (
    VOG_SVOG_SCHEMA,
    VOG_WVOG_SCHEMA,
    validate_csv_file,
)
from tests.infrastructure.fixtures import (
    get_sample_vog_svog_csv,
    get_sample_vog_wvog_csv,
)


class TestVOGSchema:
    """Tests for VOG CSV schema validation."""

    def test_valid_svog_csv(self):
        """Test validation of valid sVOG CSV file."""
        csv_path = get_sample_vog_svog_csv()
        if not csv_path.exists():
            pytest.skip("VOG sVOG sample fixture not found")

        result = validate_csv_file(csv_path, VOG_SVOG_SCHEMA)
        assert result.is_valid, f"sVOG validation failed: {result.errors}"

    def test_valid_wvog_csv(self):
        """Test validation of valid wVOG CSV file."""
        csv_path = get_sample_vog_wvog_csv()
        if not csv_path.exists():
            pytest.skip("VOG wVOG sample fixture not found")

        result = validate_csv_file(csv_path, VOG_WVOG_SCHEMA)
        assert result.is_valid, f"wVOG validation failed: {result.errors}"

    def test_svog_column_count(self):
        """Test sVOG has 8 columns."""
        assert VOG_SVOG_SCHEMA.column_count == 8

    def test_wvog_column_count(self):
        """Test wVOG has 11 columns."""
        assert VOG_WVOG_SCHEMA.column_count == 11

    def test_wvog_lens_values(self):
        """Test wVOG lens must be A, B, or X."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, newline='') as f:
            f.write(VOG_WVOG_SCHEMA.header_string + "\n")
            # Invalid lens value
            f.write("1,VOG,test,,1704456789.123,100.123,1500,1500,3000,Z,90\n")
            temp_path = f.name

        try:
            result = validate_csv_file(Path(temp_path), VOG_WVOG_SCHEMA)
            assert not result.is_valid
            assert any("lens" in str(e) for e in result.errors)
        finally:
            os.unlink(temp_path)
