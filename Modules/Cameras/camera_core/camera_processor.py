#!/usr/bin/env python3
"""
CAMERA PROCESSOR - Frame processing orchestrator.

This orchestrates the processing flow:
1. Poll capture loop for new frames directly
2. Convert RGB to BGR
3. Add frame number overlay to full-res frame (1920x1080)
4. Pass overlaid full-res frame to recorder (if recording)
5. Resize overlaid frame to preview size (640x360)
6. Pass to display manager

Simplified architecture: capture → processor → display & recorder
Frame number overlay is rendered ONCE at full resolution, then appears in both recording and preview.
"""

import asyncio
import functools
import logging
import time
from pathlib import Path
from typing import Optional

import cv2

from .camera_utils import FrameTimingMetadata, RollingFPS
from .camera_overlay import CameraOverlay
from .camera_display import CameraDisplay

logger = logging.getLogger("CameraProcessor")


class CameraProcessor:
    """
    Frame processor orchestrator.

    Polls capture loop directly, orchestrates the flow through:
    capture → processor → overlay → display & recorder
    """

    def __init__(self, camera_id: int, args, overlay_config: dict, recording_manager,
                 capture_loop, session_dir: Path):
        self.camera_id = camera_id
        self.args = args
        self.recording_manager = recording_manager
        self.capture_loop = capture_loop
        self.session_dir = session_dir
        self.logger = logging.getLogger(f"CameraProcessor{camera_id}")

        # Create overlay renderer and display manager
        self.overlay = CameraOverlay(camera_id, overlay_config)
        self.display = CameraDisplay(camera_id)

        # FPS tracking
        self.fps_tracker = RollingFPS(window_seconds=5.0)
        self.processed_frames = 0

        # Control
        self._running = False
        self._task: Optional[asyncio.Task] = None

        # Track background tasks for proper cleanup
        self._background_tasks: set[asyncio.Task] = set()

    async def _submit_frame_metadata_async(self, frame, metadata) -> None:
        """
        Async wrapper for submitting frame metadata to recording manager.

        This prevents blocking the processor loop while ensuring errors are logged.
        Uses run_in_executor for the synchronous submit_frame call.

        Args:
            frame: Frame data (typically None for hardware encoding)
            metadata: Frame timing metadata
        """
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
        """Wrapper for overlay rendering to work with run_in_executor."""
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
        """Start the processor."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._processing_loop())
        self.logger.info("Camera processor started")

    async def stop(self):
        """Stop the processor and wait for background tasks."""
        if not self._running:
            return
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        # Wait for background tasks to complete (with timeout)
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

    async def _processing_loop(self):
        """
        PROCESSING LOOP (Event-driven, zero-overhead)

        Orchestrates: capture → overlay → recorder → display
        (Frame number overlay rendered once at full-res, appears in both recording and preview)

        Event-driven architecture: waits for new frames from capture loop.
        No polling, no wasted CPU cycles. Immediate response to new frames.

        ALL blocking operations (cv2.cvtColor, overlay rendering) are moved to
        executor threads to prevent blocking the async event loop and causing stuttering.

        Performance:
        - Zero CPU waste (no polling)
        - Immediate frame processing (no 1ms polling delay)
        - 100% useful iterations (vs 3% with polling at 30 FPS)
        """
        self.logger.info("Entering processing loop (event-driven, zero-overhead)")
        loop = asyncio.get_event_loop()

        # Log first few frame waits for debugging
        log_waits = 3

        while self._running:
            try:
                # 1. Wait for new frame from capture loop (event-driven, blocks until ready)
                # This replaces the polling loop entirely
                if self.processed_frames < log_waits:
                    self.logger.info("Frame %d: Waiting for frame from capture loop...", self.processed_frames)

                try:
                    raw_frame, metadata, capture_time, capture_monotonic, sensor_timestamp_ns, _ = await self.capture_loop.wait_for_frame()

                    if self.processed_frames < log_waits:
                        self.logger.info("Frame %d: Received frame from capture loop", self.processed_frames)
                except asyncio.TimeoutError:
                    # No frame received within timeout - capture loop may be hung
                    # Log warning and continue waiting
                    self.logger.warning("No frame received from capture loop (10s timeout)")
                    continue

                # Skip if no frame available (should not happen with event-driven approach)
                if raw_frame is None:
                    self.logger.warning("Received None frame from capture loop")
                    continue

                # NEW FRAME - process it immediately
                self.processed_frames += 1
                self.fps_tracker.add_frame(time.time())

                # Get hardware FPS from capture loop
                hardware_fps = self.capture_loop.get_hardware_fps()

                # Get frame number from hardware timing (most accurate)
                hardware_frame_number = None
                software_frame_index = None
                dropped_since_last = None

                if metadata:
                    # Debug: Log available metadata keys on first few frames
                    if self.processed_frames <= 3:
                        self.logger.info("Frame %d metadata keys: %s", self.processed_frames, list(metadata.keys()))

                    # Primary: Use HardwareFrameNumber (calculated from SensorTimestamp deltas)
                    hardware_frame_number = metadata.get("HardwareFrameNumber")
                    if hardware_frame_number is not None:
                        if self.processed_frames <= 3:
                            self.logger.info("Frame %d: Using HardwareFrameNumber=%d (timestamp-based)",
                                           self.processed_frames, hardware_frame_number)

                    # Also get software frame index for reference
                    software_frame_index = metadata.get("CaptureFrameIndex")

                    # Get pre-calculated dropped frame count from capture loop
                    dropped_since_last = metadata.get("DroppedSinceLast")
                    if dropped_since_last is not None and dropped_since_last > 0 and self.processed_frames <= 10:
                        self.logger.info("Frame %d: Hardware detected %d dropped frames (timestamp gap)",
                                       self.processed_frames, dropped_since_last)

                # Gather stats for overlay (fast, no blocking)
                capture_fps = self.capture_loop.get_fps()
                processing_fps = self.fps_tracker.get_fps()
                captured_frames = self.capture_loop.get_frame_count()

                # 2. Skip color conversion - use frame directly
                # Lores is RGB888, and apparently OpenCV imshow on this platform shows it correctly
                # (The recording has correct colors, so RGB is working)
                frame_bgr = raw_frame

                # 3. Add frame number overlay to FULL-RES frame (IN EXECUTOR - non-blocking)
                # This ensures the overlay appears in both recording and preview
                # Use hardware_frame_number for the overlay (most accurate, timestamp-based)
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

                # 4. Submit metadata to recorder for CSV logging (if recording)
                # NOTE: With hardware H.264 encoding + post_callback overlay,
                # the recorder doesn't need frame pixels - encoder gets them directly.
                # We only submit metadata for CSV timing logs.
                if self.recording_manager.is_recording:
                    # Build metadata for CSV logging only
                    frame_metadata = FrameTimingMetadata(
                        sensor_timestamp_ns=sensor_timestamp_ns,  # ESSENTIAL: Hardware timestamp
                        dropped_since_last=dropped_since_last,  # ESSENTIAL: Drop detection
                        display_frame_index=hardware_frame_number if hardware_frame_number is not None else self.processed_frames,  # ESSENTIAL: Frame number
                        camera_frame_index=hardware_frame_number,  # DIAGNOSTIC: For logging
                        software_frame_index=software_frame_index,  # DIAGNOSTIC: For logging
                    )

                    # Submit metadata only (no frame pixels) - non-blocking with error handling
                    # Track task for proper cleanup
                    task = asyncio.create_task(
                        self._submit_frame_metadata_async(None, frame_metadata)
                    )
                    self._background_tasks.add(task)
                    task.add_done_callback(self._background_tasks.discard)

                # 5. Use frame directly - already at preview size from lores stream
                # No resize needed! Hardware ISP already scaled to preview resolution
                preview_frame = frame_with_overlay

                # 6. Update display manager (thread-safe, fast)
                self.display.update_frame(preview_frame)

            except asyncio.CancelledError:
                break
            except Exception as exc:
                if self._running:
                    self.logger.error("Processing error: %s", exc, exc_info=True)
                    await asyncio.sleep(0.1)

        self.logger.info("Exited processing loop")

    def get_display_frame(self):
        """
        Get latest display frame (called from main thread).

        This is the interface for camera_system.py to get frames for cv2.imshow().
        """
        return self.display.get_display_frame()
