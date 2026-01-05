"""Comprehensive Data Validation Tests (Super Sanity Test).

This module implements the full data validation test suite as specified in
DATA_VALIDATION_TEST_PLAN.md. It validates:
- CSV schema correctness for all modules
- Timing consistency and synchronization
- Hardware availability detection
- Cross-module data integrity

Usage:
    # Run all tests
    pytest test_data_validation.py -v

    # Run schema tests only
    pytest test_data_validation.py -v -k "schema"

    # Run with hardware tests (requires hardware)
    pytest test_data_validation.py -v --run-hardware

    # Generate report
    python -m rpi_logger.modules.base.tests.test_data_validation --report
"""

from __future__ import annotations

import csv
import os
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Try to import pytest (optional for standalone validation)
try:
    import pytest
    HAS_PYTEST = True
except ImportError:
    HAS_PYTEST = False
    # Stub for pytest.skip when running without pytest
    class _PytestStub:
        @staticmethod
        def skip(reason=""):
            print(f"SKIP: {reason}")
            return
        class mark:
            @staticmethod
            def parametrize(*args, **kwargs):
                def decorator(func):
                    return func
                return decorator
        @staticmethod
        def main(*args, **kwargs):
            print("pytest not installed. Use --report for standalone validation.")
            return 1
    pytest = _PytestStub()

# Import test infrastructure
from .csv_schema import (
    ALL_SCHEMAS,
    CSVSchema,
    ColumnType,
    GPS_SCHEMA,
    DRT_SDRT_SCHEMA,
    DRT_WDRT_SCHEMA,
    VOG_SVOG_SCHEMA,
    VOG_WVOG_SCHEMA,
    EYETRACKER_GAZE_SCHEMA,
    EYETRACKER_IMU_SCHEMA,
    EYETRACKER_EVENTS_SCHEMA,
    NOTES_SCHEMA,
    ValidationResult,
    validate_csv_file,
    validate_header,
    validate_row,
    detect_schema,
)

from .hardware_detection import (
    HardwareAvailability,
    get_hardware_availability,
    requires_hardware,
)

from .fixtures import (
    FIXTURES_DIR,
    get_sample_gps_csv,
    get_sample_drt_sdrt_csv,
    get_sample_drt_wdrt_csv,
    get_sample_vog_svog_csv,
    get_sample_vog_wvog_csv,
    get_sample_eyetracker_gaze_csv,
    get_sample_eyetracker_imu_csv,
    get_sample_eyetracker_events_csv,
    get_sample_notes_csv,
)


# =============================================================================
# Test Configuration
# =============================================================================

def pytest_configure(config):
    """Configure custom pytest markers."""
    config.addinivalue_line(
        "markers", "hardware: mark test as requiring physical hardware"
    )
    config.addinivalue_line(
        "markers", "slow: mark test as slow running"
    )


# =============================================================================
# Schema Validation Tests (P7-E)
# =============================================================================

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
            f.write('1,Notes,notes,,1704456789.123,100.123,,"Test with émojis: 🎉 and quotes: ""test"""\n')
            temp_path = f.name

        try:
            result = validate_csv_file(Path(temp_path), NOTES_SCHEMA)
            assert result.is_valid, f"Unicode content should be valid: {result.errors}"
        finally:
            os.unlink(temp_path)


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


# =============================================================================
# Timing Validation Tests (P7-F)
# =============================================================================

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


# =============================================================================
# Integration Tests (P7-G)
# =============================================================================

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


class TestHardwareDetection:
    """Tests for hardware availability detection."""

    def test_hardware_detection_runs(self):
        """Test hardware detection completes without error."""
        hw = HardwareAvailability()
        hw.detect_all()
        # Should have detected Notes (always available)
        assert hw.is_available("Notes")

    def test_availability_matrix_format(self):
        """Test availability matrix produces valid output."""
        hw = HardwareAvailability()
        hw.detect_all()
        matrix = hw.availability_matrix()

        assert "HARDWARE AVAILABILITY MATRIX" in matrix
        assert "TESTABLE MODULES:" in matrix
        assert "UNTESTABLE MODULES:" in matrix

    def test_notes_always_available(self):
        """Test Notes module is always marked as available."""
        hw = HardwareAvailability()
        hw.detect_all()
        avail = hw.get_availability("Notes")
        assert avail.available
        assert "No hardware required" in avail.reason


