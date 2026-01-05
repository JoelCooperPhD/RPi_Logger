"""Custom assertion helpers for Logger test suite.

Provides assertion functions for validating CSV files, timing consistency,
and data integrity. These helpers simplify common validation patterns in tests.

Usage:
    from tests.infrastructure.helpers import assert_csv_valid, assert_timing_monotonic

    def test_gps_output():
        assert_csv_valid(csv_path, GPS_SCHEMA)
        assert_timing_monotonic(csv_path)
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

from tests.infrastructure.schemas.csv_schema import (
    CSVSchema,
    ValidationResult,
    validate_csv_file,
)


class CSVValidationError(AssertionError):
    """Raised when CSV validation fails.

    Attributes:
        result: The ValidationResult containing details about failures.
        path: Path to the CSV file that failed validation.
    """

    def __init__(self, message: str, result: ValidationResult, path: Path):
        """Initialize CSVValidationError.

        Args:
            message: Human-readable error message.
            result: The ValidationResult from validation.
            path: Path to the CSV file.
        """
        super().__init__(message)
        self.result = result
        self.path = path


class TimingValidationError(AssertionError):
    """Raised when timing validation fails.

    Attributes:
        path: Path to the CSV file that failed validation.
        row: Row number where the timing issue was detected.
        details: Additional details about the timing issue.
    """

    def __init__(self, message: str, path: Path, row: int, details: Optional[Dict] = None):
        """Initialize TimingValidationError.

        Args:
            message: Human-readable error message.
            path: Path to the CSV file.
            row: Row number where the issue was detected.
            details: Optional dictionary with additional details.
        """
        super().__init__(message)
        self.path = path
        self.row = row
        self.details = details or {}


def assert_csv_valid(
    path: Union[str, Path],
    schema: CSVSchema,
    max_errors: int = 100,
    allow_empty: bool = False,
) -> ValidationResult:
    """Assert that a CSV file is valid according to a schema.

    Validates the CSV file against the provided schema and raises an assertion
    error if validation fails. Returns the ValidationResult on success for
    further inspection if needed.

    Args:
        path: Path to the CSV file to validate.
        schema: CSVSchema to validate against.
        max_errors: Maximum number of errors to collect before stopping.
        allow_empty: If True, allow empty files (no data rows). Default False.

    Returns:
        ValidationResult containing validation details.

    Raises:
        CSVValidationError: If the CSV file fails validation.
        FileNotFoundError: If the CSV file does not exist.

    Example:
        >>> from tests.infrastructure.schemas.csv_schema import GPS_SCHEMA
        >>> result = assert_csv_valid('/path/to/gps.csv', GPS_SCHEMA)
        >>> print(f"Validated {result.row_count} rows")
    """
    path = Path(path)

    if not path.exists():
        raise FileNotFoundError(f"CSV file not found: {path}")

    result = validate_csv_file(path, schema, max_errors=max_errors)

    if not result.is_valid:
        # Build a detailed error message
        error_lines = [f"CSV validation failed for {path.name} against {schema.name} schema"]
        error_lines.append(f"Rows validated: {result.row_count}")
        error_lines.append(f"Errors: {result.error_count}, Warnings: {result.warning_count}")

        if result.errors:
            error_lines.append("\nFirst 10 errors:")
            for error in result.errors[:10]:
                error_lines.append(f"  - {error}")

        if result.warnings:
            error_lines.append(f"\nFirst 5 warnings:")
            for warning in result.warnings[:5]:
                error_lines.append(f"  - {warning}")

        raise CSVValidationError("\n".join(error_lines), result, path)

    if not allow_empty and result.row_count == 0:
        raise CSVValidationError(
            f"CSV file {path.name} has no data rows",
            result,
            path,
        )

    return result


def assert_timing_monotonic(
    csv_path: Union[str, Path],
    time_column: str = "record_time_mono",
    strict: bool = True,
) -> List[Tuple[int, float]]:
    """Assert that timestamps in a CSV file are monotonically increasing.

    Validates that each timestamp is greater than (or greater than or equal to,
    if strict=False) the previous timestamp.

    Args:
        csv_path: Path to the CSV file to validate.
        time_column: Name of the timestamp column to check. Default "record_time_mono".
        strict: If True, require strictly increasing (>). If False, allow equal (>=).

    Returns:
        List of (row_number, timestamp) tuples for all validated rows.

    Raises:
        TimingValidationError: If timestamps are not monotonically increasing.
        FileNotFoundError: If the CSV file does not exist.
        KeyError: If the time column does not exist in the CSV.

    Example:
        >>> timestamps = assert_timing_monotonic('/path/to/gps.csv')
        >>> print(f"Validated {len(timestamps)} timestamps")
    """
    csv_path = Path(csv_path)

    if not csv_path.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")

    timestamps: List[Tuple[int, float]] = []
    prev_time: Optional[float] = None
    prev_row: Optional[int] = None

    with open(csv_path, 'r', newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)

        if time_column not in (reader.fieldnames or []):
            raise KeyError(f"Column '{time_column}' not found in CSV. Available columns: {reader.fieldnames}")

        for row_num, row in enumerate(reader, start=2):  # Row 1 is header
            time_str = row.get(time_column, '').strip()

            if not time_str:
                continue  # Skip empty values

            try:
                current_time = float(time_str)
            except ValueError:
                raise TimingValidationError(
                    f"Invalid timestamp value '{time_str}' at row {row_num}",
                    csv_path,
                    row_num,
                    {"value": time_str, "column": time_column},
                )

            timestamps.append((row_num, current_time))

            if prev_time is not None:
                if strict:
                    if current_time <= prev_time:
                        raise TimingValidationError(
                            f"Monotonic time violation at row {row_num}: "
                            f"{current_time} <= {prev_time} (previous at row {prev_row})",
                            csv_path,
                            row_num,
                            {
                                "current_time": current_time,
                                "previous_time": prev_time,
                                "previous_row": prev_row,
                                "column": time_column,
                            },
                        )
                else:
                    if current_time < prev_time:
                        raise TimingValidationError(
                            f"Monotonic time violation at row {row_num}: "
                            f"{current_time} < {prev_time} (previous at row {prev_row})",
                            csv_path,
                            row_num,
                            {
                                "current_time": current_time,
                                "previous_time": prev_time,
                                "previous_row": prev_row,
                                "column": time_column,
                            },
                        )

            prev_time = current_time
            prev_row = row_num

    return timestamps


def assert_no_time_travel(
    csv_path: Union[str, Path],
    mono_column: str = "record_time_mono",
    unix_column: str = "record_time_unix",
    max_drift_ratio: float = 0.01,
    max_drift_absolute: float = 0.5,
) -> Dict[str, float]:
    """Verify no backward time jumps and check unix/mono time alignment.

    This function performs two checks:
    1. Ensures monotonic time never decreases (no time travel)
    2. Verifies that the drift between unix and monotonic time deltas
       stays within acceptable bounds

    Args:
        csv_path: Path to the CSV file to validate.
        mono_column: Name of the monotonic timestamp column.
        unix_column: Name of the unix timestamp column.
        max_drift_ratio: Maximum allowed drift as a ratio of elapsed time.
        max_drift_absolute: Maximum allowed absolute drift in seconds.

    Returns:
        Dictionary containing timing statistics:
        - 'total_rows': Number of rows validated
        - 'mono_start': First monotonic timestamp
        - 'mono_end': Last monotonic timestamp
        - 'mono_duration': Duration in monotonic time
        - 'unix_start': First unix timestamp
        - 'unix_end': Last unix timestamp
        - 'unix_duration': Duration in unix time
        - 'max_observed_drift': Maximum observed drift between timestamps

    Raises:
        TimingValidationError: If time travel is detected or drift exceeds limits.
        FileNotFoundError: If the CSV file does not exist.

    Example:
        >>> stats = assert_no_time_travel('/path/to/gps.csv')
        >>> print(f"Recording duration: {stats['mono_duration']:.2f}s")
    """
    csv_path = Path(csv_path)

    if not csv_path.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")

    mono_times: List[Tuple[int, float]] = []
    unix_times: List[Tuple[int, float]] = []
    max_observed_drift: float = 0.0

    with open(csv_path, 'r', newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []

        has_mono = mono_column in fieldnames
        has_unix = unix_column in fieldnames

        if not has_mono and not has_unix:
            raise KeyError(
                f"Neither '{mono_column}' nor '{unix_column}' found in CSV. "
                f"Available columns: {fieldnames}"
            )

        prev_mono: Optional[float] = None
        prev_unix: Optional[float] = None
        prev_row: Optional[int] = None

        for row_num, row in enumerate(reader, start=2):
            mono_str = row.get(mono_column, '').strip() if has_mono else ''
            unix_str = row.get(unix_column, '').strip() if has_unix else ''

            # Parse timestamps
            mono_time: Optional[float] = None
            unix_time: Optional[float] = None

            if mono_str:
                try:
                    mono_time = float(mono_str)
                    mono_times.append((row_num, mono_time))
                except ValueError:
                    pass

            if unix_str:
                try:
                    unix_time = float(unix_str)
                    unix_times.append((row_num, unix_time))
                except ValueError:
                    pass

            # Check for time travel in monotonic time
            if mono_time is not None and prev_mono is not None:
                if mono_time < prev_mono:
                    raise TimingValidationError(
                        f"Time travel detected at row {row_num}: "
                        f"monotonic time {mono_time} < {prev_mono} (previous at row {prev_row})",
                        csv_path,
                        row_num,
                        {
                            "current_mono": mono_time,
                            "previous_mono": prev_mono,
                            "previous_row": prev_row,
                        },
                    )

            # Check drift between mono and unix time deltas
            if (mono_time is not None and prev_mono is not None and
                unix_time is not None and prev_unix is not None):
                mono_delta = mono_time - prev_mono
                unix_delta = unix_time - prev_unix
                drift = abs(mono_delta - unix_delta)

                max_observed_drift = max(max_observed_drift, drift)

                # Calculate allowed drift
                elapsed = max(mono_delta, unix_delta)
                max_allowed = max(elapsed * max_drift_ratio, max_drift_absolute)

                if drift > max_allowed:
                    raise TimingValidationError(
                        f"Excessive time drift at row {row_num}: "
                        f"mono_delta={mono_delta:.6f}s, unix_delta={unix_delta:.6f}s, "
                        f"drift={drift:.6f}s exceeds max={max_allowed:.6f}s",
                        csv_path,
                        row_num,
                        {
                            "mono_delta": mono_delta,
                            "unix_delta": unix_delta,
                            "drift": drift,
                            "max_allowed": max_allowed,
                        },
                    )

            prev_mono = mono_time if mono_time is not None else prev_mono
            prev_unix = unix_time if unix_time is not None else prev_unix
            prev_row = row_num

    # Build statistics
    stats: Dict[str, float] = {
        'total_rows': len(mono_times) if mono_times else len(unix_times),
        'max_observed_drift': max_observed_drift,
    }

    if mono_times:
        stats['mono_start'] = mono_times[0][1]
        stats['mono_end'] = mono_times[-1][1]
        stats['mono_duration'] = mono_times[-1][1] - mono_times[0][1]

    if unix_times:
        stats['unix_start'] = unix_times[0][1]
        stats['unix_end'] = unix_times[-1][1]
        stats['unix_duration'] = unix_times[-1][1] - unix_times[0][1]

    return stats


def assert_csv_row_count(
    path: Union[str, Path],
    min_rows: Optional[int] = None,
    max_rows: Optional[int] = None,
    exact_rows: Optional[int] = None,
) -> int:
    """Assert that a CSV file has a specific number of data rows.

    Args:
        path: Path to the CSV file.
        min_rows: Minimum number of rows required (inclusive).
        max_rows: Maximum number of rows allowed (inclusive).
        exact_rows: Exact number of rows required (overrides min/max).

    Returns:
        The actual row count.

    Raises:
        AssertionError: If row count does not meet requirements.
        FileNotFoundError: If the CSV file does not exist.

    Example:
        >>> count = assert_csv_row_count('/path/to/data.csv', min_rows=1)
        >>> print(f"File has {count} rows")
    """
    path = Path(path)

    if not path.exists():
        raise FileNotFoundError(f"CSV file not found: {path}")

    with open(path, 'r', newline='', encoding='utf-8') as f:
        reader = csv.reader(f)
        next(reader, None)  # Skip header
        row_count = sum(1 for _ in reader)

    if exact_rows is not None:
        assert row_count == exact_rows, (
            f"Expected exactly {exact_rows} rows, got {row_count} in {path.name}"
        )
    else:
        if min_rows is not None:
            assert row_count >= min_rows, (
                f"Expected at least {min_rows} rows, got {row_count} in {path.name}"
            )
        if max_rows is not None:
            assert row_count <= max_rows, (
                f"Expected at most {max_rows} rows, got {row_count} in {path.name}"
            )

    return row_count


def assert_column_values(
    path: Union[str, Path],
    column: str,
    allowed_values: Optional[List] = None,
    min_value: Optional[float] = None,
    max_value: Optional[float] = None,
    not_empty: bool = False,
) -> List[str]:
    """Assert constraints on values in a specific CSV column.

    Args:
        path: Path to the CSV file.
        column: Name of the column to check.
        allowed_values: List of allowed values (if specified).
        min_value: Minimum numeric value (if checking numeric column).
        max_value: Maximum numeric value (if checking numeric column).
        not_empty: If True, require all values to be non-empty.

    Returns:
        List of all values found in the column.

    Raises:
        AssertionError: If any value violates the constraints.
        KeyError: If the column does not exist.
        FileNotFoundError: If the CSV file does not exist.

    Example:
        >>> values = assert_column_values('/path/to/data.csv', 'fix_valid', allowed_values=[0, 1])
    """
    path = Path(path)

    if not path.exists():
        raise FileNotFoundError(f"CSV file not found: {path}")

    values: List[str] = []

    with open(path, 'r', newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)

        if column not in (reader.fieldnames or []):
            raise KeyError(f"Column '{column}' not found. Available: {reader.fieldnames}")

        for row_num, row in enumerate(reader, start=2):
            value = row.get(column, '')
            values.append(value)

            if not_empty and not value.strip():
                raise AssertionError(
                    f"Empty value in column '{column}' at row {row_num} in {path.name}"
                )

            if value.strip():  # Only check non-empty values
                if allowed_values is not None:
                    # Try numeric comparison first
                    try:
                        numeric = float(value) if '.' in value else int(value)
                        if numeric not in allowed_values:
                            raise AssertionError(
                                f"Value {numeric} in column '{column}' at row {row_num} "
                                f"not in allowed values {allowed_values}"
                            )
                    except ValueError:
                        if value not in allowed_values:
                            raise AssertionError(
                                f"Value '{value}' in column '{column}' at row {row_num} "
                                f"not in allowed values {allowed_values}"
                            )

                if min_value is not None or max_value is not None:
                    try:
                        numeric = float(value)
                        if min_value is not None and numeric < min_value:
                            raise AssertionError(
                                f"Value {numeric} in column '{column}' at row {row_num} "
                                f"is below minimum {min_value}"
                            )
                        if max_value is not None and numeric > max_value:
                            raise AssertionError(
                                f"Value {numeric} in column '{column}' at row {row_num} "
                                f"exceeds maximum {max_value}"
                            )
                    except ValueError:
                        raise AssertionError(
                            f"Non-numeric value '{value}' in column '{column}' at row {row_num} "
                            f"cannot be range-checked"
                        )

    return values
