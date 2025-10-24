"""
Abstract base classes for recording managers.

All module recording managers should inherit from RecordingManagerBase
to ensure consistent API across modules.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional, Any
import numpy as np


class RecordingManagerBase(ABC):
    """
    Abstract base class for all recording managers.

    Defines the contract that all recording managers must implement.
    This ensures consistent API across Eye Tracker, Cameras, Audio, etc.
    """

    def __init__(self, device_id: str):
        self.device_id = device_id
        self._is_recording = False
        self._current_session_dir: Optional[Path] = None
        self._current_trial_number: Optional[int] = None

    # === Recording Control ===

    @abstractmethod
    async def start_recording(self, session_dir: Path, trial_number: int = 1) -> Path:
        """
        Start recording to the specified session directory.

        Args:
            session_dir: Directory to save recording files
            trial_number: Trial/experiment number

        Returns:
            Path to the primary output file (video, audio, etc.)

        Raises:
            RuntimeError: If already recording or if start fails
        """
        pass

    @abstractmethod
    async def stop_recording(self) -> dict:
        """
        Stop the current recording.

        Returns:
            Dictionary with recording statistics:
            {
                'duration_seconds': float,
                'frames_written': int,
                'frames_dropped': int,
                'output_files': list[Path],
            }

        Raises:
            RuntimeError: If not currently recording
        """
        pass

    @abstractmethod
    async def pause_recording(self):
        """
        Pause recording without stopping (optional, may raise NotImplementedError).
        """
        raise NotImplementedError("Pause not supported by this device")

    @abstractmethod
    async def resume_recording(self):
        """
        Resume paused recording (optional, may raise NotImplementedError).
        """
        raise NotImplementedError("Resume not supported by this device")

    # === Data Writing ===

    @abstractmethod
    def write_frame(self, frame: Optional[np.ndarray], metadata: Any):
        """
        Write a single frame/sample with metadata.

        Args:
            frame: Frame data (numpy array for video, audio buffer, etc.) or None
            metadata: Module-specific metadata structure (e.g., FrameTimingMetadata)

        Raises:
            RuntimeError: If not currently recording

        Note:
            While base metadata classes (FrameMetadata, GazeMetadata, CameraMetadata)
            are provided in Modules.base.metadata, modules may use their own
            metadata structures for internal implementation.
        """
        pass

    # === State Queries ===

    @property
    def is_recording(self) -> bool:
        """Whether currently recording"""
        return self._is_recording

    @property
    def current_session_dir(self) -> Optional[Path]:
        """Current recording session directory"""
        return self._current_session_dir

    @property
    def current_trial_number(self) -> Optional[int]:
        """Current trial number"""
        return self._current_trial_number

    @abstractmethod
    def get_stats(self) -> dict:
        """
        Get current recording statistics.

        Returns:
            Dictionary with current stats (frames written, drops, duration, etc.)
        """
        pass

    # === Cleanup ===

    @abstractmethod
    async def cleanup(self):
        """
        Clean up resources (close files, release hardware, etc.).

        Should stop recording if active and release all resources.
        """
        pass

    # === Helper Methods (Optional Overrides) ===

    async def toggle_recording(self) -> bool:
        """
        Toggle recording state (convenience method).

        Returns:
            True if now recording, False if stopped
        """
        if self.is_recording:
            await self.stop_recording()
            return False
        else:
            # Note: Requires session_dir to be set
            if self._current_session_dir is None:
                raise RuntimeError("Cannot start recording: no session directory set")
            await self.start_recording(self._current_session_dir, self._current_trial_number or 1)
            return True

    def set_session_context(self, session_dir: Path, trial_number: int = 1):
        """
        Set session context for future recordings (convenience method).

        Useful for pre-configuring where recordings will go.
        """
        self._current_session_dir = session_dir
        self._current_trial_number = trial_number
