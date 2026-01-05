"""
API Schemas package.

Provides validation schemas for API request/response data.
"""

from .settings_schemas import (
    SettingType,
    SettingField,
    SettingsSchema,
    AUDIO_SETTINGS_SCHEMA,
    CAMERAS_SETTINGS_SCHEMA,
    GPS_SETTINGS_SCHEMA,
    DRT_SETTINGS_SCHEMA,
    VOG_SETTINGS_SCHEMA,
    EYETRACKER_SETTINGS_SCHEMA,
    NOTES_SETTINGS_SCHEMA,
    GLOBAL_SETTINGS_SCHEMA,
    SETTINGS_SCHEMAS,
    get_schema,
    get_all_schemas,
    validate_settings,
    get_defaults,
)

__all__ = [
    "SettingType",
    "SettingField",
    "SettingsSchema",
    "AUDIO_SETTINGS_SCHEMA",
    "CAMERAS_SETTINGS_SCHEMA",
    "GPS_SETTINGS_SCHEMA",
    "DRT_SETTINGS_SCHEMA",
    "VOG_SETTINGS_SCHEMA",
    "EYETRACKER_SETTINGS_SCHEMA",
    "NOTES_SETTINGS_SCHEMA",
    "GLOBAL_SETTINGS_SCHEMA",
    "SETTINGS_SCHEMAS",
    "get_schema",
    "get_all_schemas",
    "validate_settings",
    "get_defaults",
]
