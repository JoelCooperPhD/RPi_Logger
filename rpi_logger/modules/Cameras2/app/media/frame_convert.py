"""Frame conversion utilities."""

from __future__ import annotations

import numpy as np


def ensure_uint8(frame) -> np.ndarray:
    """Ensure frame data is uint8 numpy array."""

    if isinstance(frame, np.ndarray):
        data = frame
    else:
        data = frame.data if hasattr(frame, "data") else frame
    if isinstance(data, np.ndarray):
        return data.astype(np.uint8, copy=False) if data.dtype != np.uint8 else data
    return np.array(data, dtype=np.uint8)
