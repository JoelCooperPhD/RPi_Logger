"""NMEA sentence parsing for GPS receivers.

This module provides stateful NMEA sentence parsing that accumulates
GPS fix data across multiple sentence types.
"""

from __future__ import annotations

import datetime as dt
import time
from typing import Any, Callable, Dict, Optional

from ..constants import FIX_MODE_MAP, KMH_PER_KNOT, MPH_PER_KNOT
from .nmea_types import GPSFixSnapshot


def _parse_float(value: str | None) -> Optional[float]:
    """Parse string to float, None on failure."""
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _parse_int(value: str | None) -> Optional[int]:
    """Parse string to int, None on failure."""
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _parse_latlon(
    value: str | None,
    direction: str | None,
    *,
    is_lat: bool
) -> Optional[float]:
    """Parse NMEA lat/lon format (DDMM.MMMM or DDDMM.MMMM) to decimal degrees."""
    if not value or not direction:
        return None
    try:
        deg_len = 2 if is_lat else 3
        if len(value) < deg_len:
            return None
        degrees = int(value[:deg_len])
        minutes = float(value[deg_len:])
    except ValueError:
        return None
    decimal = degrees + minutes / 60.0
    if direction.upper() in {"S", "W"}:
        decimal *= -1.0
    return decimal


def _parse_hms(value: str | None) -> Optional[dt.time]:
    """Parse NMEA time format (HHMMSS.sss) to datetime.time."""
    if not value:
        return None
    raw = value.strip()
    if not raw:
        return None
    main, dot, frac = raw.partition(".")
    main = main.rjust(6, "0")
    try:
        hour = int(main[0:2])
        minute = int(main[2:4])
        second = int(main[4:6])
        micro = int((frac[:6] if dot else "0").ljust(6, "0"))
    except ValueError:
        return None
    try:
        return dt.time(hour, minute, second, micro, tzinfo=dt.timezone.utc)
    except ValueError:
        return None


def _parse_date(value: str | None) -> Optional[dt.date]:
    """Parse NMEA date format (DDMMYY) to datetime.date."""
    if not value or len(value) != 6:
        return None
    try:
        day = int(value[0:2])
        month = int(value[2:4])
        year = 2000 + int(value[4:6])
        return dt.date(year, month, day)
    except ValueError:
        return None


def _combine_datetime(
    date_obj: Optional[dt.date],
    time_obj: Optional[dt.time],
    fallback: Optional[dt.datetime]
) -> Optional[dt.datetime]:
    """Combine date and time, using fallback if needed."""
    if not time_obj:
        return fallback
    date_value = date_obj
    if not date_value and fallback:
        date_value = fallback.date()
    if not date_value:
        date_value = dt.datetime.now(dt.timezone.utc).date()
    return dt.datetime.combine(date_value, time_obj)


def validate_checksum(sentence: str) -> bool:
    """Validate NMEA checksum."""
    if not sentence.startswith("$") or "*" not in sentence:
        return False
    try:
        payload, checksum_str = sentence[1:].split("*", 1)
        expected = int(checksum_str[:2], 16)
        calculated = 0
        for char in payload:
            calculated ^= ord(char)
        return calculated == expected
    except (ValueError, IndexError):
        return False


