"""Notes CSV schema validation tests.

This module tests the Notes CSV schema to ensure data files meet the expected
format, including column structure, data types, and Unicode content handling.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from tests.infrastructure.schemas.csv_schema import (
    NOTES_SCHEMA,
    validate_csv_file,
)
from tests.infrastructure.fixtures import get_sample_notes_csv


class TestNotesSchema:
    """Tests for Notes CSV schema validation."""

    def test_valid_notes_csv(self):
        """Test validation of valid Notes CSV file."""
        csv_path = get_sample_notes_csv()
        if not csv_path.exists():
            pytest.skip("Notes sample fixture not found")

        result = validate_csv_file(csv_path, NOTES_SCHEMA)
        assert result.is_valid, f"Notes validation failed: {result.errors}"

    def test_notes_column_count(self):
        """Test Notes has 8 columns."""
        assert NOTES_SCHEMA.column_count == 8

    def test_notes_allows_unicode(self):
        """Test Notes content can contain Unicode characters."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, newline='', encoding='utf-8') as f:
            f.write(NOTES_SCHEMA.header_string + "\n")
            # Unicode content with quotes and special characters
            f.write('1,Notes,notes,,1704456789.123,100.123,,"Test with emojis: and quotes: ""test"""\n')
            temp_path = f.name

        try:
            result = validate_csv_file(Path(temp_path), NOTES_SCHEMA)
            assert result.is_valid, f"Unicode content should be valid: {result.errors}"
        finally:
            os.unlink(temp_path)