# =============================================================================
# Test Reporting (P7-H)
# =============================================================================

@dataclass
class TestReport:
    """Aggregated test report."""
    timestamp: str
    schema_results: Dict[str, ValidationResult] = field(default_factory=dict)
    hardware_matrix: str = ""
    testable_modules: List[str] = field(default_factory=list)
    untestable_modules: List[str] = field(default_factory=list)
    summary: str = ""

    def generate_summary(self) -> str:
        """Generate human-readable summary."""
        lines = [
            "=== DATA VALIDATION TEST REPORT ===",
            f"Date: {self.timestamp}",
            "",
            "SCHEMA VALIDATION:",
        ]

        for name, result in self.schema_results.items():
            status = "PASS" if result.is_valid else "FAIL"
            lines.append(f"  {name}: {status} ({result.row_count} rows, {result.error_count} errors)")

        lines.extend([
            "",
            "HARDWARE MATRIX:",
            self.hardware_matrix,
            "",
            f"TESTABLE MODULES: {', '.join(self.testable_modules) or 'None'}",
            f"UNTESTABLE MODULES: {', '.join(self.untestable_modules) or 'None'}",
        ])

        # Overall status
        all_pass = all(r.is_valid for r in self.schema_results.values())
        overall = "PASS" if all_pass else "FAIL"
        lines.extend([
            "",
            f"OVERALL: {overall}",
        ])

        return "\n".join(lines)


def run_full_validation_report() -> TestReport:
    """Run full validation and generate report."""
    report = TestReport(timestamp=datetime.now().isoformat())

    # Schema validation for all fixtures
    fixtures = [
        ("GPS", GPS_SCHEMA, get_sample_gps_csv()),
        ("DRT_sDRT", DRT_SDRT_SCHEMA, get_sample_drt_sdrt_csv()),
        ("DRT_wDRT", DRT_WDRT_SCHEMA, get_sample_drt_wdrt_csv()),
        ("VOG_sVOG", VOG_SVOG_SCHEMA, get_sample_vog_svog_csv()),
        ("VOG_wVOG", VOG_WVOG_SCHEMA, get_sample_vog_wvog_csv()),
        ("EyeTracker_GAZE", EYETRACKER_GAZE_SCHEMA, get_sample_eyetracker_gaze_csv()),
        ("EyeTracker_IMU", EYETRACKER_IMU_SCHEMA, get_sample_eyetracker_imu_csv()),
        ("EyeTracker_EVENTS", EYETRACKER_EVENTS_SCHEMA, get_sample_eyetracker_events_csv()),
        ("Notes", NOTES_SCHEMA, get_sample_notes_csv()),
    ]

    for name, schema, path in fixtures:
        if path.exists():
            result = validate_csv_file(path, schema)
        else:
            result = ValidationResult(
                schema_name=name,
                file_path=str(path),
                is_valid=False,
                row_count=0,
                errors=[],
            )
        report.schema_results[name] = result

    # Hardware detection
    hw = HardwareAvailability()
    hw.detect_all()
    report.hardware_matrix = hw.availability_matrix()
    report.testable_modules = hw.get_testable_modules()
    report.untestable_modules = hw.get_untestable_modules()

    report.summary = report.generate_summary()
    return report


# =============================================================================
# CLI Entry Point
# =============================================================================

def main():
    """CLI entry point for running validation and generating report."""
    import argparse

    parser = argparse.ArgumentParser(description="Data Validation Test Runner")
    parser.add_argument("--report", action="store_true", help="Generate validation report")
    parser.add_argument("--output", type=str, help="Output file for report")
    args = parser.parse_args()

    if args.report:
        report = run_full_validation_report()
        output = report.summary

        if args.output:
            with open(args.output, 'w') as f:
                f.write(output)
            print(f"Report written to: {args.output}")
        else:
            print(output)
    else:
        # Run pytest
        sys.exit(pytest.main([__file__, "-v"]))


if __name__ == "__main__":
    main()
