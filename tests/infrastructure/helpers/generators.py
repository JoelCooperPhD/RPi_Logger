"""Test data generators for Logger test suite.

Provides functions to generate valid test data for NMEA sentences,
CSV rows, and mock device responses. These generators ensure test data
is well-formed and follows the correct protocols.

Usage:
    from tests.infrastructure.helpers import generate_nmea_sentence, generate_csv_row

    nmea = generate_nmea_sentence(lat=48.1173, lon=11.5167)
    row = generate_csv_row(GPS_SCHEMA, latitude_deg=48.1173)
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Union

from tests.infrastructure.schemas.csv_schema import (
    CSVSchema,
    ColumnType,
    ColumnSpec,
    GPS_SCHEMA,
    DRT_SDRT_SCHEMA,
    DRT_WDRT_SCHEMA,
    VOG_SVOG_SCHEMA,
    VOG_WVOG_SCHEMA,
    EYETRACKER_GAZE_SCHEMA,
    EYETRACKER_IMU_SCHEMA,
    EYETRACKER_EVENTS_SCHEMA,
    NOTES_SCHEMA,
)


def _calculate_nmea_checksum(sentence: str) -> str:
    """Calculate NMEA checksum for a sentence.

    The checksum is XOR of all characters between $ and *.

    Args:
        sentence: NMEA sentence content (without $ prefix and *XX suffix).

    Returns:
        Two-character hex checksum string.

    Example:
        >>> _calculate_nmea_checksum("GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,47.0,M,,")
        '47'
    """
    checksum = 0
    for char in sentence:
        checksum ^= ord(char)
    return f"{checksum:02X}"


def generate_nmea_sentence(
    sentence_type: str = "GGA",
    lat: float = 48.1173,
    lon: float = 11.5167,
    alt: float = 545.4,
    speed_knots: float = 10.0,
    course: float = 84.4,
    fix_quality: int = 1,
    fix_valid: bool = True,
    satellites: int = 8,
    hdop: float = 0.9,
    pdop: float = 1.3,
    vdop: float = 1.1,
    timestamp: Optional[datetime] = None,
    date: Optional[datetime] = None,
    include_checksum: bool = True,
) -> str:
    """Generate a valid NMEA sentence.

    Supports GGA, RMC, VTG, GSA, and GLL sentence types. Generated sentences
    have valid checksums and follow NMEA 0183 format.

    Args:
        sentence_type: NMEA sentence type (GGA, RMC, VTG, GSA, GLL).
        lat: Latitude in decimal degrees (-90 to 90).
        lon: Longitude in decimal degrees (-180 to 180).
        alt: Altitude in meters.
        speed_knots: Speed in knots (for RMC/VTG).
        course: Course over ground in degrees (0-360).
        fix_quality: GPS fix quality (0=no fix, 1=GPS, 2=DGPS, etc.).
        fix_valid: Whether the fix is valid (for RMC).
        satellites: Number of satellites in use.
        hdop: Horizontal dilution of precision.
        pdop: Position dilution of precision (for GSA).
        vdop: Vertical dilution of precision (for GSA).
        timestamp: Time for sentence (default: current time).
        date: Date for sentence (default: current date).
        include_checksum: Whether to include the checksum (default True).

    Returns:
        Complete NMEA sentence with $ prefix, checksum, and CRLF terminator.

    Raises:
        ValueError: If sentence_type is not supported or coordinates are invalid.

    Example:
        >>> nmea = generate_nmea_sentence("GGA", lat=48.1173, lon=11.5167, alt=545.4)
        >>> nmea.startswith("$GPGGA")
        True
        >>> nmea.endswith("\\r\\n")
        True
    """
    if sentence_type not in ("GGA", "RMC", "VTG", "GSA", "GLL"):
        raise ValueError(f"Unsupported sentence type: {sentence_type}")

    if not -90 <= lat <= 90:
        raise ValueError(f"Latitude {lat} out of range [-90, 90]")
    if not -180 <= lon <= 180:
        raise ValueError(f"Longitude {lon} out of range [-180, 180]")

    ts = timestamp or datetime.utcnow()
    dt = date or datetime.utcnow()

    # Convert lat/lon to NMEA format (DDMM.MMMM)
    lat_deg = int(abs(lat))
    lat_min = (abs(lat) - lat_deg) * 60
    lat_dir = "N" if lat >= 0 else "S"
    lat_str = f"{lat_deg:02d}{lat_min:07.4f}"

    lon_deg = int(abs(lon))
    lon_min = (abs(lon) - lon_deg) * 60
    lon_dir = "E" if lon >= 0 else "W"
    lon_str = f"{lon_deg:03d}{lon_min:07.4f}"

    time_str = ts.strftime("%H%M%S")
    date_str = dt.strftime("%d%m%y")

    sentence: str

    if sentence_type == "GGA":
        # $GPGGA,time,lat,N/S,lon,E/W,quality,sats,hdop,alt,M,geoid,M,age,id*XX
        sentence = (
            f"GPGGA,{time_str},{lat_str},{lat_dir},{lon_str},{lon_dir},"
            f"{fix_quality},{satellites:02d},{hdop:.1f},{alt:.1f},M,47.0,M,,"
        )

    elif sentence_type == "RMC":
        # $GPRMC,time,status,lat,N/S,lon,E/W,speed,course,date,magvar,E/W*XX
        status = "A" if fix_valid else "V"
        sentence = (
            f"GPRMC,{time_str},{status},{lat_str},{lat_dir},{lon_str},{lon_dir},"
            f"{speed_knots:.1f},{course:.1f},{date_str},003.1,W"
        )

    elif sentence_type == "VTG":
        # $GPVTG,course_t,T,course_m,M,speed_n,N,speed_k,K*XX
        speed_kmh = speed_knots * 1.852
        sentence = (
            f"GPVTG,{course:.1f},T,{course:.1f},M,"
            f"{speed_knots:.1f},N,{speed_kmh:.1f},K"
        )

    elif sentence_type == "GSA":
        # $GPGSA,mode,fix,prn1,...,prn12,pdop,hdop,vdop*XX
        fix_mode = "3" if fix_quality > 0 else "1"
        # Generate some PRN numbers
        prns = ",".join(
            [f"{i:02d}" if i <= satellites else "" for i in range(1, 13)]
        )
        sentence = f"GPGSA,A,{fix_mode},{prns},{pdop:.1f},{hdop:.1f},{vdop:.1f}"

    elif sentence_type == "GLL":
        # $GPGLL,lat,N/S,lon,E/W,time,status*XX
        status = "A" if fix_valid else "V"
        sentence = f"GPGLL,{lat_str},{lat_dir},{lon_str},{lon_dir},{time_str},{status}"

    else:
        raise ValueError(f"Unsupported sentence type: {sentence_type}")

    if include_checksum:
        checksum = _calculate_nmea_checksum(sentence)
        return f"${sentence}*{checksum}\r\n"
    else:
        return f"${sentence}\r\n"


def _get_default_value(col_spec: ColumnSpec) -> str:
    """Generate a default value for a column based on its specification.

    Args:
        col_spec: Column specification.

    Returns:
        Default string value appropriate for the column type.
    """
    if col_spec.allowed_values:
        return str(col_spec.allowed_values[0])

    dtype = col_spec.dtype

    if dtype == ColumnType.INT:
        if col_spec.min_value is not None:
            return str(int(col_spec.min_value))
        return "1"

    elif dtype == ColumnType.FLOAT:
        if col_spec.min_value is not None and col_spec.max_value is not None:
            mid = (col_spec.min_value + col_spec.max_value) / 2
            return f"{mid:.6f}"
        elif col_spec.min_value is not None:
            return f"{col_spec.min_value:.6f}"
        return "0.0"

    elif dtype == ColumnType.TIMESTAMP_UNIX:
        return f"{time.time():.6f}"

    elif dtype == ColumnType.TIMESTAMP_MONO:
        return f"{time.monotonic():.6f}"

    elif dtype == ColumnType.TIMESTAMP_NS:
        return str(int(time.time_ns()))

    elif dtype == ColumnType.BOOL_INT:
        return "1"

    elif dtype == ColumnType.ISO_DATETIME:
        return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")

    elif dtype == ColumnType.STRING:
        return col_spec.name  # Use column name as default string

    return ""


def generate_csv_row(
    schema: CSVSchema,
    as_dict: bool = False,
    **overrides: Any,
) -> Union[List[str], Dict[str, str]]:
    """Generate a valid CSV row according to a schema.

    Creates a row with valid default values for all columns, then applies
    any overrides. The generated row will pass schema validation.

    Args:
        schema: The CSVSchema to generate a row for.
        as_dict: If True, return as dict with column names as keys.
        **overrides: Column values to override. Keys should match column names.

    Returns:
        List of string values (or dict if as_dict=True) representing a valid row.

    Raises:
        KeyError: If an override key doesn't match any column name.

    Example:
        >>> from tests.infrastructure.schemas.csv_schema import GPS_SCHEMA
        >>> row = generate_csv_row(GPS_SCHEMA, latitude_deg=48.1173, trial=1)
        >>> len(row) == GPS_SCHEMA.column_count
        True
        >>> row_dict = generate_csv_row(GPS_SCHEMA, as_dict=True, latitude_deg=48.1173)
        >>> row_dict['latitude_deg']
        '48.1173'
    """
    # Validate override keys
    column_names = {col.name for col in schema.columns}
    invalid_keys = set(overrides.keys()) - column_names
    if invalid_keys:
        raise KeyError(f"Invalid column names: {invalid_keys}. Valid columns: {column_names}")

    row_dict: Dict[str, str] = {}

    for col in schema.columns:
        if col.name in overrides:
            value = overrides[col.name]
            row_dict[col.name] = str(value) if value is not None else ""
        else:
            row_dict[col.name] = _get_default_value(col)

    if as_dict:
        return row_dict

    return [row_dict[col.name] for col in schema.columns]


def generate_csv_rows(
    schema: CSVSchema,
    count: int,
    time_increment: float = 1.0,
    start_mono: float = 100.0,
    start_unix: Optional[float] = None,
    **base_overrides: Any,
) -> List[List[str]]:
    """Generate multiple CSV rows with incrementing timestamps.

    Useful for generating test CSV files with realistic timing data.

    Args:
        schema: The CSVSchema to generate rows for.
        count: Number of rows to generate.
        time_increment: Time increment between rows (seconds).
        start_mono: Starting monotonic timestamp.
        start_unix: Starting unix timestamp (default: current time).
        **base_overrides: Base values to apply to all rows.

    Returns:
        List of rows, each row being a list of string values.

    Example:
        >>> rows = generate_csv_rows(GPS_SCHEMA, count=10, time_increment=0.1)
        >>> len(rows)
        10
    """
    start_unix = start_unix or time.time()
    rows: List[List[str]] = []

    for i in range(count):
        overrides = base_overrides.copy()
        overrides["record_time_mono"] = start_mono + (i * time_increment)
        overrides["record_time_unix"] = start_unix + (i * time_increment)

        row = generate_csv_row(schema, **overrides)
        rows.append(row)

    return rows


def generate_mock_device_response(
    device_type: str,
    **params: Any,
) -> bytes:
    """Generate a mock device response.

    Creates realistic response data for various device types. Useful for
    testing serial communication handlers without hardware.

    Args:
        device_type: Device type: "gps", "sdrt", "wdrt", "svog", "wvog".
        **params: Device-specific parameters (see below).

    GPS parameters:
        - lat: Latitude (-90 to 90)
        - lon: Longitude (-180 to 180)
        - alt: Altitude in meters
        - sentence_type: NMEA sentence type (default "GGA")

    DRT parameters (sDRT):
        - trial_number: Trial number
        - device_time_ms: Device timestamp in ms
        - responses: Number of responses
        - reaction_time_ms: Reaction time (-1 for timeout)

    DRT parameters (wDRT):
        - Same as sDRT plus:
        - battery_percent: Battery percentage (0-100)
        - device_unix: Device unix timestamp

    VOG parameters (sVOG):
        - trial_number: Trial number
        - open_ms: Shutter open time in ms
        - closed_ms: Shutter closed time in ms

    VOG parameters (wVOG):
        - Same as sVOG plus:
        - total_ms: Total shutter time
        - lens: Lens identifier (A/B/X)
        - battery_percent: Battery percentage
        - device_unix: Device unix timestamp

    Returns:
        Bytes containing the device response with appropriate line endings.

    Raises:
        ValueError: If device_type is not supported.

    Example:
        >>> response = generate_mock_device_response("gps", lat=48.1173, lon=11.5167)
        >>> response.startswith(b"$GP")
        True

        >>> response = generate_mock_device_response("sdrt", reaction_time_ms=250)
        >>> b"trl>" in response
        True
    """
    device_type = device_type.lower()

    if device_type == "gps":
        lat = params.get("lat", 48.1173)
        lon = params.get("lon", 11.5167)
        alt = params.get("alt", 545.4)
        sentence_type = params.get("sentence_type", "GGA")

        nmea = generate_nmea_sentence(
            sentence_type=sentence_type,
            lat=lat,
            lon=lon,
            alt=alt,
        )
        return nmea.encode("ascii")

    elif device_type == "sdrt":
        trial_number = params.get("trial_number", 1)
        device_time_ms = params.get("device_time_ms", int(time.time() * 1000) % 1000000)
        responses = params.get("responses", 1)
        reaction_time_ms = params.get("reaction_time_ms", 250)

        return f"trl>{trial_number},{device_time_ms},{responses},{reaction_time_ms}\r\n".encode()

    elif device_type == "wdrt":
        trial_number = params.get("trial_number", 1)
        device_time_ms = params.get("device_time_ms", int(time.time() * 1000) % 1000000)
        responses = params.get("responses", 1)
        reaction_time_ms = params.get("reaction_time_ms", 250)
        battery_percent = params.get("battery_percent", 85)
        device_unix = params.get("device_unix", int(time.time()))

        return (
            f"dta>{trial_number},{device_time_ms},{responses},{reaction_time_ms},"
            f"{battery_percent},{device_unix}\n"
        ).encode()

    elif device_type == "svog":
        trial_number = params.get("trial_number", 1)
        open_ms = params.get("open_ms", 1500)
        closed_ms = params.get("closed_ms", 1500)

        return f"data|{trial_number},{open_ms},{closed_ms}\r\n".encode()

    elif device_type == "wvog":
        trial_number = params.get("trial_number", 1)
        open_ms = params.get("open_ms", 1500)
        closed_ms = params.get("closed_ms", 1500)
        total_ms = params.get("total_ms", open_ms + closed_ms)
        lens = params.get("lens", "X")
        battery_percent = params.get("battery_percent", 85)
        device_unix = params.get("device_unix", int(time.time()))

        return (
            f"dta>{trial_number},{open_ms},{closed_ms},{total_ms},"
            f"{lens},{battery_percent},{device_unix}\n"
        ).encode()

    else:
        raise ValueError(
            f"Unsupported device type: {device_type}. "
            f"Supported types: gps, sdrt, wdrt, svog, wvog"
        )


def generate_mock_command_response(
    device_type: str,
    command: str,
) -> bytes:
    """Generate response to a device command.

    Args:
        device_type: Device type (sdrt, wdrt, svog, wvog).
        command: Command that was sent.

    Returns:
        Expected response bytes.

    Raises:
        ValueError: If device_type or command is not supported.

    Example:
        >>> response = generate_mock_command_response("sdrt", "exp_start")
        >>> response
        b'expStart\\r\\n'
    """
    device_type = device_type.lower()
    command = command.lower()

    responses = {
        "sdrt": {
            "exp_start": b"expStart\r\n",
            "exp_stop": b"expStop\r\n",
        },
        "wdrt": {
            "trl>1": b"trl>1\n",
            "trl>0": b"trl>0\n",
        },
        "svog": {
            "exp_start": b"expStart\r\n",
            ">do_expstart|<<": b"expStart\r\n",
            "exp_stop": b"expStop\r\n",
            ">do_expstop|<<": b"expStop\r\n",
            "trial_start": b"trialStart\r\n",
            ">do_trialstart|<<": b"trialStart\r\n",
        },
        "wvog": {
            "exp>1": b"exp>1\n",
            "exp>0": b"exp>0\n",
            "trl>1": b"trl>1\n",
            "trl>0": b"trl>0\n",
        },
    }

    if device_type not in responses:
        raise ValueError(f"Unsupported device type: {device_type}")

    device_responses = responses[device_type]
    if command not in device_responses:
        raise ValueError(
            f"Unknown command '{command}' for {device_type}. "
            f"Known commands: {list(device_responses.keys())}"
        )

    return device_responses[command]


def generate_gps_track(
    start_lat: float = 48.1173,
    start_lon: float = 11.5167,
    points: int = 10,
    bearing: float = 45.0,
    speed_mps: float = 10.0,
    interval_seconds: float = 1.0,
) -> List[Dict[str, float]]:
    """Generate a GPS track with realistic movement.

    Creates a sequence of GPS coordinates representing movement
    in a straight line.

    Args:
        start_lat: Starting latitude.
        start_lon: Starting longitude.
        points: Number of track points.
        bearing: Direction of travel in degrees (0=North, 90=East).
        speed_mps: Speed in meters per second.
        interval_seconds: Time interval between points.

    Returns:
        List of dicts with lat, lon, speed, bearing for each point.

    Example:
        >>> track = generate_gps_track(points=5, bearing=90)
        >>> len(track)
        5
        >>> track[0]['lat']
        48.1173
    """
    import math

    EARTH_RADIUS_M = 6371000  # meters
    track: List[Dict[str, float]] = []

    distance_per_point = speed_mps * interval_seconds
    bearing_rad = math.radians(bearing)

    current_lat = math.radians(start_lat)
    current_lon = math.radians(start_lon)

    for i in range(points):
        # Add current point
        track.append({
            "lat": math.degrees(current_lat),
            "lon": math.degrees(current_lon),
            "speed_mps": speed_mps,
            "bearing": bearing,
        })

        # Calculate next position using haversine formula
        angular_distance = distance_per_point / EARTH_RADIUS_M

        new_lat = math.asin(
            math.sin(current_lat) * math.cos(angular_distance) +
            math.cos(current_lat) * math.sin(angular_distance) * math.cos(bearing_rad)
        )

        new_lon = current_lon + math.atan2(
            math.sin(bearing_rad) * math.sin(angular_distance) * math.cos(current_lat),
            math.cos(angular_distance) - math.sin(current_lat) * math.sin(new_lat)
        )

        current_lat = new_lat
        current_lon = new_lon

    return track
