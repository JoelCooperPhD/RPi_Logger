"""GPS data types and structures."""

from dataclasses import dataclass
import datetime as dt
import time
from typing import Optional


@dataclass(slots=True)
class GPSFixSnapshot:
    """GPS fix data from NMEA sentences, updated incrementally."""

    timestamp: Optional[dt.datetime] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    altitude_m: Optional[float] = None
    speed_knots: Optional[float] = None
    speed_kmh: Optional[float] = None
    speed_mph: Optional[float] = None
    course_deg: Optional[float] = None
    fix_quality: Optional[int] = None
    fix_mode: Optional[str] = None
    satellites_in_use: Optional[int] = None
    satellites_in_view: Optional[int] = None
    hdop: Optional[float] = None
    vdop: Optional[float] = None
    pdop: Optional[float] = None
    fix_valid: bool = False
    last_sentence: Optional[str] = None
    raw_sentence: Optional[str] = None
    connected: bool = False
    error: Optional[str] = None
    last_update_monotonic: float = 0.0

    def age_seconds(self) -> Optional[float]:
        """Return seconds since last update, or None if never updated."""
        if not self.last_update_monotonic:
            return None
        return max(0.0, time.monotonic() - self.last_update_monotonic)

    def has_position(self) -> bool:
        """Return True if we have a valid position fix."""
        return (
            self.latitude is not None
            and self.longitude is not None
            and self.fix_valid
        )

    def copy(self) -> "GPSFixSnapshot":
        """Create a shallow copy of this snapshot."""
        return GPSFixSnapshot(
            timestamp=self.timestamp,
            latitude=self.latitude,
            longitude=self.longitude,
            altitude_m=self.altitude_m,
            speed_knots=self.speed_knots,
            speed_kmh=self.speed_kmh,
            speed_mph=self.speed_mph,
            course_deg=self.course_deg,
            fix_quality=self.fix_quality,
            fix_mode=self.fix_mode,
            satellites_in_use=self.satellites_in_use,
            satellites_in_view=self.satellites_in_view,
            hdop=self.hdop,
            vdop=self.vdop,
            pdop=self.pdop,
            fix_valid=self.fix_valid,
            last_sentence=self.last_sentence,
            raw_sentence=self.raw_sentence,
            connected=self.connected,
            error=self.error,
            last_update_monotonic=self.last_update_monotonic,
        )
