"""Recording helpers (CSV, timing, overlays).

Note: The main recording logic is now in worker/encoder.py.
These utilities are kept for compatibility and may be used by workers.
"""
from .csv_logger import CSVLogger, CSVRecord, CSV_HEADER
from .timing import FrameTimingTracker, FrameTimingUpdate, normalize_timestamp_ns
from .overlay import apply_overlay

__all__ = [
    "CSVLogger",
    "CSVRecord",
    "CSV_HEADER",
    "FrameTimingTracker",
    "FrameTimingUpdate",
    "normalize_timestamp_ns",
    "apply_overlay",
]
