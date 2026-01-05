"""Integration test fixtures for multi-component testing.

This conftest provides fixtures specifically for integration tests that:
- Test interactions between multiple components
- Validate CSV output against schemas
- Test data flow through the system

Fixtures in this file complement (not duplicate) the root conftest.py fixtures.
The root conftest provides:
- project_root, test_data_dir
- sample CSV path fixtures (sample_gps_csv, etc.)
- Basic mock device fixtures

This file provides:
- Schema validation fixtures
- CSV test data loaders
- Integration test markers
- Multi-component test helpers
"""

from __future__ import annotations

import csv
import tempfile
from pathlib import Path
from typing import Any, Callable, Dict, Generator, List, Optional, Union

import pytest


# =============================================================================
# Schema Fixtures
# =============================================================================

@pytest.fixture(scope="session")
def gps_schema():
    """Provide GPS CSV schema for validation.

    Scope: session (loaded once, shared across all tests)

    Returns:
        CSVSchema instance for GPS data

    Example:
        def test_gps_output_valid(gps_schema, output_csv):
            result = validate_csv_file(output_csv, gps_schema)
            assert result.is_valid
    """
    from tests.infrastructure.schemas.csv_schema import GPS_SCHEMA
    return GPS_SCHEMA


@pytest.fixture(scope="session")
def drt_sdrt_schema():
    """Provide sDRT CSV schema for validation.

    Scope: session

    Returns:
        CSVSchema instance for sDRT data
    """
    from tests.infrastructure.schemas.csv_schema import DRT_SDRT_SCHEMA
    return DRT_SDRT_SCHEMA


@pytest.fixture(scope="session")
def drt_wdrt_schema():
    """Provide wDRT CSV schema for validation.

    Scope: session

    Returns:
        CSVSchema instance for wDRT data
    """
    from tests.infrastructure.schemas.csv_schema import DRT_WDRT_SCHEMA
    return DRT_WDRT_SCHEMA


@pytest.fixture(scope="session")
def vog_svog_schema():
    """Provide sVOG CSV schema for validation.

    Scope: session

    Returns:
        CSVSchema instance for sVOG data
    """
    from tests.infrastructure.schemas.csv_schema import VOG_SVOG_SCHEMA
    return VOG_SVOG_SCHEMA


@pytest.fixture(scope="session")
def vog_wvog_schema():
    """Provide wVOG CSV schema for validation.

    Scope: session

    Returns:
        CSVSchema instance for wVOG data
    """
    from tests.infrastructure.schemas.csv_schema import VOG_WVOG_SCHEMA
    return VOG_WVOG_SCHEMA


@pytest.fixture(scope="session")
def eyetracker_gaze_schema():
    """Provide EyeTracker GAZE CSV schema for validation.

    Scope: session

    Returns:
        CSVSchema instance for gaze data
    """
    from tests.infrastructure.schemas.csv_schema import EYETRACKER_GAZE_SCHEMA
    return EYETRACKER_GAZE_SCHEMA


@pytest.fixture(scope="session")
def eyetracker_imu_schema():
    """Provide EyeTracker IMU CSV schema for validation.

    Scope: session

    Returns:
        CSVSchema instance for IMU data
    """
    from tests.infrastructure.schemas.csv_schema import EYETRACKER_IMU_SCHEMA
    return EYETRACKER_IMU_SCHEMA


@pytest.fixture(scope="session")
def eyetracker_events_schema():
    """Provide EyeTracker EVENTS CSV schema for validation.

    Scope: session

    Returns:
        CSVSchema instance for eye events data
    """
    from tests.infrastructure.schemas.csv_schema import EYETRACKER_EVENTS_SCHEMA
    return EYETRACKER_EVENTS_SCHEMA


@pytest.fixture(scope="session")
def notes_schema():
    """Provide Notes CSV schema for validation.

    Scope: session

    Returns:
        CSVSchema instance for notes data
    """
    from tests.infrastructure.schemas.csv_schema import NOTES_SCHEMA
    return NOTES_SCHEMA


