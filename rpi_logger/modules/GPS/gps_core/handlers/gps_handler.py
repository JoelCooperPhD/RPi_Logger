"""GPS Handler for standard NMEA GPS receivers (BerryGPS, etc)."""

from __future__ import annotations

from pathlib import Path

from rpi_logger.core.logging_utils import get_module_logger
from .base_handler import BaseGPSHandler
from ..transports import BaseGPSTransport

logger = get_module_logger(__name__)


class GPSHandler(BaseGPSHandler):
    """Default handler for NMEA-0183 receivers (RMC, GGA, VTG, GLL, GSA, GSV)."""

    def __init__(self, device_id: str, output_dir: Path, transport: BaseGPSTransport):
        """Initialize GPS handler."""
        super().__init__(device_id, output_dir, transport)
        self._logged_first_fix = False

    def _process_sentence(self, sentence: str) -> None:
        """Process NMEA sentence and log first valid fix."""
        result = self._parser.parse_sentence(sentence)
        if result and not self._logged_first_fix:
            fix = self._parser.fix
            if fix.fix_valid and fix.latitude is not None:
                self._logged_first_fix = True
                logger.info(
                    "First GPS fix acquired for %s: lat=%.6f, lon=%.6f, satellites=%s",
                    self.device_id, fix.latitude, fix.longitude, fix.satellites_in_use
                )

    def reset_first_fix_logged(self) -> None:
        """Reset first fix logged flag for new session."""
        self._logged_first_fix = False
