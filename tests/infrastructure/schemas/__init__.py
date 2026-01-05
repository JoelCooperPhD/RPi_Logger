"""Validation schemas for test data.

This module contains CSV schema definitions and hardware detection utilities
for validating test data and detecting available hardware.
"""

from .csv_schema import (
    ALL_SCHEMAS,
    CSVSchema,
    ColumnSpec,
    ColumnType,
    DRT_SDRT_SCHEMA,
    DRT_WDRT_SCHEMA,
    EYETRACKER_EVENTS_SCHEMA,
    EYETRACKER_GAZE_SCHEMA,
    EYETRACKER_IMU_SCHEMA,
    GPS_SCHEMA,
    NOTES_SCHEMA,
    ValidationError,
    ValidationResult,
    VOG_SVOG_SCHEMA,
    VOG_WVOG_SCHEMA,
    detect_schema,
    validate_csv_file,
    validate_header,
    validate_row,
)

from .hardware_detection import (
    ModuleAvailability,
    HardwareAvailability,
    get_hardware_availability,
    requires_hardware,
)

__all__ = [
    # CSV Schema
    "ALL_SCHEMAS",
    "CSVSchema",
    "ColumnSpec",
    "ColumnType",
    "DRT_SDRT_SCHEMA",
    "DRT_WDRT_SCHEMA",
    "EYETRACKER_EVENTS_SCHEMA",
    "EYETRACKER_GAZE_SCHEMA",
    "EYETRACKER_IMU_SCHEMA",
    "GPS_SCHEMA",
    "NOTES_SCHEMA",
    "ValidationError",
    "ValidationResult",
    "VOG_SVOG_SCHEMA",
    "VOG_WVOG_SCHEMA",
    "detect_schema",
    "validate_csv_file",
    "validate_header",
    "validate_row",
    # Hardware Detection
    "ModuleAvailability",
    "HardwareAvailability",
    "get_hardware_availability",
    "requires_hardware",
]
