#!/usr/bin/env python3
"""
Command handler for camera system.

Processes commands received from master in slave mode.
"""

import datetime
import logging
from pathlib import Path
from typing import TYPE_CHECKING

import cv2

if TYPE_CHECKING:
    from ..camera_system import CameraSystem

from .command_protocol import StatusMessage

logger = logging.getLogger("CommandHandler")


class CommandHandler:
    """Handles command execution for camera system."""

    def __init__(self, camera_system: 'CameraSystem'):
        """
        Initialize command handler.

        Args:
            camera_system: Reference to CameraSystem instance
        """
        self.system = camera_system
        self.logger = logging.getLogger("CommandHandler")

    def handle_command(self, command_data: dict) -> None:
        """
        Handle command from master.

        Args:
            command_data: Parsed command dict from JSON
        """
        try:
            cmd = command_data.get("command")

            if cmd == "start_recording":
                self._handle_start_recording()
            elif cmd == "stop_recording":
                self._handle_stop_recording()
            elif cmd == "take_snapshot":
                self._handle_take_snapshot()
            elif cmd == "get_status":
                self._handle_get_status()
            elif cmd == "toggle_preview":
                self._handle_toggle_preview(command_data)
            elif cmd == "quit":
                self._handle_quit()
            else:
                StatusMessage.send("error", {"message": f"Unknown command: {cmd}"})

        except Exception as e:
            StatusMessage.send("error", {"message": str(e)})
            self.logger.error("Command error: %s", e, exc_info=True)

    def _handle_start_recording(self) -> None:
        """Handle start_recording command."""
        if not self.system.recording:
            session_dir = self.system._ensure_session_dir()
            for cam in self.system.cameras:
                cam.start_recording(session_dir)
            self.system.recording = True
            StatusMessage.send(
                "recording_started",
                {
                    "session": self.system.session_label,
                    "files": [str(cam.recorder) for cam in self.system.cameras if cam.recorder],
                },
            )
        else:
            StatusMessage.send("error", {"message": "Already recording"})

    def _handle_stop_recording(self) -> None:
        """Handle stop_recording command."""
        if self.system.recording:
            for cam in self.system.cameras:
                cam.stop_recording()
            self.system.recording = False
            StatusMessage.send(
                "recording_stopped",
                {
                    "session": self.system.session_label,
                    "files": [
                        str(cam.last_recording)
                        for cam in self.system.cameras
                        if cam.last_recording is not None
                    ],
                },
            )
        else:
            StatusMessage.send("error", {"message": "Not recording"})

    def _handle_take_snapshot(self) -> None:
        """Handle take_snapshot command."""
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filenames = []
        session_dir = self.system._ensure_session_dir()
        for i, cam in enumerate(self.system.cameras):
            frame = cam.update_preview_cache()
            if frame is not None:
                filename = session_dir / f"snapshot_cam{i}_{ts}.jpg"
                cv2.imwrite(str(filename), frame)
                filenames.append(str(filename))
        StatusMessage.send("snapshot_taken", {"files": filenames})

    def _handle_get_status(self) -> None:
        """Handle get_status command."""
        status_data = {
            "recording": self.system.recording,
            "session": self.system.session_label,
            "cameras": [
                {
                    "cam_num": cam.cam_num,
                    "recording": cam.recording,
                    "capture_fps": round(cam.capture_loop.get_fps(), 2),
                    "collation_fps": round(cam.collator_loop.get_fps(), 2),
                    "captured_frames": cam.capture_loop.get_frame_count(),
                    "collated_frames": cam.collator_loop.get_frame_count(),
                    "duplicated_frames": cam.recording_manager.duplicated_frames,
                    "recorded_frames": cam.recording_manager.written_frames,
                    "output": str(cam.recording_manager.video_path) if cam.recording_manager.video_path else None,
                } for cam in self.system.cameras
            ]
        }
        StatusMessage.send("status_report", status_data)

    def _handle_toggle_preview(self, command_data: dict) -> None:
        """Handle toggle_preview command."""
        cam_num = command_data.get("camera_id", 0)
        enabled = command_data.get("enabled", True)

        if 0 <= cam_num < len(self.system.preview_enabled):
            self.system.preview_enabled[cam_num] = enabled
            StatusMessage.send(
                "preview_toggled",
                {"camera_id": cam_num, "enabled": enabled},
            )
        else:
            StatusMessage.send("error", {"message": f"Invalid camera_id: {cam_num}"})

    def _handle_quit(self) -> None:
        """Handle quit command."""
        self.system.running = False
        self.system.shutdown_event.set()
        StatusMessage.send("quitting")
