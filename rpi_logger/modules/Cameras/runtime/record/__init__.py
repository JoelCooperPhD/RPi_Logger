"""Recording helpers (pipeline, recorder, CSV, timing, overlays)."""

from .pipeline import RecordPipeline
from .recorder import Recorder, RecorderHandle
from .csv_logger import CSVLogger, CSVRecord, CSV_HEADER
from .timing import FrameTimingTracker, FrameTimingUpdate, normalize_timestamp_ns
from .overlay import apply_overlay

__all__ = [
    "RecordPipeline",
    "Recorder",
    "RecorderHandle",
    "CSVLogger",
    "CSVRecord",
    "CSV_HEADER",
    "FrameTimingTracker",
    "FrameTimingUpdate",
    "normalize_timestamp_ns",
    "apply_overlay",
]
