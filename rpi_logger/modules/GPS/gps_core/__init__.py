"""GPS core package - structured components for GPS module."""

from .constants import (
    TILE_SIZE,
    GRID_SIZE,
    MIN_ZOOM_LEVEL,
    MAX_ZOOM_LEVEL,
    KMH_PER_KNOT,
    MPH_PER_KNOT,
    MPS_PER_KNOT,
    FIX_QUALITY_DESCRIPTIONS,
    FIX_MODE_MAP,
    GPS_CSV_HEADER,
    DEFAULT_BAUD_RATE,
    DEFAULT_RECONNECT_DELAY,
    DEFAULT_NMEA_HISTORY,
)
from .parsers import GPSFixSnapshot, NMEAParser
from .transports import BaseGPSTransport, SerialGPSTransport
from .data_logger import GPSDataLogger
from .handlers import BaseGPSHandler, GPSHandler

__all__ = [
    # Constants
    "TILE_SIZE",
    "GRID_SIZE",
    "MIN_ZOOM_LEVEL",
    "MAX_ZOOM_LEVEL",
    "KMH_PER_KNOT",
    "MPH_PER_KNOT",
    "MPS_PER_KNOT",
    "FIX_QUALITY_DESCRIPTIONS",
    "FIX_MODE_MAP",
    "GPS_CSV_HEADER",
    "DEFAULT_BAUD_RATE",
    "DEFAULT_RECONNECT_DELAY",
    "DEFAULT_NMEA_HISTORY",
    # Types
    "GPSFixSnapshot",
    # Parser
    "NMEAParser",
    # Transport
    "BaseGPSTransport",
    "SerialGPSTransport",
    # Data Logger
    "GPSDataLogger",
    # Handlers
    "BaseGPSHandler",
    "GPSHandler",
]
