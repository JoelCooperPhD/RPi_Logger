
import asyncio
import logging
import time
from typing import Any, Dict, List

from Modules.base import BaseSystem, ModuleInitializationError, RecordingStateMixin
from .audio_handler import AudioHandler
from .audio_utils import DeviceDiscovery
from .commands import StatusMessage
from .modes import SlaveMode, HeadlessMode, GUIMode

logger = logging.getLogger(__name__)


class AudioInitializationError(ModuleInitializationError):
    pass


class AudioSystem(BaseSystem, RecordingStateMixin):

    # Audio devices will be detected in background after GUI is created
    DEFER_DEVICE_INIT_IN_GUI = True

    def __init__(self, args):
        super().__init__(args)
        RecordingStateMixin.__init__(self)

        self.sample_rate = getattr(args, "sample_rate", 48000)
        self.auto_select_new = getattr(args, "auto_select_new", True)
        self.auto_start_recording = getattr(args, "auto_start_recording", False)

        self.handlers: List[AudioHandler] = []
        self.active_handlers: Dict[int, AudioHandler] = {}
        self.available_devices: Dict[int, dict] = {}
        self.selected_devices: set = set()
        self._known_devices: set = set()
        self.current_trial_number: int = 1
        self.gui = None  # Will be set by the mode

        self.feedback_queue = asyncio.Queue()

    async def _initialize_devices(self) -> None:
        self.logger.info("Searching for audio devices (timeout: %ds)...", self.device_timeout)

        self.lifecycle_timer.mark_phase("device_discovery_start")
        start_time = time.time()
        self.initialized = False

        discovery_attempts = 0
        if self._should_send_status():
            StatusMessage.send("discovering", {"device_type": "audio_input", "timeout": self.device_timeout})

        while time.time() - start_time < self.device_timeout:
            discovery_attempts += 1
            try:
                self.available_devices = await DeviceDiscovery.get_audio_input_devices()
                if self.available_devices:
                    if self._should_send_status():
                        StatusMessage.send("device_detected", {
                            "device_type": "audio_input",
                            "count": len(self.available_devices)
                        })
                    break
            except Exception as e:
                self.logger.debug("Device detection attempt failed: %s", e)

            if self.shutdown_event.is_set():
                raise KeyboardInterrupt("Device discovery cancelled")

            await asyncio.sleep(0.5)

        for device_id, info in self.available_devices.items():
            self.logger.info("Found device %d: %s (%d ch, %.0f Hz)",
                           device_id, info['name'], info['channels'], info['sample_rate'])

        if not self.available_devices:
            error_msg = f"No audio input devices found within {self.device_timeout} seconds"
            self.logger.warning(error_msg)
            if self.slave_mode:
                StatusMessage.send("warning", {"message": error_msg})
            raise AudioInitializationError(error_msg)

        self._known_devices = set(self.available_devices.keys())

        if self.auto_select_new and not self.selected_devices:
            first_device = min(self.available_devices.keys())
            self.selected_devices.add(first_device)
            self.logger.info("Auto-selected device %d", first_device)

        self.initialized = True
        self.lifecycle_timer.mark_phase("device_discovery_complete")
        self.lifecycle_timer.mark_phase("initialized")

        self.logger.info("Audio device discovery complete: %d devices available", len(self.available_devices))

        if self._should_send_status():
            init_duration = self.lifecycle_timer.get_duration("device_discovery_start", "initialized")
            StatusMessage.send_with_timing("initialized", init_duration, {
                "devices": len(self.available_devices),
                "session": self.session_label,
                "discovery_attempts": discovery_attempts
            })

    def select_device(self, device_id: int) -> bool:
        if device_id not in self.available_devices:
            self.logger.warning("Device %d not found", device_id)
            return False

        self.selected_devices.add(device_id)
        self.logger.info("Selected device %d: %s", device_id, self.available_devices[device_id]['name'])
        return True

    def deselect_device(self, device_id: int) -> bool:
        if device_id not in self.selected_devices:
            return False

        self.selected_devices.remove(device_id)
        self.logger.info("Deselected device %d", device_id)
        return True

    async def start_recording(self, trial_number: int = 1) -> bool:
        can_start, error_msg = self.validate_recording_start()
        if not can_start:
            self.logger.error("Cannot start recording: %s", error_msg)
            return False

        if not self.selected_devices:
            self.logger.error("No devices selected for recording (available: %d, selected: %d)",
                            len(self.available_devices), len(self.selected_devices))
            return False

        self.current_trial_number = trial_number
        self._increment_recording_count()
        self.recording = True
        success_count = 0

        for device_id in self.selected_devices:
            device_info = self.available_devices[device_id]

            handler = AudioHandler(device_id, device_info, self.sample_rate, gui=self.gui)

            if handler.start_stream(self.feedback_queue):
                if handler.start_recording(self.session_dir, trial_number):
                    self.active_handlers[device_id] = handler
                    success_count += 1
                else:
                    self.logger.error("Failed to start recording on device %d", device_id)
            else:
                self.logger.error("Failed to start stream on device %d", device_id)

        if success_count > 0:
            device_names = [self.available_devices[did]['name'] for did in self.active_handlers.keys()]
            self.logger.info("Started recording #%d (trial %d) on %d devices: %s",
                           self.recording_count, trial_number, len(self.active_handlers), ', '.join(device_names))
            return True
        else:
            self.recording = False
            return False

    async def stop_recording(self) -> bool:
        can_stop, error_msg = self.validate_recording_stop()
        if not can_stop:
            self.logger.warning("Cannot stop recording: %s", error_msg)
            return False

        self.recording = False

        save_tasks = []
        for device_id, handler in self.active_handlers.items():
            task = handler.stop_recording(self.session_dir, self.current_trial_number)
            save_tasks.append(task)

        if save_tasks:
            saved_files = await asyncio.gather(*save_tasks, return_exceptions=True)

            success_count = 0
            for result in saved_files:
                if isinstance(result, Exception):
                    self.logger.error("Save error: %s", result)
                elif result:
                    success_count += 1

            self.logger.info("Saved %d recordings", success_count)

        if self.active_handlers:
            cleanup_tasks = [handler.cleanup() for handler in self.active_handlers.values()]
            await asyncio.gather(*cleanup_tasks, return_exceptions=True)

        self.active_handlers.clear()
        self.logger.info("Recording stopped")
        return True

    def _create_mode_instance(self, mode_name: str) -> Any:
        if mode_name == "slave":
            return SlaveMode(self)
        elif mode_name == "headless":
            return HeadlessMode(self)
        else:  # gui or any other mode defaults to GUI
            return GUIMode(self, enable_commands=self.enable_gui_commands)

    async def cleanup(self) -> None:
        self.running = False
        self.shutdown_event.set()

        if self.recording:
            await self.stop_recording()

        if self.active_handlers:
            await asyncio.gather(
                *[handler.cleanup() for handler in self.active_handlers.values()],
                return_exceptions=True
            )
            self.active_handlers.clear()

        self.initialized = False
        self.logger.info("Cleanup completed")