@pytest.fixture(scope="session")
def all_schemas() -> Dict[str, Any]:
    """Provide all CSV schemas as a dictionary.

    Scope: session

    Returns:
        Dictionary mapping schema names to CSVSchema instances

    Example:
        def test_schema_coverage(all_schemas):
            assert "GPS" in all_schemas
            assert len(all_schemas) >= 9  # All module schemas
    """
    from tests.infrastructure.schemas.csv_schema import ALL_SCHEMAS
    return ALL_SCHEMAS


@pytest.fixture(scope="session")
def module_schemas() -> Dict[str, List[Any]]:
    """Provide module-to-schemas mapping.

    Scope: session

    Returns:
        Dictionary mapping module names to lists of applicable schemas

    Example:
        def test_drt_has_two_schemas(module_schemas):
            assert len(module_schemas["DRT"]) == 2  # sDRT and wDRT
    """
    from tests.infrastructure.schemas.csv_schema import MODULE_SCHEMAS
    return MODULE_SCHEMAS


# =============================================================================
# CSV Data Fixtures
# =============================================================================

@pytest.fixture(scope="session")
def csv_fixtures_dir(test_data_dir) -> Path:
    """Provide path to CSV fixture files directory.

    Scope: session

    Args:
        test_data_dir: Root test data directory from root conftest

    Returns:
        Path to the fixtures directory containing sample CSVs
    """
    # test_data_dir already points to infrastructure/fixtures
    return test_data_dir


