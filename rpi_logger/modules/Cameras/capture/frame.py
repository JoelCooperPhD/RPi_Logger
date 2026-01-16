"""Frame and audio data structures."""

from dataclasses import dataclass
import numpy as np


@dataclass(frozen=True, slots=True)
class CapturedFrame:
    """Immutable video frame data from camera."""

    data: np.ndarray  # BGR image data
    frame_number: int  # Sequential frame number
    monotonic_time: float  # time.perf_counter() for cross-module sync
    wall_time: float  # Wall clock time (time.time())
    size: tuple[int, int]  # (width, height)


@dataclass(frozen=True, slots=True)
class AudioChunk:
    """Immutable audio chunk data."""

    data: np.ndarray  # Audio samples (float32)
    chunk_number: int  # Sequential chunk number
    monotonic_time: float  # time.perf_counter() for cross-module sync
    wall_time: float  # Wall clock time
    sample_rate: int  # Sample rate (Hz)
    channels: int  # Number of channels
    samples: int  # Number of samples in chunk
