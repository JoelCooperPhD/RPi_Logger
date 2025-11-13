import asyncio
import logging
import time
from typing import Any, Optional
from pathlib import Path

from Modules.base import BaseSystem, RecordingStateMixin
from .gps_handler import GPSHandler
from .recording import GPSRecordingManager
from .constants import SERIAL_PORT, BAUD_RATE

logger = logging.getLogger(__name__)


class GPSInitializationError(Exception):
    pass


class GPSSystem(BaseSystem, RecordingStateMixin):

    DEFER_DEVICE_INIT_IN_GUI = True

    def __init__(self, args):
        super().__init__(args)
        RecordingStateMixin.__init__(self)

        self.auto_start_recording = getattr(args, "auto_start_recording", False)
        self.gps_handler: Optional[GPSHandler] = None
        self.recording_manager: Optional[GPSRecordingManager] = None
        self.current_trial_number: int = 1

    async def _initialize_devices(self) -> None:
        logger.info("Initializing GPS receiver (timeout: %ds)...", self.device_timeout)

        self.lifecycle_timer.mark_phase("device_discovery_start")
        start_time = time.time()
        self.initialized = False

        discovery_attempts = 0
        while time.time() - start_time < self.device_timeout:
            discovery_attempts += 1
            try:
                if self._should_send_status() and discovery_attempts == 1:
                    from logger_core.commands import StatusMessage
                    StatusMessage.send("discovering", {"device_type": "gps_receiver", "timeout": self.device_timeout})

                self.gps_handler = GPSHandler(SERIAL_PORT, BAUD_RATE)
                await self.gps_handler.start()

                if await self.gps_handler.wait_for_fix(timeout=2.0):
                    if self._should_send_status():
                        from logger_core.commands import StatusMessage
                        StatusMessage.send("device_detected", {"device_type": "gps_receiver", "port": SERIAL_PORT})
                    break
            except Exception as e:
                logger.debug("GPS initialization attempt failed: %s", e)
                if self.gps_handler:
                    await self.gps_handler.stop()
                    self.gps_handler = None

            if self.shutdown_event.is_set():
                raise KeyboardInterrupt("Device discovery cancelled")

            await asyncio.sleep(0.5)

        if not self.gps_handler:
            error_msg = f"No GPS receiver found on {SERIAL_PORT} within {self.device_timeout} seconds"
            logger.warning(error_msg)
            raise GPSInitializationError(error_msg)

        self.recording_manager = GPSRecordingManager(self.gps_handler)
        self.initialized = True

        self.lifecycle_timer.mark_phase("device_discovery_complete")
        self.lifecycle_timer.mark_phase("initialized")

        logger.info("GPS receiver initialized successfully")

        if self._should_send_status():
            from logger_core.commands import StatusMessage
            init_duration = self.lifecycle_timer.get_duration("device_discovery_start", "initialized")
            StatusMessage.send_with_timing("initialized", init_duration, {
                "device_type": "gps_receiver",
                "port": SERIAL_PORT,
                "discovery_attempts": discovery_attempts
            })

    async def start_recording(self, trial_number: int = 1) -> bool:
        can_start, error_msg = self.validate_recording_start()
        if not can_start:
            logger.error("Cannot start recording: %s", error_msg)
            return False

        if not self.recording_manager:
            logger.error("Recording manager not initialized")
            return False

        self.current_trial_number = trial_number
        self._increment_recording_count()
        self.recording = True

        try:
            await self.recording_manager.start_recording(self.session_dir, trial_number)
            logger.info("Started GPS recording #%d (trial %d)", self.recording_count, trial_number)
            return True
        except Exception as e:
            logger.error("Failed to start recording: %s", e)
            self.recording = False
            return False

    async def stop_recording(self) -> bool:
        can_stop, error_msg = self.validate_recording_stop()
        if not can_stop:
            logger.warning("Cannot stop recording: %s", error_msg)
            return False

        self.recording = False

        if self.recording_manager:
            try:
                await self.recording_manager.stop_recording()
                logger.info("Recording stopped")
                return True
            except Exception as e:
                logger.error("Failed to stop recording: %s", e)
                return False

        return False

    def _create_mode_instance(self, mode_name: str) -> Any:
        if mode_name == "gui":
            from .modes.gui_mode import GUIMode
            return GUIMode(self, enable_commands=self.enable_gui_commands)
        else:
            raise ValueError(f"Unsupported mode: {mode_name}")

    async def cleanup(self) -> None:
        logger.info("GPS cleanup")
        self.running = False
        self.shutdown_event.set()

        if self.recording:
            await self.stop_recording()

        if self.gps_handler:
            handler = self.gps_handler
            self.gps_handler = None
            try:
                await handler.stop()
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.error("Failed to stop GPS handler cleanly: %s", exc, exc_info=True)

        if self.recording_manager:
            manager = self.recording_manager
            self.recording_manager = None
            try:
                await manager.cleanup()
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.error("Failed to cleanup GPS recording manager: %s", exc, exc_info=True)

        self.initialized = False
        logger.info("GPS cleanup completed")
