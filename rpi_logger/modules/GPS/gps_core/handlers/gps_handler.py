"""GPS Handler for standard NMEA GPS receivers.

This handler works with any GPS receiver that outputs standard NMEA sentences,
including the OzzMaker BerryGPS and similar UART-based receivers.
"""

from __future__ import annotations

import logging
from pathlib import Path

from .base_handler import BaseGPSHandler
from ..transports import BaseGPSTransport

logger = logging.getLogger(__name__)


class GPSHandler(BaseGPSHandler):
    """Handler for standard NMEA GPS receivers.

    This is the default handler that works with any GPS device outputting
    standard NMEA-0183 sentences. It supports:
    - $GPRMC - Recommended Minimum (position, speed, course, date/time)
    - $GPGGA - Fix Data (position, fix quality, satellites, altitude)
    - $GPVTG - Course Over Ground and Ground Speed
    - $GPGLL - Geographic Position
    - $GPGSA - DOP and Active Satellites
    - $GPGSV - Satellites in View

    Example:
        transport = SerialGPSTransport("/dev/serial0", 9600)
        await transport.connect()

        handler = GPSHandler("GPS:serial0", output_dir, transport)
        handler.data_callback = my_callback
        await handler.start()

        # Handler processes NMEA data in background
        # Access current fix via handler.fix

        await handler.stop()
    """

    def __init__(
        self,
        device_id: str,
        output_dir: Path,
        transport: BaseGPSTransport,
    ):
        """Initialize the GPS handler.

        Args:
            device_id: Unique identifier (e.g., "GPS:serial0")
            output_dir: Directory for data files
            transport: Transport for communication
        """
        super().__init__(device_id, output_dir, transport)

        # Track first valid fix for logging
        self._logged_first_fix = False

    def _process_sentence(self, sentence: str) -> None:
        """Process an NMEA sentence.

        Args:
            sentence: Raw NMEA sentence starting with '$'
        """
        # Parse the sentence (this updates self._parser.fix and calls callback)
        result = self._parser.parse_sentence(sentence)

        # Log first valid fix
        if result and not self._logged_first_fix:
            fix = self._parser.fix
            if fix.fix_valid and fix.latitude is not None:
                self._logged_first_fix = True
                logger.info(
                    "First GPS fix acquired for %s: lat=%.6f, lon=%.6f, satellites=%s",
                    self.device_id,
                    fix.latitude,
                    fix.longitude,
                    fix.satellites_in_use,
                )

    def reset_first_fix_logged(self) -> None:
        """Reset the first fix logged flag.

        Call this when starting a new session to log the first fix again.
        """
        self._logged_first_fix = False
