#!/usr/bin/env python3
"""
Multi-device audio system coordinator.
Manages multiple audio devices and delegates to appropriate operational mode.
"""

import asyncio
import datetime
import logging
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

from .audio_handler import AudioHandler
from .audio_utils import DeviceDiscovery
from .commands import StatusMessage
from .modes import InteractiveMode, SlaveMode, HeadlessMode
from .constants import DEVICE_DISCOVERY_TIMEOUT

logger = logging.getLogger("AudioSystem")


class AudioInitializationError(RuntimeError):
    """Raised when audio devices cannot be initialized."""


class AudioSystem:
    """Multi-device audio system with interactive, slave, and headless modes."""

    def __init__(self, args):
        self.logger = logging.getLogger("AudioSystem")
        self.handlers: List[AudioHandler] = []
        self.active_handlers: Dict[int, AudioHandler] = {}
        self.running = False
        self.recording = False
        self.recording_count = 0
        self.args = args
        self.mode = getattr(args, "mode", "interactive")
        self.slave_mode = self.mode == "slave"
        self.headless_mode = self.mode == "headless"
        self.sample_rate = getattr(args, "sample_rate", 48000)
        self.session_prefix = getattr(args, "session_prefix", "experiment")
        self.auto_select_new = getattr(args, "auto_select_new", True)
        self.auto_start_recording = getattr(args, "auto_start_recording", False)
        self.shutdown_event = asyncio.Event()
        self.device_timeout = DEVICE_DISCOVERY_TIMEOUT
        self.initialized = False

        # Device management
        self.available_devices: Dict[int, dict] = {}
        self.selected_devices: set = set()
        self._known_devices: set = set()

        # Get console stdout for user-facing messages
        self.console = getattr(args, "console_stdout", sys.stdout)

        # Session directory is created in main() and passed via args
        self.session_dir = getattr(args, "session_dir", None)
        if self.session_dir is None:
            # Fallback: create session directory if not provided
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            prefix = self.session_prefix.rstrip("_")
            session_name = f"{prefix}_{timestamp}" if prefix else timestamp
            base = Path(self.args.output_dir)
            self.session_dir = base / session_name
            self.session_dir.mkdir(parents=True, exist_ok=True)
        self.session_label = self.session_dir.name
        self.logger.info("Session directory: %s", self.session_dir)

        # Feedback queue for device status messages
        self.feedback_queue = asyncio.Queue()

        # Signal handlers are set up in main.py using asyncio signal handlers

        if self.slave_mode:
            StatusMessage.send("initializing", {"device": "audio"})

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
        if self.slave_mode:
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

    async def run(self) -> None:
        """Main run method - chooses mode based on configuration and delegates."""
        try:
            # Initialize devices now that signal handlers are set up
            await self._initialize_devices()

            # Create and run appropriate mode
            if self.slave_mode:
                mode = SlaveMode(self)
            elif self.headless_mode:
                mode = HeadlessMode(self)
            else:
                mode = InteractiveMode(self)

            await mode.run()

        except KeyboardInterrupt:
            self.logger.info("Audio system cancelled by user")
            if self.slave_mode:
                StatusMessage.send("error", {"message": "Cancelled by user"})
            raise
        except AudioInitializationError:
            raise
        except Exception as e:
            self.logger.error("Unexpected error in run: %s", e)
            if self.slave_mode:
                StatusMessage.send("error", {"message": f"Unexpected error: {e}"})
            raise

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
