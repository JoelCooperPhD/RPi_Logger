from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional

from rpi_logger.modules.Cameras.defaults import (
    DEFAULT_CAPTURE_RESOLUTION,
    DEFAULT_CAPTURE_FPS,
    DEFAULT_RECORD_FPS,
    DEFAULT_PREVIEW_SIZE,
    DEFAULT_PREVIEW_FPS,
    DEFAULT_PREVIEW_JPEG_QUALITY,
)


class WorkerState(Enum):
    STARTING = auto()
    IDLE = auto()
    PREVIEWING = auto()
    RECORDING = auto()
    STOPPING = auto()
    ERROR = auto()


# --- Commands (main process → worker) ---

@dataclass(slots=True)
class CmdConfigure:
    """Initial configuration sent after worker spawns."""
    camera_type: str  # "picam" or "usb"
    camera_id: str  # sensor_id or device path
    capture_resolution: tuple[int, int] = DEFAULT_CAPTURE_RESOLUTION
    capture_fps: float = DEFAULT_CAPTURE_FPS


@dataclass(slots=True)
class CmdStartPreview:
    """Start sending preview frames to main process."""
    preview_size: tuple[int, int] = DEFAULT_PREVIEW_SIZE
    target_fps: float = DEFAULT_PREVIEW_FPS
    jpeg_quality: int = DEFAULT_PREVIEW_JPEG_QUALITY


@dataclass(slots=True)
class CmdStopPreview:
    """Stop sending preview frames."""
    pass


@dataclass(slots=True)
class CmdStartRecord:
    """Start recording video to disk."""
    output_dir: str
    filename: str
    resolution: tuple[int, int] = DEFAULT_CAPTURE_RESOLUTION
    fps: float = DEFAULT_RECORD_FPS
    overlay_enabled: bool = True
    trial_number: Optional[int] = None
    csv_enabled: bool = True


@dataclass(slots=True)
class CmdStopRecord:
    """Stop recording and finalize video file."""
    pass


@dataclass(slots=True)
class CmdShutdown:
    """Gracefully shut down the worker process."""
    timeout_sec: float = 5.0


# --- Responses (worker → main process) ---

@dataclass(slots=True)
class RespReady:
    """Worker has initialized and is ready to receive commands."""
    camera_type: str
    camera_id: str
    capabilities: dict = field(default_factory=dict)


@dataclass(slots=True)
class RespPreviewFrame:
    """A preview frame for display in the UI."""
    frame_data: bytes  # JPEG-compressed
    width: int
    height: int
    timestamp: float  # unix time
    frame_number: int


@dataclass(slots=True)
class RespStateUpdate:
    """Periodic state update from worker."""
    state: WorkerState
    is_recording: bool
    is_previewing: bool
    fps_capture: float
    fps_encode: float
    frames_captured: int
    frames_recorded: int
    # Extended metrics for UI display
    fps_preview: float = 0.0
    target_record_fps: float = 0.0
    target_preview_fps: float = 0.0
    capture_queue_depth: int = 0
    encode_queue_depth: int = 0
    capture_wait_ms: float = 0.0
    error: Optional[str] = None


@dataclass(slots=True)
class RespRecordingStarted:
    """Confirmation that recording has started."""
    video_path: str
    csv_path: Optional[str]


@dataclass(slots=True)
class RespRecordingComplete:
    """Recording has finished and files are finalized."""
    video_path: str
    csv_path: Optional[str]
    frames_total: int
    duration_sec: float
    success: bool
    error: Optional[str] = None


@dataclass(slots=True)
class RespError:
    """An error occurred in the worker."""
    message: str
    fatal: bool = False  # if True, worker is shutting down


@dataclass(slots=True)
class RespShutdownAck:
    """Worker acknowledges shutdown and is exiting."""
    pass


# Type aliases for convenience
Command = (
    CmdConfigure
    | CmdStartPreview
    | CmdStopPreview
    | CmdStartRecord
    | CmdStopRecord
    | CmdShutdown
)

Response = (
    RespReady
    | RespPreviewFrame
    | RespStateUpdate
    | RespRecordingStarted
    | RespRecordingComplete
    | RespError
    | RespShutdownAck
)
