"""Per-camera slot state used by the Cameras controller."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from ..domain.pipelines import FrameTimingTracker, ImagePipeline
from ..domain.model import CapturedFrame, FrameGate, FramePayload
from ..io.storage import CameraStoragePipeline
from ..logging_utils import get_module_logger

logger = get_module_logger(__name__)


@dataclass(slots=True)
class CameraSlot:
    """Aggregates preview, storage, and pipeline state for a single camera."""

    index: int
    camera: Any
    frame: Any
    holder: Any
    label: Any
    size: tuple[int, int]
    title: str
    main_format: str = ""
    preview_format: str = ""
    main_size: Optional[tuple[int, int]] = None
    preview_stream: str = "main"
    main_stream: str = "main"
    preview_stream_size: Optional[tuple[int, int]] = None
    capture_queue: Optional[asyncio.Queue[Optional[CapturedFrame]]] = field(default=None, repr=False)
    preview_queue: Optional[asyncio.Queue[FramePayload]] = field(default=None, repr=False)
    storage_queue: Optional[asyncio.Queue[FramePayload]] = field(default=None, repr=False)
    save_size: Optional[tuple[int, int]] = None
    photo: Optional[Any] = field(default=None, repr=False)
    preview_gate: FrameGate = field(default_factory=FrameGate, repr=False)
    preview_stride: int = 1
    preview_stride_offset: int = 0
    frame_rate_gate: FrameGate = field(default_factory=FrameGate, repr=False)
    first_frame_event: asyncio.Event = field(default_factory=asyncio.Event, repr=False)
    capture_fps: float = 0.0
    process_fps: float = 0.0
    preview_fps: float = 0.0
    storage_fps: float = 0.0
    image_pipeline: Optional[ImagePipeline] = field(default=None, repr=False)
    capture_task: Optional[asyncio.Task] = field(default=None, repr=False)
    router_task: Optional[asyncio.Task] = field(default=None, repr=False)
    preview_task: Optional[asyncio.Task] = field(default=None, repr=False)
    storage_task: Optional[asyncio.Task] = field(default=None, repr=False)
    saving_active: bool = False
    preview_enabled: bool = True
    frame_duration_us: Optional[int] = None
    was_resizing: bool = False
    capture_main_stream: bool = False
    timing_tracker: FrameTimingTracker = field(default_factory=FrameTimingTracker, repr=False)
    capture_index: int = 0
    last_hardware_fps: float = 0.0
    last_expected_interval_ns: Optional[int] = None
    storage_pipeline: Optional[CameraStoragePipeline] = field(default=None, repr=False)
    storage_drop_since_last: int = 0
    storage_drop_total: int = 0
    storage_queue_size: int = 1
    last_video_frame_count: int = 0
    video_stall_frames: int = 0
    last_video_fps: float = 0.0
    last_observed_fps: float = 0.0
    session_camera_dir: Optional[Path] = field(default=None, repr=False)
    slow_capture_warnings: int = 0
    capture_paused: bool = False
    capture_active_event: asyncio.Event = field(default_factory=asyncio.Event, repr=False)
    capture_idle_event: asyncio.Event = field(default_factory=asyncio.Event, repr=False)

    def __post_init__(self) -> None:
        # capture_active_event defaults to "running" so the capture loop can start immediately.
        if not self.capture_active_event.is_set():
            self.capture_active_event.set()
        # idle event stays cleared until the capture loop voluntarily pauses.
        if self.capture_idle_event.is_set():
            self.capture_idle_event.clear()

    def attach_queues(
        self,
        *,
        capture_queue: Optional[asyncio.Queue[Optional[CapturedFrame]]],
        preview_queue: Optional[asyncio.Queue[FramePayload]],
        storage_queue: Optional[asyncio.Queue[FramePayload]],
    ) -> None:
        self.capture_queue = capture_queue
        self.preview_queue = preview_queue
        self.storage_queue = storage_queue
        logger.debug(
            "CameraSlot queues attached | index=%s capture=%s preview=%s storage=%s",
            self.index,
            bool(capture_queue),
            bool(preview_queue),
            bool(storage_queue),
        )

    def reset_pipeline(self) -> None:
        self.capture_task = None
        self.router_task = None
        self.preview_task = None
        self.storage_task = None
        self.image_pipeline = None
        logger.debug("CameraSlot pipeline reset | index=%s", self.index)

__all__ = ["CameraSlot"]
