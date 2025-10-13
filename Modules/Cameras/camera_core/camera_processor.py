#!/usr/bin/env python3
"""
CAMERA PROCESSOR - Frame processing orchestrator.

This orchestrates the processing flow:
1. Receive frames from collator (awaits newest frame)
2. Convert RGB to BGR
3. Add frame number overlay to full-res frame (1920x1080)
4. Pass overlaid full-res frame to recorder (if recording)
5. Resize overlaid frame to preview size (640x360)
6. Pass to display manager

This is the "glue" that connects collator→display→recorder.
Frame number overlay is rendered ONCE at full resolution, then appears in both recording and preview.
"""

import asyncio
import functools
import logging
from pathlib import Path
from typing import Optional

import cv2

from .camera_utils import FrameTimingMetadata
from .camera_overlay import CameraOverlay
from .camera_display import CameraDisplay

logger = logging.getLogger("CameraProcessor")


class CameraProcessor:
    """
    Frame processor orchestrator.

    Receives frames from collator, orchestrates the flow through:
    collator → processor → overlay → display & recorder
    """

    def __init__(self, camera_id: int, args, overlay_config: dict, recording_manager,
                 capture_loop, collator_loop, session_dir: Path):
        self.camera_id = camera_id
        self.args = args
        self.recording_manager = recording_manager
        self.capture_loop = capture_loop
        self.collator_loop = collator_loop
        self.session_dir = session_dir
        self.logger = logging.getLogger(f"CameraProcessor{camera_id}")

        # Create overlay renderer and display manager
        self.overlay = CameraOverlay(camera_id, overlay_config)
        self.display = CameraDisplay(camera_id)

        # Control
        self._running = False
        self._task: Optional[asyncio.Task] = None

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
        """Stop the processor."""
        if not self._running:
            return
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self.logger.info("Camera processor stopped")

    async def _processing_loop(self):
        """
        PROCESSING LOOP

        Orchestrates: collator → overlay → recorder → resize → display
        (Frame number overlay rendered once at full-res, appears in both recording and preview)

        ALL blocking operations (cv2.cvtColor, overlay rendering, cv2.resize) are moved to
        executor threads to prevent blocking the async event loop and causing stuttering.
        """
        self.logger.info("Entering processing loop")
        loop = asyncio.get_event_loop()

        while self._running:
            try:
                # 1. Get frame from collator (blocking with timeout)
                frame_data = await self.collator_loop.get_frame()
                if frame_data is None:
                    # Brief sleep to prevent tight spinning when queue empty
                    await asyncio.sleep(0.001)
                    continue

                # Extract frame data
                raw_frame = frame_data['frame']
                metadata = frame_data['metadata']
                capture_time = frame_data['capture_time']
                capture_monotonic = frame_data.get('capture_monotonic')
                sensor_timestamp_ns = frame_data.get('sensor_timestamp_ns')
                hardware_fps = frame_data.get('hardware_fps', 0.0)
                collated_frame_num = frame_data['collated_frame_num']

                # Get frame number from hardware timing (most accurate)
                hardware_frame_number = None
                software_frame_index = None
                dropped_since_last = None

                if metadata:
                    # Debug: Log available metadata keys on first few frames
                    if collated_frame_num <= 3:
                        self.logger.info("Frame %d metadata keys: %s", collated_frame_num, list(metadata.keys()))

                    # Primary: Use HardwareFrameNumber (calculated from SensorTimestamp deltas)
                    hardware_frame_number = metadata.get("HardwareFrameNumber")
                    if hardware_frame_number is not None:
                        if collated_frame_num <= 3:
                            self.logger.info("Frame %d: Using HardwareFrameNumber=%d (timestamp-based)",
                                           collated_frame_num, hardware_frame_number)

                    # Also get software frame index for reference
                    software_frame_index = metadata.get("CaptureFrameIndex")

                    # Get pre-calculated dropped frame count from capture loop
                    dropped_since_last = metadata.get("DroppedSinceLast")
                    if dropped_since_last is not None and dropped_since_last > 0 and collated_frame_num <= 10:
                        self.logger.info("Frame %d: Hardware detected %d dropped frames (timestamp gap)",
                                       collated_frame_num, dropped_since_last)

                # Gather stats for overlay (fast, no blocking)
                capture_fps = self.capture_loop.get_fps()
                collation_fps = self.collator_loop.get_fps()
                captured_frames = self.capture_loop.get_frame_count()
                collated_frames = self.collator_loop.get_frame_count()

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
                    collation_fps,
                    captured_frames,
                    hardware_frame_number if hardware_frame_number is not None else collated_frames,  # Use hardware frame number
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
                        display_frame_index=hardware_frame_number if hardware_frame_number is not None else collated_frame_num,  # ESSENTIAL: Frame number
                        camera_frame_index=hardware_frame_number,  # DIAGNOSTIC: For logging
                        software_frame_index=software_frame_index,  # DIAGNOSTIC: For logging
                    )

                    # Submit metadata only (no frame pixels) - fire-and-forget
                    loop.run_in_executor(
                        None,
                        self.recording_manager.submit_frame,
                        None,  # No frame pixels - encoder handles recording
                        frame_metadata
                    )

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
