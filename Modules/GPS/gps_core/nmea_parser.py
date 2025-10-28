import logging
from typing import Optional, Dict, Any
from datetime import datetime

logger = logging.getLogger(__name__)


class NMEAParser:

    def __init__(self):
        self.last_gga = None
        self.last_rmc = None
        self.last_gsa = None

    def parse_sentence(self, sentence: str) -> Optional[str]:
        if not sentence.startswith('$'):
            return None

        try:
            sentence = sentence.strip()

            if sentence.startswith('$GPGGA') or sentence.startswith('$GNGGA'):
                self.last_gga = self._parse_gga(sentence)
                return 'GGA'
            elif sentence.startswith('$GPRMC') or sentence.startswith('$GNRMC'):
                self.last_rmc = self._parse_rmc(sentence)
                return 'RMC'
            elif sentence.startswith('$GPGSA') or sentence.startswith('$GNGSA'):
                self.last_gsa = self._parse_gsa(sentence)
                return 'GSA'

        except Exception as e:
            logger.debug("Error parsing NMEA: %s - %s", sentence, e)

        return None

    def get_latest_data(self) -> Dict[str, Any]:
        data = {
            'latitude': 0.0,
            'longitude': 0.0,
            'altitude': 0.0,
            'speed_kmh': 0.0,
            'heading': 0.0,
            'satellites': 0,
            'fix_quality': 0,
            'hdop': 99.9,
            'timestamp': 0.0
        }

        if self.last_gga:
            data.update({
                'latitude': self.last_gga.get('latitude', 0.0),
                'longitude': self.last_gga.get('longitude', 0.0),
                'altitude': self.last_gga.get('altitude', 0.0),
                'satellites': self.last_gga.get('satellites', 0),
                'fix_quality': self.last_gga.get('fix_quality', 0),
                'hdop': self.last_gga.get('hdop', 99.9),
                'timestamp': self.last_gga.get('timestamp', 0.0)
            })

        if self.last_rmc:
            data.update({
                'speed_kmh': self.last_rmc.get('speed_kmh', 0.0),
                'heading': self.last_rmc.get('heading', 0.0)
            })

        return data

    def _parse_gga(self, sentence: str) -> Dict[str, Any]:
        fields = sentence.split(',')

        try:
            lat = self._parse_coordinate(fields[2], fields[3])
            lon = self._parse_coordinate(fields[4], fields[5])
            fix_quality = int(fields[6]) if fields[6] else 0
            satellites = int(fields[7]) if fields[7] else 0
            hdop = float(fields[8]) if fields[8] else 99.9
            altitude = float(fields[9]) if fields[9] else 0.0

            return {
                'latitude': lat,
                'longitude': lon,
                'fix_quality': fix_quality,
                'satellites': satellites,
                'hdop': hdop,
                'altitude': altitude,
                'timestamp': datetime.now().timestamp()
            }
        except (IndexError, ValueError) as e:
            logger.debug("Error parsing GGA: %s", e)
            return {}

    def _parse_rmc(self, sentence: str) -> Dict[str, Any]:
        fields = sentence.split(',')

        try:
            speed_knots = float(fields[7]) if fields[7] else 0.0
            speed_kmh = speed_knots * 1.852
            heading = float(fields[8]) if fields[8] else 0.0

            return {
                'speed_kmh': speed_kmh,
                'heading': heading
            }
        except (IndexError, ValueError) as e:
            logger.debug("Error parsing RMC: %s", e)
            return {}

    def _parse_gsa(self, sentence: str) -> Dict[str, Any]:
        fields = sentence.split(',')

        try:
            pdop = float(fields[15]) if fields[15] else 99.9
            hdop = float(fields[16]) if fields[16] else 99.9
            vdop = float(fields[17].split('*')[0]) if fields[17] else 99.9

            return {
                'pdop': pdop,
                'hdop': hdop,
                'vdop': vdop
            }
        except (IndexError, ValueError) as e:
            logger.debug("Error parsing GSA: %s", e)
            return {}

    def _parse_coordinate(self, coord_str: str, direction: str) -> float:
        if not coord_str or not direction:
            return 0.0

        coord = float(coord_str)
        degrees = int(coord / 100)
        minutes = coord - (degrees * 100)
        decimal = degrees + (minutes / 60)

        if direction in ['S', 'W']:
            decimal = -decimal

        return decimal
