#!/usr/bin/env python3
"""
CAMERA PROCESSOR - Frame processing orchestrator.

This orchestrates the processing flow:
1. Receive frames from collator
2. Convert RGB to BGR
3. Pass to overlay renderer → get frame with overlays
4. Resize for preview
5. Pass to display manager
6. Pass to recorder (if recording)

This is the "glue" that connects collator→overlay→display→recorder.
"""

import asyncio
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

        Orchestrates: collator → overlay → display → recorder
        """
        self.logger.info("Entering processing loop")

        while self._running:
            try:
                # 1. Get frame from collator (blocking with timeout)
                frame_data = await self.collator_loop.get_frame()
                if frame_data is None:
                    continue

                # Extract frame data
                raw_frame = frame_data['frame']
                metadata = frame_data['metadata']
                capture_time = frame_data['capture_time']
                hardware_fps = frame_data.get('hardware_fps', 0.0)
                collated_frame_num = frame_data['collated_frame_num']

                # 2. Convert RGB to BGR for OpenCV
                frame_bgr = cv2.cvtColor(raw_frame, cv2.COLOR_RGB2BGR)

                # Get sequence number
                sequence = None
                if metadata:
                    sequence = metadata.get("Sequence")
                    if sequence is not None:
                        try:
                            sequence = int(sequence)
                        except (TypeError, ValueError):
                            sequence = None

                # Get metrics from loops
                capture_fps = self.capture_loop.get_fps()
                collation_fps = self.collator_loop.get_fps()
                captured_frames = self.capture_loop.get_frame_count()
                collated_frames = self.collator_loop.get_frame_count()

                # 3. Add overlays
                frame_with_overlays = self.overlay.add_overlays(
                    frame_bgr,
                    capture_fps=hardware_fps,  # Use hardware FPS from camera sensor
                    collation_fps=collation_fps,
                    captured_frames=captured_frames,
                    collated_frames=collated_frames,
                    requested_fps=float(self.args.fps),
                    is_recording=self.recording_manager.is_recording,
                    recording_filename=self.recording_manager.video_path.name if self.recording_manager.video_path else None,
                    recorded_frames=self.recording_manager.written_frames,
                    session_name=self.session_dir.name,
                )

                # 4. Resize for preview
                preview_frame = cv2.resize(
                    frame_with_overlays,
                    (self.args.preview_width, self.args.preview_height)
                )

                # 5. Update display manager (thread-safe)
                self.display.update_frame(preview_frame)

                # 6. Submit to recorder (if recording)
                if self.recording_manager.is_recording:
                    # Build metadata for recorder
                    frame_metadata = FrameTimingMetadata(
                        capture_monotonic=None,
                        capture_unix=capture_time if capture_time else None,
                        camera_frame_index=sequence,
                        display_frame_index=collated_frame_num,
                        dropped_frames_total=None,
                        duplicates_total=None,
                        available_camera_fps=capture_fps,
                        requested_fps=float(self.args.fps),
                    )

                    await asyncio.get_event_loop().run_in_executor(
                        None,
                        self.recording_manager.submit_frame,
                        frame_with_overlays,  # Submit full-res with overlays
                        frame_metadata
                    )

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
