"""Timing validation tests for CSV data.

This module tests timing consistency and synchronization across CSV data,
including monotonic time validation and the standard 6-column prefix that
all module CSVs must have.
"""

from __future__ import annotations

import csv

import pytest

from tests.infrastructure.schemas.csv_schema import (
    ALL_SCHEMAS,
    CSVSchema,
    ColumnType,
)
from tests.infrastructure.fixtures import (
    get_sample_gps_csv,
    get_sample_drt_sdrt_csv,
    get_sample_vog_svog_csv,
    get_sample_notes_csv,
)


class TestStandardPrefix:
    """Tests for the standard 6-column prefix."""

    @pytest.mark.parametrize("schema_name,schema", list(ALL_SCHEMAS.items()))
    def test_all_schemas_have_standard_prefix(self, schema_name: str, schema: CSVSchema):
        """Test all schemas start with the standard 6-column prefix."""
        expected_prefix = ["trial", "module", "device_id", "label", "record_time_unix", "record_time_mono"]
        actual_prefix = schema.header[:6]
        assert actual_prefix == expected_prefix, f"{schema_name} does not have standard prefix"

    @pytest.mark.parametrize("schema_name,schema", list(ALL_SCHEMAS.items()))
    def test_trial_is_positive_integer(self, schema_name: str, schema: CSVSchema):
        """Test trial column requires positive integer."""
        trial_col = schema.get_column("trial")
        assert trial_col is not None
        assert trial_col.dtype == ColumnType.INT
        assert trial_col.min_value == 1


class TestTimingValidation:
    """Tests for timing consistency and synchronization."""

    def test_monotonic_time_increasing(self):
        """Test that record_time_mono is strictly increasing."""
        csv_path = get_sample_gps_csv()
        if not csv_path.exists():
            pytest.skip("GPS sample fixture not found")

        with open(csv_path, 'r', newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            prev_mono = None
            for row_num, row in enumerate(reader, start=2):
                mono_time = float(row['record_time_mono'])
                if prev_mono is not None:
                    assert mono_time > prev_mono, f"Row {row_num}: monotonic time decreased"
                prev_mono = mono_time

    def test_unix_mono_alignment(self):
        """Test that unix and monotonic times are aligned."""
        csv_path = get_sample_gps_csv()
        if not csv_path.exists():
            pytest.skip("GPS sample fixture not found")

        with open(csv_path, 'r', newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        if len(rows) < 2:
            pytest.skip("Not enough rows for alignment test")

        first_unix = float(rows[0]['record_time_unix'])
        first_mono = float(rows[0]['record_time_mono'])
        last_unix = float(rows[-1]['record_time_unix'])
        last_mono = float(rows[-1]['record_time_mono'])

        unix_delta = last_unix - first_unix
        mono_delta = last_mono - first_mono

        # Allow 1% drift or 0.1 second, whichever is larger
        max_drift = max(unix_delta * 0.01, 0.1)
        actual_drift = abs(unix_delta - mono_delta)
        assert actual_drift < max_drift, f"Time drift too large: {actual_drift}s"

    def test_no_time_travel(self):
        """Test for no backwards jumps in timestamps."""
        for fixture_getter in [
            get_sample_gps_csv,
            get_sample_drt_sdrt_csv,
            get_sample_vog_svog_csv,
            get_sample_notes_csv,
        ]:
            csv_path = fixture_getter()
            if not csv_path.exists():
                continue

            with open(csv_path, 'r', newline='', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                prev_mono = None
                for row_num, row in enumerate(reader, start=2):
                    mono_str = row.get('record_time_mono', '')
                    if mono_str:
                        mono_time = float(mono_str)
                        if prev_mono is not None:
                            assert mono_time >= prev_mono, (
                                f"{csv_path.name} row {row_num}: time travel detected"
                            )
                        prev_mono = mono_time
