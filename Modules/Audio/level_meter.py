"""Audio level metering helpers for the module view."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Iterable, Tuple

import numpy as np

from .constants import DB_MAX, DB_MIN


@dataclass(slots=True)
class LevelMeter:
    """Track RMS/peak levels for a single audio stream."""

    peak_hold_time: float = 2.0
    _rms_db: float = field(init=False, default=DB_MIN)
    _peak_db: float = field(init=False, default=DB_MIN)
    _peak_timestamp: float = field(init=False, default=0.0)
    dirty: bool = field(init=False, default=False)

    def __post_init__(self) -> None:
        self._rms_db: float = DB_MIN
        self._peak_db: float = DB_MIN
        self._peak_timestamp: float = 0.0
        self.dirty: bool = False

    def add_samples(self, samples: Iterable[float], timestamp: float | None = None) -> None:
        array = np.asarray(samples, dtype=np.float32)
        if array.size == 0:
            return

        rms = float(np.sqrt(np.mean(np.square(array), dtype=np.float32)))
        peak = float(np.max(np.abs(array)))
        now = timestamp or time.time()

        if rms > 0:
            self._rms_db = self._to_db(rms)
        else:
            self._rms_db = DB_MIN

        if peak > 0:
            peak_db = self._to_db(peak)
            if peak_db >= self._peak_db or (now - self._peak_timestamp) > self.peak_hold_time:
                self._peak_db = peak_db
                self._peak_timestamp = now
        elif (now - self._peak_timestamp) > self.peak_hold_time:
            self._peak_db = DB_MIN
            self._peak_timestamp = now

        self.dirty = True

    def get_db_levels(self) -> Tuple[float, float]:
        return self._rms_db, self._peak_db

    def clear_dirty(self) -> None:
        self.dirty = False

    @staticmethod
    def _to_db(value: float) -> float:
        if value <= 0:
            return DB_MIN
        return max(DB_MIN, min(DB_MAX, 20.0 * math.log10(value)))
