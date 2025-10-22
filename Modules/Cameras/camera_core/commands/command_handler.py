#!/usr/bin/env python3
"""
Command handler for camera system.

Processes commands received from master in slave mode.
"""

import asyncio
import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict

import cv2

if TYPE_CHECKING:
    from ..camera_system import CameraSystem

from logger_core.commands import BaseCommandHandler, StatusMessage


class CommandHandler(BaseCommandHandler):
    """Handles command execution for camera system."""

    def __init__(self, camera_system: 'CameraSystem', gui=None):
        """
        Initialize command handler.

        Args:
            camera_system: Reference to CameraSystem instance
            gui: Optional reference to TkinterGUI instance (for get_geometry)
        """
        super().__init__(camera_system, gui=gui)

    async def handle_start_recording(self, command_data: Dict[str, Any]) -> None:
        """Handle start_recording command."""
        if self._check_recording_state(should_be_recording=False):
            session_dir = self.system._ensure_session_dir()
            for cam in self.system.cameras:
                cam.start_recording(session_dir)
            self.system.recording = True
            StatusMessage.send(
                "recording_started",
                {
                    "session": self.system.session_label,
                    "files": [
                        str(cam.recording_manager.video_path)
                        for cam in self.system.cameras
                        if cam.recording_manager.video_path
                    ],
                },
            )

    async def handle_stop_recording(self, command_data: Dict[str, Any]) -> None:
        """Handle stop_recording command."""
        if self._check_recording_state(should_be_recording=True):
            for cam in self.system.cameras:
                cam.stop_recording()
            self.system.recording = False
            StatusMessage.send(
                "recording_stopped",
                {
                    "session": self.system.session_label,
                    "files": [
                        str(cam.recording_manager.video_path)
                        for cam in self.system.cameras
                        if cam.recording_manager.video_path is not None
                    ],
                },
            )

    async def handle_take_snapshot(self, command_data: Dict[str, Any]) -> None:
        """Handle take_snapshot command (async)."""
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        session_dir = self.system._ensure_session_dir()

        # Collect frames first (fast)
        frames_to_save = []
        for i, cam in enumerate(self.system.cameras):
            frame = cam.update_preview_cache()
            if frame is not None:
                filename = session_dir / f"snapshot_cam{i}_{ts}.jpg"
                frames_to_save.append((str(filename), frame.copy()))  # Copy to avoid race conditions

        # Save all frames concurrently using executor (non-blocking)
        loop = asyncio.get_event_loop()

        async def save_frame(filename: str, frame) -> tuple[str, bool]:
            """Save a single frame asynchronously."""
            try:
                await loop.run_in_executor(None, cv2.imwrite, filename, frame)
                self.logger.info("Saved snapshot %s", filename)
                return (filename, True)
            except Exception as e:
                self.logger.error("Failed to save snapshot %s: %s", filename, e)
                return (filename, False)

        # Run all saves concurrently with timeout
        try:
            results = await asyncio.wait_for(
                asyncio.gather(*[save_frame(fn, fr) for fn, fr in frames_to_save]),
                timeout=5.0
            )
            # Collect successfully saved filenames
            filenames = [fn for fn, success in results if success]
        except asyncio.TimeoutError:
            self.logger.error("Snapshot saving timed out")
            filenames = []

        StatusMessage.send("snapshot_taken", {"files": filenames})

    async def handle_get_status(self, command_data: Dict[str, Any]) -> None:
        """Handle get_status command."""
        status_data = {
            "recording": self.system.recording,
            "session": self.system.session_label,
            "cameras": [
                {
                    "cam_num": cam.cam_num,
                    "recording": cam.recording,
                    "capture_fps": round(cam.capture_loop.get_fps(), 2),
                    "processing_fps": round(cam.processor.fps_tracker.get_fps(), 2),
                    "captured_frames": cam.capture_loop.get_frame_count(),
                    "processed_frames": cam.processor.processed_frames,
                    "recorded_frames": cam.recording_manager.written_frames,
                    "output": str(cam.recording_manager.video_path) if cam.recording_manager.video_path else None,
                } for cam in self.system.cameras
            ]
        }
        StatusMessage.send("status_report", status_data)

    async def handle_custom_command(self, command: str, command_data: Dict[str, Any]) -> bool:
        """Handle camera-specific custom commands."""
        if command == "toggle_preview":
            cam_num = command_data.get("camera_id", 0)
            enabled = command_data.get("enabled", True)

            if 0 <= cam_num < len(self.system.preview_enabled):
                self.system.preview_enabled[cam_num] = enabled
                StatusMessage.send(
                    "preview_toggled",
                    {"camera_id": cam_num, "enabled": enabled},
                )
                return True
            else:
                StatusMessage.send("error", {"message": f"Invalid camera_id: {cam_num}"})
                return True

        return False  # Not handled
