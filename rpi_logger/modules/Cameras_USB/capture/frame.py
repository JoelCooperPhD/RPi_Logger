from dataclasses import dataclass
from typing import Any
import numpy as np


@dataclass(frozen=True, slots=True)
class CapturedFrame:
    data: np.ndarray
    frame_number: int
    capture_timestamp_ns: int
    monotonic_ns: int
    wall_time: float
    color_format: str
    size: tuple[int, int]
    sequence_number: int

    @property
    def width(self) -> int:
        return self.size[0]

    @property
    def height(self) -> int:
        return self.size[1]

    @property
    def capture_timestamp_s(self) -> float:
        return self.capture_timestamp_ns / 1e9

    @property
    def monotonic_s(self) -> float:
        return self.monotonic_ns / 1e9


@dataclass(frozen=True, slots=True)
class AudioChunk:
    data: np.ndarray
    chunk_number: int
    capture_timestamp_ns: int
    monotonic_ns: int
    wall_time: float
    sample_rate: int
    channels: int
    samples: int

    @property
    def duration_s(self) -> float:
        return self.samples / self.sample_rate
