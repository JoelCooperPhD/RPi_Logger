#!/usr/bin/env python3
"""
Multi-device audio system coordinator.
Manages multiple audio devices and delegates to appropriate operational mode.
"""

import asyncio
import logging
import time
from typing import Any, Dict, List

from Modules.base import BaseSystem
from .audio_handler import AudioHandler
from .audio_utils import DeviceDiscovery
from .commands import StatusMessage
from .modes import SlaveMode, HeadlessMode, GUIMode

logger = logging.getLogger("AudioSystem")


class AudioInitializationError(RuntimeError):
    """Raised when audio devices cannot be initialized."""


class AudioSystem(BaseSystem):
    """Multi-device audio system with GUI and headless modes."""

    def __init__(self, args):
        # Initialize base system (handles common initialization)
        super().__init__(args)

        # Audio-specific configuration
        self.sample_rate = getattr(args, "sample_rate", 48000)
        self.auto_select_new = getattr(args, "auto_select_new", True)
        self.auto_start_recording = getattr(args, "auto_start_recording", False)
        self.recording_count = 0

        # Auto-detect parent communication mode
        # If stdin is not a TTY (i.e., it's a pipe), enable command mode for GUI
        import sys
        self.enable_gui_commands = getattr(args, "enable_commands", False) or (
            self.gui_mode and not sys.stdin.isatty()
        )

        # Audio device management
        self.handlers: List[AudioHandler] = []
        self.active_handlers: Dict[int, AudioHandler] = {}
        self.available_devices: Dict[int, dict] = {}
        self.selected_devices: set = set()
        self._known_devices: set = set()

        # Feedback queue for device status messages
        self.feedback_queue = asyncio.Queue()

    async def _initialize_devices(self) -> None:
        """Initialize audio devices with timeout and graceful handling."""
        self.logger.info("Searching for audio devices (timeout: %ds)...", self.device_timeout)

        start_time = time.time()
        self.initialized = False

        # Try to detect audio devices with timeout
        while time.time() - start_time < self.device_timeout:
            try:
                self.available_devices = await DeviceDiscovery.get_audio_input_devices()
                if self.available_devices:
                    break
            except Exception as e:
                self.logger.debug("Device detection attempt failed: %s", e)

            # Check if we should abort
            if self.shutdown_event.is_set():
                raise KeyboardInterrupt("Device discovery cancelled")

            await asyncio.sleep(0.5)

        # Log found devices
        for device_id, info in self.available_devices.items():
            self.logger.info("Found device %d: %s (%d ch, %.0f Hz)",
                           device_id, info['name'], info['channels'], info['sample_rate'])

        # Check if we have devices
        if not self.available_devices:
            error_msg = f"No audio input devices found within {self.device_timeout} seconds"
            self.logger.warning(error_msg)
            if self.slave_mode:
                StatusMessage.send("warning", {"message": error_msg})
            raise AudioInitializationError(error_msg)

        self._known_devices = set(self.available_devices.keys())

        # Auto-select first device if enabled
        if self.auto_select_new and not self.selected_devices:
            first_device = min(self.available_devices.keys())
            self.selected_devices.add(first_device)
            self.logger.info("Auto-selected device %d", first_device)

        self.logger.info("Audio device discovery complete: %d devices available", len(self.available_devices))

        # Send initialized status if parent communication is enabled
        if self.slave_mode or self.enable_gui_commands:
            StatusMessage.send(
                "initialized",
                {"devices": len(self.available_devices), "session": self.session_label}
            )
        self.initialized = True

    def select_device(self, device_id: int) -> bool:
        """
        Select device for recording.

        Args:
            device_id: Device ID to select

        Returns:
            True if device was selected
        """
        if device_id not in self.available_devices:
            self.logger.warning("Device %d not found", device_id)
            return False

        self.selected_devices.add(device_id)
        self.logger.info("Selected device %d: %s", device_id, self.available_devices[device_id]['name'])
        return True

    def deselect_device(self, device_id: int) -> bool:
        """
        Deselect device from recording.

        Args:
            device_id: Device ID to deselect

        Returns:
            True if device was deselected
        """
        if device_id not in self.selected_devices:
            return False

        self.selected_devices.remove(device_id)
        self.logger.info("Deselected device %d", device_id)
        return True

    def start_recording(self) -> bool:
        """
        Start recording from all selected devices.

        Returns:
            True if recording started successfully
        """
        if self.recording or not self.selected_devices:
            if not self.selected_devices:
                self.logger.warning("No devices selected for recording")
            return False

        self.recording_count += 1
        self.recording = True
        success_count = 0

        for device_id in self.selected_devices:
            device_info = self.available_devices[device_id]

            # Create handler for this device
            handler = AudioHandler(device_id, device_info, self.sample_rate)

            # Start audio stream
            if handler.start_stream(self.feedback_queue):
                # Start recording
                if handler.start_recording():
                    self.active_handlers[device_id] = handler
                    success_count += 1
                else:
                    self.logger.error("Failed to start recording on device %d", device_id)
            else:
                self.logger.error("Failed to start stream on device %d", device_id)

        if success_count > 0:
            device_names = [self.available_devices[did]['name'] for did in self.active_handlers.keys()]
            self.logger.info("Started recording #%d on %d devices: %s",
                           self.recording_count, len(self.active_handlers), ', '.join(device_names))
            return True
        else:
            self.recording = False
            return False

    async def stop_recording(self) -> bool:
        """
        Stop recording on all active devices and save files (async, concurrent).

        Returns:
            True if recording stopped successfully
        """
        if not self.recording:
            return False

        self.recording = False

        # Stop all handlers and save recordings concurrently
        save_tasks = []
        for device_id, handler in self.active_handlers.items():
            task = handler.stop_recording(self.session_dir, self.recording_count)
            save_tasks.append(task)

        if save_tasks:
            # Use gather with return_exceptions for robust error handling
            saved_files = await asyncio.gather(*save_tasks, return_exceptions=True)

            # Log results and handle exceptions
            success_count = 0
            for result in saved_files:
                if isinstance(result, Exception):
                    self.logger.error("Save error: %s", result)
                elif result:
                    success_count += 1

            self.logger.info("Saved %d recordings", success_count)

        # Clean up handlers concurrently
        if self.active_handlers:
            cleanup_tasks = [handler.cleanup() for handler in self.active_handlers.values()]
            await asyncio.gather(*cleanup_tasks, return_exceptions=True)

        self.active_handlers.clear()
        self.logger.info("Recording stopped")
        return True

    def _create_mode_instance(self, mode_name: str) -> Any:
        """
        Create mode instance based on mode name.

        Args:
            mode_name: Mode name ('gui', 'headless', 'slave')

        Returns:
            Mode instance (SlaveMode, HeadlessMode, or GUIMode)
        """
        if mode_name == "slave":
            return SlaveMode(self)
        elif mode_name == "headless":
            return HeadlessMode(self)
        else:  # gui or any other mode defaults to GUI
            return GUIMode(self, enable_commands=self.enable_gui_commands)

    async def cleanup(self) -> None:
        """Clean up all audio resources."""
        self.running = False
        self.shutdown_event.set()

        if self.recording:
            await self.stop_recording()

        # Clean up all handlers
        if self.active_handlers:
            await asyncio.gather(
                *[handler.cleanup() for handler in self.active_handlers.values()],
                return_exceptions=True
            )
            self.active_handlers.clear()

        self.initialized = False
        self.logger.info("Cleanup completed")
