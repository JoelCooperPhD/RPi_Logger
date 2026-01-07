from dataclasses import dataclass
from typing import Any
import numpy as np


@dataclass(frozen=True, slots=True)
class CapturedFrame:
    data: np.ndarray
    frame_number: int
    sensor_timestamp_ns: int
    monotonic_ns: int
    wall_time: float
    color_format: str
    size: tuple[int, int]
    metadata: dict[str, Any]
    sequence_number: int

    @property
    def width(self) -> int:
        return self.size[0]

    @property
    def height(self) -> int:
        return self.size[1]

    @property
    def sensor_timestamp_s(self) -> float:
        return self.sensor_timestamp_ns / 1e9

    @property
    def monotonic_s(self) -> float:
        return self.monotonic_ns / 1e9
