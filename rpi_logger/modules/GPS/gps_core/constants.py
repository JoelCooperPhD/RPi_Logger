"""GPS/NMEA protocol constants and configuration defaults."""

# Map tile rendering
TILE_SIZE = 256
GRID_SIZE = 3  # produces a 768x768 view
MIN_ZOOM_LEVEL = 10.0
MAX_ZOOM_LEVEL = 15.0

# Speed conversion factors
KMH_PER_KNOT = 1.852
MPH_PER_KNOT = 1.15077945
MPS_PER_KNOT = 0.514444

# Fix mode mapping (from NMEA GSA sentence)
FIX_MODE_MAP = {
    1: "No fix",
    2: "2D",
    3: "3D",
}

# GPS CSV header (25 fields)
GPS_CSV_HEADER = [
    "trial",
    "module",
    "device_id",
    "label",
    "record_time_unix",
    "record_time_mono",
    "device_time_unix",
    "latitude_deg",
    "longitude_deg",
    "altitude_m",
    "speed_mps",
    "speed_kmh",
    "speed_knots",
    "speed_mph",
    "course_deg",
    "fix_quality",
    "fix_mode",
    "fix_valid",
    "satellites_in_use",
    "satellites_in_view",
    "hdop",
    "pdop",
    "vdop",
    "sentence_type",
    "raw_sentence",
]

# Default serial configuration
DEFAULT_BAUD_RATE = 9600
DEFAULT_RECONNECT_DELAY = 3.0
DEFAULT_NMEA_HISTORY = 30
DEFAULT_STALE_THRESHOLD = 5.0  # seconds without valid NMEA before fix_valid=False

# GPS fix quality descriptions (GGA sentence, field 6)
FIX_QUALITY_DESCRIPTIONS = {
    0: "Invalid",
    1: "GPS fix (SPS)",
    2: "DGPS fix",
    3: "PPS fix",
    4: "Real Time Kinematic",
    5: "Float RTK",
    6: "Estimated (dead reckoning)",
    7: "Manual input mode",
    8: "Simulation mode",
}


def get_fix_quality_description(quality: int | None) -> str | None:
    """Get human-readable description for GPS fix quality.

    Args:
        quality: GPS fix quality value (0-8) from GGA sentence

    Returns:
        Description string or None if quality is None
    """
    if quality is None:
        return None
    return FIX_QUALITY_DESCRIPTIONS.get(quality, f"Unknown ({quality})")
