"""VOG system coordinator with USB device management."""

import asyncio
from pathlib import Path
from typing import Any, Optional, Dict, List, Tuple

from rpi_logger.modules.base import (
    BaseSystem,
    RecordingStateMixin,
    USBDeviceConfig,
    USBDeviceMonitor,
    USBSerialDevice,
)
from rpi_logger.core.commands import StatusMessage

from . import VOGInitializationError
from .vog_handler import VOGHandler


class VOGSystem(BaseSystem, RecordingStateMixin):
    """Main system coordinator for VOG module."""

    DEFER_DEVICE_INIT_IN_GUI = True

    def __init__(self, args):
        super().__init__(args)
        RecordingStateMixin.__init__(self)

        self.usb_monitor: Optional[USBDeviceMonitor] = None
        self.device_handlers: Dict[str, VOGHandler] = {}
        self.output_dir: Optional[Path] = None

        # Track active trial for all handlers
        self.active_trial_number: int = 0

    async def _initialize_devices(self) -> None:
        """Initialize USB device monitoring."""
        try:
            self.logger.info("Initializing VOG module...")
            self.lifecycle_timer.mark_phase("device_discovery_start")

            if self._should_send_status():
                StatusMessage.send("discovering", {
                    "device_type": "usb_vog",
                    "timeout": self.device_timeout
                })

            self.session_dir.mkdir(parents=True, exist_ok=True)
            self.output_dir = self.session_dir

            # Get VID/PID from args
            vid = int(self.args.device_vid) if isinstance(self.args.device_vid, str) else self.args.device_vid
            pid = int(self.args.device_pid) if isinstance(self.args.device_pid, str) else self.args.device_pid

            device_config = USBDeviceConfig(
                vid=vid,
                pid=pid,
                baudrate=self.args.baudrate,
                device_name="sVOG"
            )

            self.usb_monitor = USBDeviceMonitor(
                config=device_config,
                on_connect=self._on_device_connected,
                on_disconnect=self._on_device_disconnected
            )

            await self.usb_monitor.start()

            self.initialized = True
            self.lifecycle_timer.mark_phase("device_discovery_complete")
            self.lifecycle_timer.mark_phase("initialized")

            self.logger.info("VOG module initialized successfully, discovering devices...")

            if self._should_send_status():
                init_duration = self.lifecycle_timer.get_duration(
                    "device_discovery_start", "initialized"
                )
                StatusMessage.send_with_timing("initialized", init_duration, {
                    "device_type": "usb_vog",
                    "usb_monitor_active": True,
                    "vid": hex(vid),
                    "pid": hex(pid)
                })

        except VOGInitializationError:
            raise
        except Exception as e:
            error_msg = f"Failed to initialize VOG: {e}"
            self.logger.error(error_msg, exc_info=True)
            raise VOGInitializationError(error_msg) from e

    async def _on_device_connected(self, device: USBSerialDevice):
        """Handle new device connection."""
        self.logger.info("VOGSystem: sVOG device connected on %s", device.port)

        handler = VOGHandler(device, device.port, self.output_dir, system=self)
        handler.set_data_callback(self._on_device_data)

        await handler.initialize_device()
        await handler.start()

        self.device_handlers[device.port] = handler
        self.logger.info("VOGSystem: Handler registered for %s", device.port)

        if self.mode_instance and hasattr(self.mode_instance, 'on_device_connected'):
            await self.mode_instance.on_device_connected(device.port)

    async def _on_device_disconnected(self, port: str):
        """Handle device disconnection."""
        self.logger.info("sVOG device disconnected from %s", port)

        if port in self.device_handlers:
            handler = self.device_handlers.pop(port)
            await handler.stop()

        if self.mode_instance and hasattr(self.mode_instance, 'on_device_disconnected'):
            await self.mode_instance.on_device_disconnected(port)

    async def _on_device_data(self, port: str, data_type: str, data: Dict[str, Any]):
        """Handle data received from device."""
        if self.mode_instance and hasattr(self.mode_instance, 'on_device_data'):
            await self.mode_instance.on_device_data(port, data_type, data)

    def _create_mode_instance(self, mode_name: str) -> Any:
        """Create the appropriate mode instance."""
        if mode_name == "gui":
            from .modes.gui_mode import GUIMode
            return GUIMode(self, enable_commands=self.enable_gui_commands)
        if mode_name == "simple":
            from .modes.simple_mode import SimpleMode
            return SimpleMode(self, enable_commands=self.enable_gui_commands)
        if mode_name == "headless":
            from .modes.simple_mode import SimpleMode
            return SimpleMode(self, enable_commands=self.enable_gui_commands)
        raise ValueError(f"Unknown mode: {mode_name}")

    async def start_recording(self) -> bool:
        """Start recording on all connected devices."""
        can_start, error_msg = self.validate_recording_start()
        if not can_start:
            self.logger.warning("Cannot start recording: %s", error_msg)
            return False

        if not self.device_handlers:
            self.logger.error("Cannot start recording - no devices connected")
            return False

        started_handlers: List[Tuple[str, VOGHandler]] = []
        failures: List[str] = []

        for port, handler in self.device_handlers.items():
            try:
                success = await handler.start_experiment()
            except Exception as exc:
                self.logger.error(
                    "Exception starting experiment on %s: %s",
                    port, exc, exc_info=True
                )
                success = False

            if success:
                started_handlers.append((port, handler))
            else:
                failures.append(port)

        if failures:
            self.logger.error("Failed to start recording on ports: %s", ", ".join(failures))
            # Rollback successfully started handlers
            for port, handler in started_handlers:
                try:
                    await handler.stop_experiment()
                except Exception as exc:
                    self.logger.warning(
                        "Rollback stop_experiment failed on %s: %s",
                        port, exc, exc_info=True
                    )
            return False

        self.recording = True
        self.logger.info("VOG recording started for all devices")
        return True

    async def stop_recording(self) -> bool:
        """Stop recording on all connected devices."""
        can_stop, error_msg = self.validate_recording_stop()
        if not can_stop:
            self.logger.warning("Cannot stop recording: %s", error_msg)
            return False

        failures: List[str] = []

        for port, handler in self.device_handlers.items():
            try:
                success = await handler.stop_experiment()
            except Exception as exc:
                self.logger.error(
                    "Exception stopping experiment on %s: %s",
                    port, exc, exc_info=True
                )
                success = False

            if not success:
                failures.append(port)

        if failures:
            self.logger.error("Failed to stop recording on ports: %s", ", ".join(failures))
            return False

        self.recording = False
        self.logger.info("VOG recording stopped for all devices")
        return True

    async def peek_open_all(self) -> bool:
        """Send peek open command to all devices."""
        for handler in self.device_handlers.values():
            await handler.peek_open()
        return True

    async def peek_close_all(self) -> bool:
        """Send peek close command to all devices."""
        for handler in self.device_handlers.values():
            await handler.peek_close()
        return True

    async def cleanup(self):
        """Clean up system resources."""
        self.logger.info("Cleaning up VOG system...")

        self.running = False
        self.shutdown_event.set()

        if self.recording:
            self.logger.info("Stopping recording before cleanup...")
            stopped = await self.stop_recording()
            if not stopped:
                self.logger.warning("Recording did not stop cleanly during cleanup")

        if self.usb_monitor:
            await self.usb_monitor.stop()

        for handler in list(self.device_handlers.values()):
            try:
                await handler.stop()
            except Exception as exc:
                self.logger.warning(
                    "Error stopping handler during cleanup on %s: %s",
                    getattr(handler, 'port', 'unknown'),
                    exc, exc_info=True
                )

        self.device_handlers.clear()

        self.initialized = False
        self.logger.info("VOG cleanup completed")

    def get_connected_devices(self) -> Dict[str, USBSerialDevice]:
        """Get all connected USB devices."""
        if self.usb_monitor:
            return self.usb_monitor.get_devices()
        return {}

    def get_device_handler(self, port: str) -> Optional[VOGHandler]:
        """Get handler for a specific port."""
        return self.device_handlers.get(port)
