
import math
from typing import List, Tuple


class AudioLevelMeter:

    def __init__(self, peak_hold_time: float = 2.0):
        self.current_rms = 0.0
        self.current_peak = 0.0
        self.peak_hold = 0.0
        self.peak_hold_timestamp = 0.0
        self.peak_hold_time = peak_hold_time
        self.dirty = False

    def add_samples(self, samples: List[float], timestamp: float):
        if not samples:
            return

        rms = math.sqrt(sum(s * s for s in samples) / len(samples))

        peak = max(abs(s) for s in samples)

        self.current_rms = rms
        self.current_peak = peak

        if peak > self.peak_hold:
            self.peak_hold = peak
            self.peak_hold_timestamp = timestamp

        if timestamp - self.peak_hold_timestamp > self.peak_hold_time:
            self.peak_hold = peak

        self.dirty = True

    def get_db_levels(self) -> Tuple[float, float]:
        # Convert to dB (with floor at -60 dB to avoid log(0))
        rms_db = 20 * math.log10(max(self.current_rms, 1e-6))
        peak_db = 20 * math.log10(max(self.peak_hold, 1e-6))

        return (rms_db, peak_db)

    def clear_dirty(self):
        self.dirty = False
