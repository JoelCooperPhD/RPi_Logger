"""Test helpers for Logger test suite.

Provides assertion helpers and test data generators for use in tests.
These utilities simplify common testing patterns and ensure consistent
test data generation.

Assertion Helpers:
    assert_csv_valid - Validate CSV file against schema
    assert_timing_monotonic - Check timestamps are increasing
    assert_no_time_travel - Verify no backward time jumps
    assert_csv_row_count - Check CSV row count constraints
    assert_column_values - Validate column value constraints

Data Generators:
    generate_nmea_sentence - Generate valid NMEA sentences
    generate_csv_row - Generate valid CSV rows
    generate_csv_rows - Generate multiple CSV rows
    generate_mock_device_response - Generate device responses
    generate_mock_command_response - Generate command responses
    generate_gps_track - Generate GPS track data

Exception Classes:
    CSVValidationError - Raised when CSV validation fails
    TimingValidationError - Raised when timing validation fails

Usage:
    from tests.infrastructure.helpers import (
        assert_csv_valid,
        assert_timing_monotonic,
        generate_nmea_sentence,
        generate_csv_row,
    )

    # Validate a CSV file
    result = assert_csv_valid('/path/to/data.csv', GPS_SCHEMA)

    # Generate test data
    nmea = generate_nmea_sentence(lat=48.1173, lon=11.5167)
    row = generate_csv_row(GPS_SCHEMA, trial=1)
"""

from pathlib import Path

# Assertion helpers
from tests.infrastructure.helpers.assertions import (
    CSVValidationError,
    TimingValidationError,
    assert_csv_valid,
    assert_timing_monotonic,
    assert_no_time_travel,
    assert_csv_row_count,
    assert_column_values,
)

# Data generators
from tests.infrastructure.helpers.generators import (
    generate_nmea_sentence,
    generate_csv_row,
    generate_csv_rows,
    generate_mock_device_response,
    generate_mock_command_response,
    generate_gps_track,
)

HELPERS_DIR = Path(__file__).parent

__all__ = [
    # Exception classes
    "CSVValidationError",
    "TimingValidationError",
    # Assertion helpers
    "assert_csv_valid",
    "assert_timing_monotonic",
    "assert_no_time_travel",
    "assert_csv_row_count",
    "assert_column_values",
    # Data generators
    "generate_nmea_sentence",
    "generate_csv_row",
    "generate_csv_rows",
    "generate_mock_device_response",
    "generate_mock_command_response",
    "generate_gps_track",
    # Constants
    "HELPERS_DIR",
]