@pytest.fixture(scope="function")
def load_csv_data() -> Callable[[Path], List[Dict[str, str]]]:
    """Provide a function to load CSV data as list of dictionaries.

    Scope: function

    Returns:
        Function that loads CSV file and returns rows as dicts

    Example:
        def test_csv_content(load_csv_data, sample_gps_csv):
            rows = load_csv_data(sample_gps_csv)
            assert len(rows) > 0
            assert "latitude_deg" in rows[0]
    """
    def loader(csv_path: Path) -> List[Dict[str, str]]:
        """Load CSV file and return rows as dictionaries."""
        with open(csv_path, "r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            return list(reader)

    return loader


@pytest.fixture(scope="function")
def write_test_csv(tmp_path: Path) -> Callable[..., Path]:
    """Provide a function to write test CSV files.

    Scope: function

    Args:
        tmp_path: Temporary directory for test files

    Returns:
        Function that writes CSV data and returns the file path

    Example:
        def test_csv_processing(write_test_csv):
            csv_path = write_test_csv(
                filename="test.csv",
                header=["col1", "col2"],
                rows=[["a", "b"], ["c", "d"]]
            )
            # Process csv_path...
    """
    def writer(
        filename: str,
        header: List[str],
        rows: List[List[str]],
        subdir: Optional[str] = None,
    ) -> Path:
        """Write a test CSV file and return its path."""
        if subdir:
            output_dir = tmp_path / subdir
            output_dir.mkdir(parents=True, exist_ok=True)
        else:
            output_dir = tmp_path

        csv_path = output_dir / filename

        with open(csv_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(header)
            writer.writerows(rows)

        return csv_path

    return writer


@pytest.fixture(scope="function")
def sample_csv_with_schema(write_test_csv) -> Callable[..., Path]:
    """Provide a function to create sample CSVs matching a schema.

    Scope: function

    Args:
        write_test_csv: CSV writer fixture

    Returns:
        Function that creates schema-compliant CSV files

    Example:
        def test_schema_validation(sample_csv_with_schema, gps_schema):
            csv_path = sample_csv_with_schema(
                schema=gps_schema,
                row_count=10
            )
            result = validate_csv_file(csv_path, gps_schema)
            assert result.is_valid
    """
    import time

    def create_sample(
        schema: Any,
        row_count: int = 5,
        filename: Optional[str] = None,
    ) -> Path:
        """Create a sample CSV file matching the given schema."""
        if filename is None:
            filename = f"sample_{schema.name.lower()}.csv"

        header = schema.header

        # Generate sample rows with valid data
        rows = []
        base_time = time.time()

        for i in range(row_count):
            row = []
            for col in schema.columns:
                value = _generate_sample_value(col, i, base_time)
                row.append(str(value))
            rows.append(row)

        return write_test_csv(filename=filename, header=header, rows=rows)

    return create_sample


def _generate_sample_value(col_spec: Any, row_index: int, base_time: float) -> Any:
    """Generate a sample value for a column specification.

    Internal helper for sample_csv_with_schema fixture.
    """
    from tests.infrastructure.schemas.csv_schema import ColumnType

    name = col_spec.name
    dtype = col_spec.dtype

    # Handle standard prefix columns
    if name == "trial":
        return row_index + 1
    elif name == "module":
        return "TestModule"
    elif name == "device_id":
        return "test_device_0"
    elif name == "label":
        return "test"
    elif name == "record_time_unix":
        return base_time + row_index * 0.1
    elif name == "record_time_mono":
        return row_index * 0.1

    # Generate type-appropriate values
    if dtype == ColumnType.INT:
        if col_spec.min_value is not None and col_spec.max_value is not None:
            return int((col_spec.min_value + col_spec.max_value) / 2)
        elif col_spec.min_value is not None:
            return int(col_spec.min_value) + row_index
        return row_index

    elif dtype == ColumnType.FLOAT:
        if col_spec.min_value is not None and col_spec.max_value is not None:
            return (col_spec.min_value + col_spec.max_value) / 2
        elif col_spec.min_value is not None:
            return col_spec.min_value + row_index * 0.1
        return float(row_index)

    elif dtype == ColumnType.BOOL_INT:
        return row_index % 2

    elif dtype == ColumnType.TIMESTAMP_UNIX:
        return base_time + row_index

    elif dtype == ColumnType.TIMESTAMP_MONO:
        return row_index * 0.1

    elif dtype == ColumnType.TIMESTAMP_NS:
        return int((base_time + row_index) * 1e9)

    elif dtype == ColumnType.ISO_DATETIME:
        from datetime import datetime, timezone
        dt = datetime.fromtimestamp(base_time + row_index, tz=timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%S")

    elif dtype == ColumnType.STRING:
        if col_spec.allowed_values:
            return col_spec.allowed_values[row_index % len(col_spec.allowed_values)]
        return f"value_{row_index}"

    return ""


# =============================================================================
# Validation Fixtures
# =============================================================================

@pytest.fixture(scope="function")
def validate_csv() -> Callable[..., Any]:
    """Provide CSV validation function.

    Scope: function

    Returns:
        Function to validate CSV files against schemas

    Example:
        def test_output_valid(validate_csv, gps_schema, output_file):
            result = validate_csv(output_file, gps_schema)
            assert result.is_valid, f"Errors: {result.errors}"
    """
    from tests.infrastructure.schemas.csv_schema import validate_csv_file

    def validator(
        file_path: Union[str, Path],
        schema: Any,
        max_errors: int = 100,
    ) -> Any:
        """Validate a CSV file against a schema."""
        return validate_csv_file(file_path, schema, max_errors)

    return validator


@pytest.fixture(scope="function")
def detect_csv_schema() -> Callable[[Union[str, Path]], Optional[Any]]:
    """Provide CSV schema detection function.

    Scope: function

    Returns:
        Function to auto-detect schema from CSV header

    Example:
        def test_schema_detection(detect_csv_schema, sample_gps_csv):
            schema = detect_csv_schema(sample_gps_csv)
            assert schema is not None
            assert schema.name == "GPS"
    """
    from tests.infrastructure.schemas.csv_schema import detect_schema
    return detect_schema


# =============================================================================
# Integration Test Markers
# =============================================================================

@pytest.fixture(scope="session")
def integration_markers():
    """Provide integration test marker utilities.

    Scope: session

    Returns:
        Dictionary of marker helper functions

    Example:
        def test_with_markers(integration_markers):
            if integration_markers["is_schema_test"](test_name):
                # Handle schema-specific logic
                pass
    """
    def is_schema_test(name: str) -> bool:
        """Check if a test is a schema validation test."""
        return "schema" in name.lower()

    def is_data_flow_test(name: str) -> bool:
        """Check if a test is a data flow test."""
        return "flow" in name.lower() or "pipeline" in name.lower()

    def is_timing_test(name: str) -> bool:
        """Check if a test is a timing validation test."""
        return "timing" in name.lower() or "monotonic" in name.lower()

    return {
        "is_schema_test": is_schema_test,
        "is_data_flow_test": is_data_flow_test,
        "is_timing_test": is_timing_test,
    }


# =============================================================================
# Timing Validation Fixtures
# =============================================================================

@pytest.fixture(scope="function")
def timing_validator() -> Callable[[List[Dict[str, str]]], List[str]]:
    """Provide timing validation function for CSV rows.

    Validates that monotonic timestamps are strictly increasing.

    Scope: function

    Returns:
        Function that validates timing and returns list of errors

    Example:
        def test_timing_monotonic(timing_validator, load_csv_data, sample_gps_csv):
            rows = load_csv_data(sample_gps_csv)
            errors = timing_validator(rows)
            assert len(errors) == 0, f"Timing errors: {errors}"
    """
    def validator(
        rows: List[Dict[str, str]],
        time_column: str = "record_time_mono",
    ) -> List[str]:
        """Validate that timestamps are monotonically increasing."""
        errors = []
        prev_time: Optional[float] = None

        for i, row in enumerate(rows, start=1):
            if time_column not in row:
                errors.append(f"Row {i}: Missing {time_column} column")
                continue

            try:
                current_time = float(row[time_column])
            except (ValueError, TypeError):
                errors.append(f"Row {i}: Invalid {time_column} value: {row[time_column]}")
                continue

            if prev_time is not None and current_time < prev_time:
                errors.append(
                    f"Row {i}: Time travel detected - {time_column} decreased "
                    f"from {prev_time} to {current_time}"
                )

            prev_time = current_time

        return errors

    return validator


# =============================================================================
# Standard Prefix Validation Fixtures
# =============================================================================

@pytest.fixture(scope="session")
def standard_prefix_columns() -> List[str]:
    """Provide list of standard 6-column prefix names.

    Scope: session

    Returns:
        List of column names in the standard prefix

    Example:
        def test_has_standard_prefix(standard_prefix_columns, csv_header):
            for col in standard_prefix_columns:
                assert col in csv_header
    """
    return [
        "trial",
        "module",
        "device_id",
        "label",
        "record_time_unix",
        "record_time_mono",
    ]


@pytest.fixture(scope="function")
def validate_standard_prefix() -> Callable[[List[str]], List[str]]:
    """Provide function to validate standard CSV prefix columns.

    Scope: function

    Returns:
        Function that validates header has correct standard prefix

    Example:
        def test_header_valid(validate_standard_prefix):
            header = ["trial", "module", "device_id", "label", "record_time_unix", "record_time_mono", "extra"]
            errors = validate_standard_prefix(header)
            assert len(errors) == 0
    """
    expected_prefix = [
        "trial",
        "module",
        "device_id",
        "label",
        "record_time_unix",
        "record_time_mono",
    ]

    def validator(header: List[str]) -> List[str]:
        """Validate that header starts with standard prefix."""
        errors = []

        if len(header) < len(expected_prefix):
            errors.append(
                f"Header too short: expected at least {len(expected_prefix)} columns, "
                f"got {len(header)}"
            )
            return errors

        for i, (actual, expected) in enumerate(zip(header, expected_prefix)):
            if actual != expected:
                errors.append(
                    f"Column {i}: expected '{expected}', got '{actual}'"
                )

        return errors

    return validator