class NMEAParser:
    """Stateful NMEA sentence parser.

    Accumulates data from multiple NMEA sentence types into a GPSFixSnapshot.
    Maintains date state across sentences.
    """

    def __init__(
        self,
        on_fix_update: Optional[Callable[[GPSFixSnapshot, Dict[str, Any]], None]] = None,
        validate_checksums: bool = True,
        enabled_sentences: Optional[set[str]] = None,
    ):
        self._fix = GPSFixSnapshot()
        self._last_known_date: Optional[dt.date] = None
        self._on_fix_update = on_fix_update
        self._validate_checksums = validate_checksums
        self._enabled_sentences = enabled_sentences

    def set_enabled_sentences(self, sentences: Optional[set[str]]) -> None:
        self._enabled_sentences = sentences

    @property
    def fix(self) -> GPSFixSnapshot:
        """Current accumulated GPS fix data."""
        return self._fix

    @property
    def last_known_date(self) -> Optional[dt.date]:
        """Last date received from GPS (used for sentences without date)."""
        return self._last_known_date

    def reset(self) -> None:
        """Reset parser state to initial values."""
        self._fix = GPSFixSnapshot()
        self._last_known_date = None

    def parse_sentence(self, sentence: str) -> Optional[Dict[str, Any]]:
        """Parse NMEA sentence and update fix. Returns parsed values or None."""
        if not sentence or not sentence.startswith("$"):
            return None

        # Validate checksum if enabled
        if self._validate_checksums and not validate_checksum(sentence):
            return None

        # Extract payload (between $ and *)
        payload = sentence[1:]
        if "*" in payload:
            payload = payload.split("*", 1)[0]

        parts = payload.split(",")
        if not parts:
            return None

        # Get message type (last 3 chars of header, e.g., "RMC" from "GPRMC")
        header = parts[0]
        message_type = header[-3:].upper()

        # Filter by enabled sentences
        if self._enabled_sentences is not None and message_type not in self._enabled_sentences:
            return None

        # Find and call appropriate parser method
        handler = getattr(self, f"_parse_{message_type.lower()}", None)
        if not handler:
            return None

        data = handler(parts[1:])
        if data is None:
            return None

        data["sentence_type"] = message_type
        data["raw_sentence"] = sentence

        # Apply update to fix
        self._apply_update(data)

        # Call callback if registered
        if self._on_fix_update:
            self._on_fix_update(self._fix, data)

        return data

    def _apply_update(self, update: Dict[str, Any]) -> None:
        """Apply parsed data to the fix snapshot."""
        fix = self._fix

        # Position
        lat = update.get("latitude")
        lon = update.get("longitude")
        if lat is not None and lon is not None:
            fix.latitude = lat
            fix.longitude = lon

        # Timestamp
        timestamp = update.get("timestamp")
        if timestamp:
            fix.timestamp = timestamp

        # Fix quality and mode
        fix_quality = update.get("fix_quality")
        if fix_quality is not None:
            fix.fix_quality = fix_quality

        if "fix_mode" in update and update["fix_mode"]:
            fix.fix_mode = update["fix_mode"]

        if "fix_valid" in update:
            fix.fix_valid = bool(update["fix_valid"])

        # Satellites
        if "satellites_in_use" in update and update["satellites_in_use"] is not None:
            fix.satellites_in_use = int(update["satellites_in_use"])

        if "satellites_in_view" in update and update["satellites_in_view"] is not None:
            fix.satellites_in_view = int(update["satellites_in_view"])

        # Altitude
        if "altitude_m" in update and update["altitude_m"] is not None:
            fix.altitude_m = float(update["altitude_m"])

        # DOP values
        if "hdop" in update and update["hdop"] is not None:
            fix.hdop = float(update["hdop"])

        if "pdop" in update and update["pdop"] is not None:
            fix.pdop = float(update["pdop"])

        if "vdop" in update and update["vdop"] is not None:
            fix.vdop = float(update["vdop"])

        # Course
        if "course_deg" in update and update["course_deg"] is not None:
            fix.course_deg = float(update["course_deg"])

        # Speed (with unit conversions)
        speed_knots = update.get("speed_knots")
        if speed_knots is not None:
            fix.speed_knots = float(speed_knots)
            fix.speed_kmh = fix.speed_knots * KMH_PER_KNOT
            fix.speed_mph = fix.speed_knots * MPH_PER_KNOT
        elif update.get("speed_kmh") is not None:
            fix.speed_kmh = float(update["speed_kmh"])
            fix.speed_mph = fix.speed_kmh / 1.609344
            fix.speed_knots = fix.speed_kmh / KMH_PER_KNOT

        # Metadata
        fix.last_sentence = update.get("sentence_type") or fix.last_sentence
        fix.raw_sentence = update.get("raw_sentence") or fix.raw_sentence
        fix.last_update_monotonic = time.monotonic()

    # ------------------------------------------------------------------
    # Sentence-specific parsers
    # ------------------------------------------------------------------

    def _parse_rmc(self, fields: list[str]) -> Optional[Dict[str, Any]]:
        """Parse $GPRMC: time, status, position, speed, course, date."""
        if len(fields) < 9:
            return None

        time_str = fields[0]
        status = (fields[1] or "").upper()
        lat = _parse_latlon(fields[2], fields[3], is_lat=True)
        lon = _parse_latlon(fields[4], fields[5], is_lat=False)
        speed_knots = _parse_float(fields[6])
        course_deg = _parse_float(fields[7])
        date_str = fields[8]
        mode = fields[11] if len(fields) > 11 else None

        date_obj = _parse_date(date_str)
        if date_obj:
            self._last_known_date = date_obj
        time_obj = _parse_hms(time_str)
        timestamp = _combine_datetime(self._last_known_date, time_obj, self._fix.timestamp)

        return {
            "latitude": lat,
            "longitude": lon,
            "speed_knots": speed_knots,
            "course_deg": course_deg,
            "timestamp": timestamp,
            "fix_valid": status == "A",
            "fix_mode": mode or None,
        }

    def _parse_gga(self, fields: list[str]) -> Optional[Dict[str, Any]]:
        """Parse $GPGGA: time, position, fix quality, satellites, HDOP, altitude."""
        if len(fields) < 9:
            return None

        time_str = fields[0]
        lat = _parse_latlon(fields[1], fields[2], is_lat=True)
        lon = _parse_latlon(fields[3], fields[4], is_lat=False)
        fix_quality = _parse_int(fields[5])
        satellites = _parse_int(fields[6])
        hdop = _parse_float(fields[7])
        altitude = _parse_float(fields[8])

        time_obj = _parse_hms(time_str)
        timestamp = _combine_datetime(self._last_known_date, time_obj, self._fix.timestamp)

        return {
            "latitude": lat,
            "longitude": lon,
            "fix_quality": fix_quality,
            "satellites_in_use": satellites,
            "hdop": hdop,
            "altitude_m": altitude,
            "timestamp": timestamp,
            "fix_valid": (fix_quality or 0) > 0,
        }

    def _parse_vtg(self, fields: list[str]) -> Optional[Dict[str, Any]]:
        """Parse $GPVTG: course and ground speed."""
        if len(fields) < 7:
            return None

        course_deg = _parse_float(fields[0])
        speed_knots = _parse_float(fields[4])
        speed_kmh = _parse_float(fields[6])

        return {
            "course_deg": course_deg,
            "speed_knots": speed_knots,
            "speed_kmh": speed_kmh,
        }

    def _parse_gll(self, fields: list[str]) -> Optional[Dict[str, Any]]:
        """Parse $GPGLL: position, time, status."""
        if len(fields) < 5:
            return None

        lat = _parse_latlon(fields[0], fields[1], is_lat=True)
        lon = _parse_latlon(fields[2], fields[3], is_lat=False)
        time_obj = _parse_hms(fields[4])
        status = (fields[5] or "").upper() if len(fields) > 5 else ""
        timestamp = _combine_datetime(self._last_known_date, time_obj, self._fix.timestamp)

        return {
            "latitude": lat,
            "longitude": lon,
            "timestamp": timestamp,
            "fix_valid": status == "A",
        }

    def _parse_gsa(self, fields: list[str]) -> Optional[Dict[str, Any]]:
        """Parse $GPGSA: fix mode, PDOP, HDOP, VDOP."""
        if len(fields) < 17:
            return None

        fix_type = _parse_int(fields[1])
        pdop = _parse_float(fields[14]) if len(fields) > 14 else None
        hdop = _parse_float(fields[15]) if len(fields) > 15 else None
        vdop = _parse_float(fields[16]) if len(fields) > 16 else None

        fix_mode = FIX_MODE_MAP.get(fix_type or 0)

        return {
            "fix_mode": fix_mode,
            "pdop": pdop,
            "hdop": hdop,
            "vdop": vdop,
        }

    def _parse_gsv(self, fields: list[str]) -> Optional[Dict[str, Any]]:
        """Parse $GPGSV: satellites in view."""
        if len(fields) < 3:
            return None

        satellites_in_view = _parse_int(fields[2])

        return {"satellites_in_view": satellites_in_view}
