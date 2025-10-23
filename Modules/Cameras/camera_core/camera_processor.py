
import asyncio
import functools
import logging
import time
from pathlib import Path
from typing import Optional

import cv2

from .camera_utils import FrameTimingMetadata, RollingFPS
from .display import FrameCache, CameraOverlay

logger = logging.getLogger(__name__)


class CameraProcessor:

    def __init__(self, camera_id: int, args, overlay_config: dict, recording_manager,
                 capture_loop, session_dir: Path):
        self.camera_id = camera_id
        self.args = args
        self.recording_manager = recording_manager
        self.capture_loop = capture_loop
        self.session_dir = session_dir
        self.logger = logging.getLogger(f"CameraProcessor{camera_id}")

        self.overlay = CameraOverlay(camera_id, overlay_config)
        self.display = FrameCache(camera_id)

        self.fps_tracker = RollingFPS(window_seconds=5.0)
        self.processed_frames = 0

        self._running = False
        self._paused = False  # Pause state for CPU saving
        self._task: Optional[asyncio.Task] = None

        self._background_tasks: set[asyncio.Task] = set()

    async def _submit_frame_metadata_async(self, frame, metadata) -> None:
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                self.recording_manager.submit_frame,
                frame,
                metadata
            )
        except Exception as exc:
            self.logger.error("Error submitting frame metadata: %s", exc)

    def _add_overlays_wrapper(self, frame, capture_fps, collation_fps, captured_frames,
                              collated_frames, requested_fps, is_recording, recording_filename,
                              recorded_frames, session_name):
        return self.overlay.add_overlays(
            frame,
            capture_fps=capture_fps,
            collation_fps=collation_fps,
            captured_frames=captured_frames,
            collated_frames=collated_frames,
            requested_fps=requested_fps,
            is_recording=is_recording,
            recording_filename=recording_filename,
            recorded_frames=recorded_frames,
            session_name=session_name,
        )

    async def start(self):
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._processing_loop())
        self.logger.info("Camera processor started")

    async def stop(self):
        if not self._running:
            return
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        if self._background_tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*self._background_tasks, return_exceptions=True),
                    timeout=2.0
                )
            except asyncio.TimeoutError:
                self.logger.warning("Background tasks did not complete within 2 seconds")
            self._background_tasks.clear()

        self.logger.info("Camera processor stopped")

    async def pause(self):
        if not self._paused:
            self._paused = True
            self.logger.info("Camera %d processor paused (CPU saving mode)", self.camera_id)

    async def resume(self):
        if self._paused:
            self._paused = False
            self.logger.info("Camera %d processor resumed", self.camera_id)

    async def _processing_loop(self):
        self.logger.info("Entering processing loop (event-driven, zero-overhead)")
        loop = asyncio.get_event_loop()

        # Log first few frame waits for debugging
        log_waits = 3

        while self._running:
            try:
                if self._paused:
                    await asyncio.sleep(0.1)  # Idle sleep, minimal CPU
                    continue

                # 1. Wait for new frame from capture loop (event-driven, blocks until ready)
                if self.processed_frames < log_waits:
                    self.logger.info("Frame %d: Waiting for frame from capture loop...", self.processed_frames)

                try:
                    raw_frame, metadata, capture_time, capture_monotonic, sensor_timestamp_ns, _ = await self.capture_loop.wait_for_frame()

                    if self.processed_frames < log_waits:
                        self.logger.info("Frame %d: Received frame from capture loop", self.processed_frames)
                except asyncio.TimeoutError:
                    self.logger.warning("No frame received from capture loop (10s timeout)")
                    continue

                # Skip if no frame available (should not happen with event-driven approach)
                if raw_frame is None:
                    self.logger.warning("Received None frame from capture loop")
                    continue

                self.processed_frames += 1
                self.fps_tracker.add_frame(time.time())

                hardware_fps = self.capture_loop.get_hardware_fps()

                # Get frame number from hardware timing (most accurate)
                hardware_frame_number = None
                software_frame_index = None
                dropped_since_last = None

                if metadata:
                    # Debug: Log available metadata keys on first few frames
                    if self.processed_frames <= 3:
                        self.logger.info("Frame %d metadata keys: %s", self.processed_frames, list(metadata.keys()))

                    hardware_frame_number = metadata.get("HardwareFrameNumber")
                    if hardware_frame_number is not None:
                        if self.processed_frames <= 3:
                            self.logger.info("Frame %d: Using HardwareFrameNumber=%d (timestamp-based)",
                                           self.processed_frames, hardware_frame_number)

                    software_frame_index = metadata.get("CaptureFrameIndex")

                    dropped_since_last = metadata.get("DroppedSinceLast")
                    if dropped_since_last is not None and dropped_since_last > 0 and self.processed_frames <= 10:
                        self.logger.info("Frame %d: Hardware detected %d dropped frames (timestamp gap)",
                                       self.processed_frames, dropped_since_last)

                capture_fps = self.capture_loop.get_fps()
                processing_fps = self.fps_tracker.get_fps()
                captured_frames = self.capture_loop.get_frame_count()

                frame_bgr = raw_frame

                overlay_fn = functools.partial(
                    self._add_overlays_wrapper,
                    frame_bgr,
                    hardware_fps,
                    processing_fps,
                    captured_frames,
                    hardware_frame_number if hardware_frame_number is not None else self.processed_frames,  # Use hardware frame number
                    float(self.args.fps),
                    self.recording_manager.is_recording,
                    self.recording_manager.video_path.name if self.recording_manager.video_path else None,
                    self.recording_manager.written_frames,
                    self.session_dir.name if self.session_dir else "no_session",
                )
                frame_with_overlay = await loop.run_in_executor(None, overlay_fn)

                # We only submit metadata for CSV timing logs.
                if self.recording_manager.is_recording:
                    frame_metadata = FrameTimingMetadata(
                        sensor_timestamp_ns=sensor_timestamp_ns,  # ESSENTIAL: Hardware timestamp
                        dropped_since_last=dropped_since_last,  # ESSENTIAL: Drop detection
                        display_frame_index=hardware_frame_number if hardware_frame_number is not None else self.processed_frames,  # ESSENTIAL: Frame number
                        camera_frame_index=hardware_frame_number,  # DIAGNOSTIC: For logging
                        software_frame_index=software_frame_index,  # DIAGNOSTIC: For logging
                    )

                    task = asyncio.create_task(
                        self._submit_frame_metadata_async(None, frame_metadata)
                    )
                    self._background_tasks.add(task)
                    task.add_done_callback(self._background_tasks.discard)

                preview_frame = frame_with_overlay

                self.display.update_frame(preview_frame)

            except asyncio.CancelledError:
                break
            except Exception as exc:
                if self._running:
                    self.logger.error("Processing error: %s", exc, exc_info=True)
                    await asyncio.sleep(0.1)

        self.logger.info("Exited processing loop")

    def get_display_frame(self):
        return self.display.get_display_frame()
