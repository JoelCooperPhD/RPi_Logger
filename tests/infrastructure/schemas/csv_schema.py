"""CSV Schema Validation Framework.

Defines schemas for all Logger module CSV outputs and provides validation utilities.
Each schema specifies column names, types, and validation constraints.

Usage:
    from csv_schema import GPS_SCHEMA, validate_csv_file

    errors = validate_csv_file('/path/to/gps_data.csv', GPS_SCHEMA)
    if errors:
        for error in errors:
            print(error)
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Union


class ColumnType(Enum):
    """Data types for CSV columns."""
    INT = auto()
    FLOAT = auto()
    STRING = auto()
    BOOL_INT = auto()  # 0 or 1 representing boolean
    TIMESTAMP_UNIX = auto()  # Unix timestamp (float, seconds since epoch)
    TIMESTAMP_MONO = auto()  # Monotonic timestamp (float, seconds)
    TIMESTAMP_NS = auto()  # Nanosecond timestamp (int)
    ISO_DATETIME = auto()  # ISO 8601 datetime string


@dataclass
class ColumnSpec:
    """Specification for a single CSV column."""
    name: str
    dtype: ColumnType
    required: bool = True
    nullable: bool = True  # Can be empty string
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    allowed_values: Optional[Sequence[Any]] = None
    regex_pattern: Optional[str] = None
    description: str = ""

    def validate(self, value: str, row_num: int) -> List[str]:
        """Validate a single value against this column spec.

        Args:
            value: String value from CSV cell
            row_num: Row number (1-indexed) for error messages

        Returns:
            List of error messages (empty if valid)
        """
        errors = []

        # Handle empty values
        if value == "" or value is None:
            if self.required and not self.nullable:
                errors.append(f"Row {row_num}, {self.name}: required value is empty")
            return errors

        # Type validation
        parsed_value = None
        try:
            if self.dtype == ColumnType.INT:
                parsed_value = int(value)
            elif self.dtype == ColumnType.FLOAT:
                parsed_value = float(value)
            elif self.dtype == ColumnType.TIMESTAMP_UNIX:
                parsed_value = float(value)
                if parsed_value < 0:
                    errors.append(f"Row {row_num}, {self.name}: unix timestamp cannot be negative")
            elif self.dtype == ColumnType.TIMESTAMP_MONO:
                parsed_value = float(value)
                if parsed_value < 0:
                    errors.append(f"Row {row_num}, {self.name}: monotonic timestamp cannot be negative")
            elif self.dtype == ColumnType.TIMESTAMP_NS:
                parsed_value = int(value)
                if parsed_value < 0:
                    errors.append(f"Row {row_num}, {self.name}: nanosecond timestamp cannot be negative")
            elif self.dtype == ColumnType.BOOL_INT:
                parsed_value = int(value)
                if parsed_value not in (0, 1):
                    errors.append(f"Row {row_num}, {self.name}: boolean int must be 0 or 1, got {parsed_value}")
            elif self.dtype == ColumnType.ISO_DATETIME:
                # Basic ISO 8601 format check
                if not re.match(r'\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}', value):
                    errors.append(f"Row {row_num}, {self.name}: invalid ISO datetime format")
                parsed_value = value
            elif self.dtype == ColumnType.STRING:
                parsed_value = value
        except (ValueError, TypeError) as e:
            errors.append(f"Row {row_num}, {self.name}: type error - expected {self.dtype.name}, got '{value}'")
            return errors

        # Range validation
        if parsed_value is not None and isinstance(parsed_value, (int, float)):
            if self.min_value is not None and parsed_value < self.min_value:
                errors.append(f"Row {row_num}, {self.name}: value {parsed_value} below minimum {self.min_value}")
            if self.max_value is not None and parsed_value > self.max_value:
                errors.append(f"Row {row_num}, {self.name}: value {parsed_value} above maximum {self.max_value}")

        # Allowed values validation
        if self.allowed_values is not None and parsed_value not in self.allowed_values:
            errors.append(f"Row {row_num}, {self.name}: value '{value}' not in allowed values {self.allowed_values}")

        # Regex validation
        if self.regex_pattern is not None:
            if not re.match(self.regex_pattern, str(value)):
                errors.append(f"Row {row_num}, {self.name}: value '{value}' does not match pattern {self.regex_pattern}")

        return errors


@dataclass
class CSVSchema:
    """Schema definition for a CSV file format."""
    name: str
    columns: List[ColumnSpec]
    module_name: str
    description: str = ""

    @property
    def header(self) -> List[str]:
        """Return expected header as list of column names."""
        return [col.name for col in self.columns]

    @property
    def header_string(self) -> str:
        """Return expected header as comma-separated string."""
        return ",".join(self.header)

    @property
    def column_count(self) -> int:
        """Return expected number of columns."""
        return len(self.columns)

    def get_column(self, name: str) -> Optional[ColumnSpec]:
        """Get column spec by name."""
        for col in self.columns:
            if col.name == name:
                return col
        return None


@dataclass
class ValidationError:
    """Represents a validation error."""
    row: int
    column: Optional[str]
    message: str
    severity: str = "error"  # "error" or "warning"

    def __str__(self) -> str:
        if self.column:
            return f"[{self.severity.upper()}] Row {self.row}, {self.column}: {self.message}"
        return f"[{self.severity.upper()}] Row {self.row}: {self.message}"


@dataclass
class ValidationResult:
    """Result of validating a CSV file."""
    schema_name: str
    file_path: str
    is_valid: bool
    row_count: int
    errors: List[ValidationError] = field(default_factory=list)
    warnings: List[ValidationError] = field(default_factory=list)

    @property
    def error_count(self) -> int:
        return len(self.errors)

    @property
    def warning_count(self) -> int:
        return len(self.warnings)

    def summary(self) -> str:
        """Return human-readable summary."""
        status = "PASS" if self.is_valid else "FAIL"
        return (
            f"{self.schema_name}: {status} "
            f"({self.row_count} rows, {self.error_count} errors, {self.warning_count} warnings)"
        )


# =============================================================================
# Standard 6-Column Prefix (shared by all CSV modules)
# =============================================================================

STANDARD_PREFIX_COLUMNS = [
    ColumnSpec("trial", ColumnType.INT, min_value=1, description="Trial number (1-indexed)"),
    ColumnSpec("module", ColumnType.STRING, nullable=False, description="Module name"),
    ColumnSpec("device_id", ColumnType.STRING, description="Device identifier"),
    ColumnSpec("label", ColumnType.STRING, description="User-assigned label"),
    ColumnSpec("record_time_unix", ColumnType.TIMESTAMP_UNIX, description="System time (seconds since epoch)"),
    ColumnSpec("record_time_mono", ColumnType.TIMESTAMP_MONO, description="Monotonic clock (seconds)"),
]


def _prefix_columns() -> List[ColumnSpec]:
    """Return a fresh copy of standard prefix columns."""
    return [
        ColumnSpec(c.name, c.dtype, c.required, c.nullable, c.min_value, c.max_value,
                   c.allowed_values, c.regex_pattern, c.description)
        for c in STANDARD_PREFIX_COLUMNS
    ]


# =============================================================================
# GPS Schema (26 columns)
# =============================================================================

GPS_SCHEMA = CSVSchema(
    name="GPS",
    module_name="GPS",
    description="GPS/NMEA position data",
    columns=_prefix_columns() + [
        ColumnSpec("device_time_iso", ColumnType.ISO_DATETIME, nullable=True, description="Device time (ISO 8601)"),
        ColumnSpec("device_time_unix", ColumnType.TIMESTAMP_UNIX, nullable=True, description="Device epoch time"),
        ColumnSpec("latitude_deg", ColumnType.FLOAT, min_value=-90, max_value=90, description="Latitude (decimal degrees)"),
        ColumnSpec("longitude_deg", ColumnType.FLOAT, min_value=-180, max_value=180, description="Longitude (decimal degrees)"),
        ColumnSpec("altitude_m", ColumnType.FLOAT, min_value=-500, max_value=50000, description="Altitude (meters)"),
        ColumnSpec("speed_mps", ColumnType.FLOAT, min_value=0, description="Speed (m/s)"),
        ColumnSpec("speed_kmh", ColumnType.FLOAT, min_value=0, description="Speed (km/h)"),
        ColumnSpec("speed_knots", ColumnType.FLOAT, min_value=0, description="Speed (knots)"),
        ColumnSpec("speed_mph", ColumnType.FLOAT, min_value=0, description="Speed (mph)"),
        ColumnSpec("course_deg", ColumnType.FLOAT, min_value=0, max_value=360, description="Course (degrees from north)"),
        ColumnSpec("fix_quality", ColumnType.INT, min_value=0, max_value=8, description="GPS fix quality code"),
        ColumnSpec("fix_mode", ColumnType.STRING, description="Fix mode (A/V or mode string)"),
        ColumnSpec("fix_valid", ColumnType.BOOL_INT, description="Fix validity (0/1)"),
        ColumnSpec("satellites_in_use", ColumnType.INT, min_value=0, description="Active satellites"),
        ColumnSpec("satellites_in_view", ColumnType.INT, min_value=0, description="Visible satellites"),
        ColumnSpec("hdop", ColumnType.FLOAT, min_value=0, description="Horizontal dilution of precision"),
        ColumnSpec("pdop", ColumnType.FLOAT, min_value=0, description="Position dilution of precision"),
        ColumnSpec("vdop", ColumnType.FLOAT, min_value=0, description="Vertical dilution of precision"),
        ColumnSpec("sentence_type", ColumnType.STRING, description="NMEA sentence type (GGA/RMC/VTG/etc)"),
        ColumnSpec("raw_sentence", ColumnType.STRING, description="Raw NMEA sentence"),
    ]
)


# =============================================================================
# DRT Schemas (10 columns for sDRT, 11 for wDRT)
# =============================================================================

DRT_SDRT_SCHEMA = CSVSchema(
    name="DRT_sDRT",
    module_name="DRT",
    description="Simple Detection Response Task data",
    columns=_prefix_columns() + [
        ColumnSpec("device_time_ms", ColumnType.INT, min_value=0, description="Device timestamp (milliseconds)"),
        ColumnSpec("device_time_unix", ColumnType.TIMESTAMP_UNIX, nullable=True, description="Device epoch time"),
        ColumnSpec("responses", ColumnType.INT, min_value=0, description="Response count"),
        ColumnSpec("reaction_time_ms", ColumnType.INT, min_value=-1, description="Reaction time (ms), -1 = timeout"),
    ]
)

DRT_WDRT_SCHEMA = CSVSchema(
    name="DRT_wDRT",
    module_name="DRT",
    description="Wireless Detection Response Task data",
    columns=_prefix_columns() + [
        ColumnSpec("device_time_ms", ColumnType.INT, min_value=0, description="Device timestamp (milliseconds)"),
        ColumnSpec("device_time_unix", ColumnType.TIMESTAMP_UNIX, description="Device epoch time"),
        ColumnSpec("responses", ColumnType.INT, min_value=0, description="Response count"),
        ColumnSpec("reaction_time_ms", ColumnType.INT, min_value=-1, description="Reaction time (ms), -1 = timeout"),
        ColumnSpec("battery_percent", ColumnType.INT, min_value=0, max_value=100, description="Battery level (%)"),
    ]
)


# =============================================================================
# VOG Schemas (8 columns for sVOG, 11 for wVOG)
# =============================================================================

VOG_SVOG_SCHEMA = CSVSchema(
    name="VOG_sVOG",
    module_name="VOG",
    description="Simple Vision Occlusion Glasses data",
    columns=_prefix_columns() + [
        ColumnSpec("shutter_open", ColumnType.INT, min_value=0, description="Time shutter open (ms)"),
        ColumnSpec("shutter_closed", ColumnType.INT, min_value=0, description="Time shutter closed (ms)"),
    ]
)

VOG_WVOG_SCHEMA = CSVSchema(
    name="VOG_wVOG",
    module_name="VOG",
    description="Wireless Vision Occlusion Glasses data",
    columns=_prefix_columns() + [
        ColumnSpec("shutter_open", ColumnType.INT, min_value=0, description="Time shutter open (ms)"),
        ColumnSpec("shutter_closed", ColumnType.INT, min_value=0, description="Time shutter closed (ms)"),
        ColumnSpec("shutter_total", ColumnType.INT, min_value=0, description="Total shutter time (ms)"),
        ColumnSpec("lens", ColumnType.STRING, allowed_values=['A', 'B', 'X'], description="Lens identifier"),
        ColumnSpec("battery_percent", ColumnType.INT, min_value=0, max_value=100, description="Battery level (%)"),
    ]
)


# =============================================================================
# EyeTracker Schemas (36 GAZE, 19 IMU, 24 EVENTS)
# =============================================================================

EYETRACKER_GAZE_SCHEMA = CSVSchema(
    name="EyeTracker_GAZE",
    module_name="EyeTracker",
    description="Gaze tracking data from Pupil Labs Neon",
    columns=_prefix_columns() + [
        ColumnSpec("timestamp", ColumnType.TIMESTAMP_UNIX, description="Device timestamp"),
        ColumnSpec("timestamp_ns", ColumnType.TIMESTAMP_NS, description="Nanosecond timestamp"),
        ColumnSpec("stream_type", ColumnType.STRING, description="Stream type identifier"),
        ColumnSpec("worn", ColumnType.BOOL_INT, description="Headset worn status"),
        ColumnSpec("x", ColumnType.FLOAT, min_value=0, max_value=1, description="Normalized gaze X"),
        ColumnSpec("y", ColumnType.FLOAT, min_value=0, max_value=1, description="Normalized gaze Y"),
        ColumnSpec("left_x", ColumnType.FLOAT, description="Left eye X"),
        ColumnSpec("left_y", ColumnType.FLOAT, description="Left eye Y"),
        ColumnSpec("right_x", ColumnType.FLOAT, description="Right eye X"),
        ColumnSpec("right_y", ColumnType.FLOAT, description="Right eye Y"),
        ColumnSpec("pupil_diameter_left", ColumnType.FLOAT, min_value=0, description="Left pupil diameter (mm)"),
        ColumnSpec("pupil_diameter_right", ColumnType.FLOAT, min_value=0, description="Right pupil diameter (mm)"),
        ColumnSpec("eyeball_center_left_x", ColumnType.FLOAT, description="Left eyeball center X"),
        ColumnSpec("eyeball_center_left_y", ColumnType.FLOAT, description="Left eyeball center Y"),
        ColumnSpec("eyeball_center_left_z", ColumnType.FLOAT, description="Left eyeball center Z"),
        ColumnSpec("optical_axis_left_x", ColumnType.FLOAT, description="Left optical axis X"),
        ColumnSpec("optical_axis_left_y", ColumnType.FLOAT, description="Left optical axis Y"),
        ColumnSpec("optical_axis_left_z", ColumnType.FLOAT, description="Left optical axis Z"),
        ColumnSpec("eyeball_center_right_x", ColumnType.FLOAT, description="Right eyeball center X"),
        ColumnSpec("eyeball_center_right_y", ColumnType.FLOAT, description="Right eyeball center Y"),
        ColumnSpec("eyeball_center_right_z", ColumnType.FLOAT, description="Right eyeball center Z"),
        ColumnSpec("optical_axis_right_x", ColumnType.FLOAT, description="Right optical axis X"),
        ColumnSpec("optical_axis_right_y", ColumnType.FLOAT, description="Right optical axis Y"),
        ColumnSpec("optical_axis_right_z", ColumnType.FLOAT, description="Right optical axis Z"),
        ColumnSpec("eyelid_angle_top_left", ColumnType.FLOAT, description="Left top eyelid angle"),
        ColumnSpec("eyelid_angle_bottom_left", ColumnType.FLOAT, description="Left bottom eyelid angle"),
        ColumnSpec("eyelid_aperture_left", ColumnType.FLOAT, min_value=0, description="Left eyelid aperture (mm)"),
        ColumnSpec("eyelid_angle_top_right", ColumnType.FLOAT, description="Right top eyelid angle"),
        ColumnSpec("eyelid_angle_bottom_right", ColumnType.FLOAT, description="Right bottom eyelid angle"),
        ColumnSpec("eyelid_aperture_right", ColumnType.FLOAT, min_value=0, description="Right eyelid aperture (mm)"),
    ]
)

EYETRACKER_IMU_SCHEMA = CSVSchema(
    name="EyeTracker_IMU",
    module_name="EyeTracker",
    description="IMU sensor data from Pupil Labs Neon",
    columns=_prefix_columns() + [
        ColumnSpec("timestamp", ColumnType.TIMESTAMP_UNIX, description="Device timestamp"),
        ColumnSpec("timestamp_ns", ColumnType.TIMESTAMP_NS, description="Nanosecond timestamp"),
        ColumnSpec("gyro_x", ColumnType.FLOAT, description="Gyroscope X (rad/s)"),
        ColumnSpec("gyro_y", ColumnType.FLOAT, description="Gyroscope Y (rad/s)"),
        ColumnSpec("gyro_z", ColumnType.FLOAT, description="Gyroscope Z (rad/s)"),
        ColumnSpec("accel_x", ColumnType.FLOAT, description="Accelerometer X (m/s^2)"),
        ColumnSpec("accel_y", ColumnType.FLOAT, description="Accelerometer Y (m/s^2)"),
        ColumnSpec("accel_z", ColumnType.FLOAT, description="Accelerometer Z (m/s^2)"),
        ColumnSpec("quat_w", ColumnType.FLOAT, description="Quaternion W"),
        ColumnSpec("quat_x", ColumnType.FLOAT, description="Quaternion X"),
        ColumnSpec("quat_y", ColumnType.FLOAT, description="Quaternion Y"),
        ColumnSpec("quat_z", ColumnType.FLOAT, description="Quaternion Z"),
        ColumnSpec("temperature", ColumnType.FLOAT, min_value=-40, max_value=85, description="Sensor temperature (C)"),
    ]
)

EYETRACKER_EVENTS_SCHEMA = CSVSchema(
    name="EyeTracker_EVENTS",
    module_name="EyeTracker",
    description="Eye events (fixations, saccades, blinks) from Pupil Labs Neon",
    columns=_prefix_columns() + [
        ColumnSpec("timestamp", ColumnType.TIMESTAMP_UNIX, description="Event timestamp"),
        ColumnSpec("timestamp_ns", ColumnType.TIMESTAMP_NS, description="Nanosecond timestamp"),
        ColumnSpec("event_type", ColumnType.STRING, description="Event type (fixation/saccade/blink)"),
        ColumnSpec("event_subtype", ColumnType.STRING, description="Event subtype"),
        ColumnSpec("confidence", ColumnType.FLOAT, min_value=0, max_value=1, description="Detection confidence"),
        ColumnSpec("duration", ColumnType.FLOAT, min_value=0, description="Event duration (seconds)"),
        ColumnSpec("start_time_ns", ColumnType.TIMESTAMP_NS, description="Event start (ns)"),
        ColumnSpec("end_time_ns", ColumnType.TIMESTAMP_NS, description="Event end (ns)"),
        ColumnSpec("start_gaze_x", ColumnType.FLOAT, description="Start gaze X"),
        ColumnSpec("start_gaze_y", ColumnType.FLOAT, description="Start gaze Y"),
        ColumnSpec("end_gaze_x", ColumnType.FLOAT, description="End gaze X"),
        ColumnSpec("end_gaze_y", ColumnType.FLOAT, description="End gaze Y"),
        ColumnSpec("mean_gaze_x", ColumnType.FLOAT, description="Mean gaze X"),
        ColumnSpec("mean_gaze_y", ColumnType.FLOAT, description="Mean gaze Y"),
        ColumnSpec("amplitude_pixels", ColumnType.FLOAT, min_value=0, description="Saccade amplitude (pixels)"),
        ColumnSpec("amplitude_angle_deg", ColumnType.FLOAT, min_value=0, description="Saccade amplitude (degrees)"),
        ColumnSpec("mean_velocity", ColumnType.FLOAT, min_value=0, description="Mean angular velocity"),
        ColumnSpec("max_velocity", ColumnType.FLOAT, min_value=0, description="Peak angular velocity"),
    ]
)


# =============================================================================
# Notes Schema (8 columns)
# =============================================================================

NOTES_SCHEMA = CSVSchema(
    name="Notes",
    module_name="Notes",
    description="User text annotations",
    columns=_prefix_columns() + [
        ColumnSpec("device_time_unix", ColumnType.TIMESTAMP_UNIX, nullable=True, description="Device time"),
        ColumnSpec("content", ColumnType.STRING, description="Note text content"),
    ]
)


# =============================================================================
# Schema Registry
# =============================================================================

ALL_SCHEMAS: Dict[str, CSVSchema] = {
    "GPS": GPS_SCHEMA,
    "DRT_sDRT": DRT_SDRT_SCHEMA,
    "DRT_wDRT": DRT_WDRT_SCHEMA,
    "VOG_sVOG": VOG_SVOG_SCHEMA,
    "VOG_wVOG": VOG_WVOG_SCHEMA,
    "EyeTracker_GAZE": EYETRACKER_GAZE_SCHEMA,
    "EyeTracker_IMU": EYETRACKER_IMU_SCHEMA,
    "EyeTracker_EVENTS": EYETRACKER_EVENTS_SCHEMA,
    "Notes": NOTES_SCHEMA,
}

# Mapping from module name to possible schemas
MODULE_SCHEMAS: Dict[str, List[CSVSchema]] = {
    "GPS": [GPS_SCHEMA],
    "DRT": [DRT_SDRT_SCHEMA, DRT_WDRT_SCHEMA],
    "VOG": [VOG_SVOG_SCHEMA, VOG_WVOG_SCHEMA],
    "EyeTracker": [EYETRACKER_GAZE_SCHEMA, EYETRACKER_IMU_SCHEMA, EYETRACKER_EVENTS_SCHEMA],
    "Notes": [NOTES_SCHEMA],
}


# =============================================================================
# Validation Functions
# =============================================================================

def validate_header(header: List[str], schema: CSVSchema) -> List[ValidationError]:
    """Validate CSV header against schema.

    Args:
        header: List of column names from CSV
        schema: Expected schema

    Returns:
        List of validation errors (empty if valid)
    """
    errors = []
    expected = schema.header

    if len(header) != len(expected):
        errors.append(ValidationError(
            row=1,
            column=None,
            message=f"Column count mismatch: expected {len(expected)}, got {len(header)}"
        ))
        return errors

    for i, (actual, exp) in enumerate(zip(header, expected)):
        if actual.strip() != exp:
            errors.append(ValidationError(
                row=1,
                column=f"column[{i}]",
                message=f"Header mismatch: expected '{exp}', got '{actual}'"
            ))

    return errors


def validate_row(row: List[str], schema: CSVSchema, row_num: int) -> List[ValidationError]:
    """Validate a single CSV row against schema.

    Args:
        row: List of values from CSV row
        schema: Expected schema
        row_num: Row number (1-indexed, counting from after header)

    Returns:
        List of validation errors
    """
    errors = []

    # Check column count
    if len(row) != schema.column_count:
        errors.append(ValidationError(
            row=row_num,
            column=None,
            message=f"Column count mismatch: expected {schema.column_count}, got {len(row)}"
        ))
        return errors

    # Validate each column
    for i, (value, col_spec) in enumerate(zip(row, schema.columns)):
        col_errors = col_spec.validate(value, row_num)
        for err_msg in col_errors:
            errors.append(ValidationError(
                row=row_num,
                column=col_spec.name,
                message=err_msg.split(": ", 1)[-1] if ": " in err_msg else err_msg
            ))

    return errors


def validate_csv_file(
    file_path: Union[str, Path],
    schema: CSVSchema,
    max_errors: int = 100,
) -> ValidationResult:
    """Validate an entire CSV file against a schema.

    Args:
        file_path: Path to CSV file
        schema: Expected schema
        max_errors: Stop after this many errors

    Returns:
        ValidationResult with all errors and warnings
    """
    file_path = Path(file_path)
    errors: List[ValidationError] = []
    warnings: List[ValidationError] = []
    row_count = 0

    try:
        with file_path.open('r', encoding='utf-8', newline='') as f:
            reader = csv.reader(f)

            # Validate header
            try:
                header = next(reader)
            except StopIteration:
                errors.append(ValidationError(
                    row=0,
                    column=None,
                    message="File is empty (no header)"
                ))
                return ValidationResult(
                    schema_name=schema.name,
                    file_path=str(file_path),
                    is_valid=False,
                    row_count=0,
                    errors=errors,
                )

            header_errors = validate_header(header, schema)
            errors.extend(header_errors)

            if header_errors:
                # Can't validate rows if header is wrong
                return ValidationResult(
                    schema_name=schema.name,
                    file_path=str(file_path),
                    is_valid=False,
                    row_count=0,
                    errors=errors,
                )

            # Validate each row
            prev_mono_time: Optional[float] = None

            for row_num, row in enumerate(reader, start=2):  # Start at 2 (header is row 1)
                row_count += 1

                if len(errors) >= max_errors:
                    warnings.append(ValidationError(
                        row=row_num,
                        column=None,
                        message=f"Stopped validation after {max_errors} errors",
                        severity="warning"
                    ))
                    break

                row_errors = validate_row(row, schema, row_num)
                errors.extend(row_errors)

                # Additional timing validation
                if len(row) >= 6:  # Has standard prefix
                    try:
                        mono_time = float(row[5]) if row[5] else None
                        if mono_time is not None and prev_mono_time is not None:
                            if mono_time < prev_mono_time:
                                warnings.append(ValidationError(
                                    row=row_num,
                                    column="record_time_mono",
                                    message=f"Monotonic time decreased (time travel): {mono_time} < {prev_mono_time}",
                                    severity="warning"
                                ))
                        prev_mono_time = mono_time
                    except (ValueError, IndexError):
                        pass

    except FileNotFoundError:
        errors.append(ValidationError(
            row=0,
            column=None,
            message=f"File not found: {file_path}"
        ))
    except Exception as e:
        errors.append(ValidationError(
            row=0,
            column=None,
            message=f"Error reading file: {e}"
        ))

    return ValidationResult(
        schema_name=schema.name,
        file_path=str(file_path),
        is_valid=len(errors) == 0,
        row_count=row_count,
        errors=errors,
        warnings=warnings,
    )


def detect_schema(file_path: Union[str, Path]) -> Optional[CSVSchema]:
    """Attempt to detect the schema of a CSV file based on its header.

    Args:
        file_path: Path to CSV file

    Returns:
        Matching schema or None if not detected
    """
    file_path = Path(file_path)

    try:
        with file_path.open('r', encoding='utf-8', newline='') as f:
            reader = csv.reader(f)
            header = next(reader)
    except (FileNotFoundError, StopIteration):
        return None

    # Try each schema
    for schema in ALL_SCHEMAS.values():
        if header == schema.header:
            return schema

    # Try partial match (same column count and first 6 columns match)
    for schema in ALL_SCHEMAS.values():
        if len(header) == schema.column_count:
            if header[:6] == schema.header[:6]:
                return schema

    return None


def validate_csv_directory(
    directory: Union[str, Path],
    schemas: Optional[Dict[str, CSVSchema]] = None,
) -> Dict[str, ValidationResult]:
    """Validate all CSV files in a directory.

    Args:
        directory: Directory containing CSV files
        schemas: Optional mapping of filename patterns to schemas

    Returns:
        Dictionary mapping file paths to validation results
    """
    directory = Path(directory)
    results = {}

    for csv_file in directory.glob("**/*.csv"):
        schema = detect_schema(csv_file)
        if schema is None:
            # Try to detect from filename
            name = csv_file.stem.upper()
            if "GPS" in name:
                schema = GPS_SCHEMA
            elif "GAZE" in name:
                schema = EYETRACKER_GAZE_SCHEMA
            elif "IMU" in name:
                schema = EYETRACKER_IMU_SCHEMA
            elif "EVENT" in name:
                schema = EYETRACKER_EVENTS_SCHEMA
            elif "NOTE" in name:
                schema = NOTES_SCHEMA
            elif "DRT" in name:
                # Check column count to distinguish sDRT vs wDRT
                with csv_file.open('r', encoding='utf-8', newline='') as f:
                    header = next(csv.reader(f))
                    schema = DRT_WDRT_SCHEMA if len(header) == 11 else DRT_SDRT_SCHEMA
            elif "VOG" in name:
                # Check column count to distinguish sVOG vs wVOG
                with csv_file.open('r', encoding='utf-8', newline='') as f:
                    header = next(csv.reader(f))
                    schema = VOG_WVOG_SCHEMA if len(header) == 11 else VOG_SVOG_SCHEMA

        if schema is not None:
            results[str(csv_file)] = validate_csv_file(csv_file, schema)

    return results
