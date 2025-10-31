import asyncio
import logging
from pathlib import Path
from typing import Any, Optional, Dict

from Modules.base import BaseSystem, RecordingStateMixin, USBDeviceConfig, USBDeviceMonitor, USBSerialDevice
from . import DRTInitializationError
from .drt_handler import DRTHandler

logger = logging.getLogger(__name__)


class DRTSystem(BaseSystem, RecordingStateMixin):

    DEFER_DEVICE_INIT_IN_GUI = True

    def __init__(self, args):
        super().__init__(args)
        RecordingStateMixin.__init__(self)

        self.usb_monitor: Optional[USBDeviceMonitor] = None
        self.device_handlers: Dict[str, DRTHandler] = {}
        self.output_dir: Optional[Path] = None

    async def _initialize_devices(self) -> None:
        try:
            logger.info("Initializing DRT module...")
            self.lifecycle_timer.mark_phase("device_discovery_start")

            if self._should_send_status():
                from logger_core.commands import StatusMessage
                StatusMessage.send("discovering", {"device_type": "usb_drt", "timeout": self.device_timeout})

            self.session_dir.mkdir(parents=True, exist_ok=True)
            self.output_dir = self.session_dir

            vid = int(self.args.device_vid) if isinstance(self.args.device_vid, str) else self.args.device_vid
            pid = int(self.args.device_pid) if isinstance(self.args.device_pid, str) else self.args.device_pid

            device_config = USBDeviceConfig(
                vid=vid,
                pid=pid,
                baudrate=self.args.baudrate,
                device_name="sDRT"
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

            logger.info("DRT module initialized successfully, discovering devices...")

            if self._should_send_status():
                from logger_core.commands import StatusMessage
                init_duration = self.lifecycle_timer.get_duration("device_discovery_start", "initialized")
                StatusMessage.send_with_timing("initialized", init_duration, {
                    "device_type": "usb_drt",
                    "usb_monitor_active": True,
                    "vid": hex(vid),
                    "pid": hex(pid)
                })

        except DRTInitializationError:
            raise
        except Exception as e:
            error_msg = f"Failed to initialize DRT: {e}"
            logger.error(error_msg, exc_info=True)
            raise DRTInitializationError(error_msg) from e

    async def _on_device_connected(self, device: USBSerialDevice):
        logger.info(f"DRTSystem: sDRT device connected on {device.port}")

        logger.info(f"DRTSystem: Creating handler for {device.port}")
        handler = DRTHandler(device, device.port, self.output_dir, system=self)
        handler.set_data_callback(self._on_device_data)

        logger.info(f"DRTSystem: Initializing device {device.port}")
        await handler.initialize_device()
        logger.info(f"DRTSystem: Starting handler for {device.port}")
        await handler.start()

        self.device_handlers[device.port] = handler
        logger.info(f"DRTSystem: Handler registered for {device.port}")

        if self.mode_instance and hasattr(self.mode_instance, 'on_device_connected'):
            logger.info(f"DRTSystem: Calling mode_instance.on_device_connected for {device.port}")
            await self.mode_instance.on_device_connected(device.port)
            logger.info(f"DRTSystem: mode_instance.on_device_connected completed for {device.port}")
        else:
            logger.warning(f"DRTSystem: No mode_instance or on_device_connected method available")

    async def _on_device_disconnected(self, port: str):
        logger.info(f"sDRT device disconnected from {port}")

        if port in self.device_handlers:
            handler = self.device_handlers.pop(port)
            await handler.stop()

        if self.mode_instance and hasattr(self.mode_instance, 'on_device_disconnected'):
            await self.mode_instance.on_device_disconnected(port)

    async def _on_device_data(self, port: str, data_type: str, data: Dict[str, Any]):
        if self.mode_instance and hasattr(self.mode_instance, 'on_device_data'):
            await self.mode_instance.on_device_data(port, data_type, data)

    def _create_mode_instance(self, mode_name: str) -> Any:
        if mode_name == "gui":
            from .modes.gui_mode import GUIMode
            return GUIMode(self, enable_commands=self.enable_gui_commands)
        elif mode_name == "headless":
            logger.error("Headless mode not implemented for DRT")
            raise ValueError(f"Unsupported mode: {mode_name}")
        else:
            raise ValueError(f"Unknown mode: {mode_name}")

    async def start_recording(self) -> bool:
        can_start, error_msg = self.validate_recording_start()
        if not can_start:
            logger.warning("Cannot start recording: %s", error_msg)
            return False

        if not self.device_handlers:
            logger.error("Cannot start recording - no devices connected")
            return False

        try:
            for handler in self.device_handlers.values():
                await handler.start_experiment()

            self.recording = True
            logger.info("DRT recording started for all devices")
            return True

        except Exception as e:
            logger.error("Exception starting recording: %s", e, exc_info=True)
            return False

    async def stop_recording(self) -> bool:
        can_stop, error_msg = self.validate_recording_stop()
        if not can_stop:
            logger.warning("Cannot stop recording: %s", error_msg)
            return False

        try:
            for handler in self.device_handlers.values():
                await handler.stop_experiment()

            self.recording = False
            logger.info("DRT recording stopped for all devices")
            return True

        except Exception as e:
            logger.error("Exception stopping recording: %s", e, exc_info=True)
            return False

    async def cleanup(self):
        logger.info("Cleaning up DRT system...")

        self.running = False
        self.shutdown_event.set()

        if self.recording:
            logger.info("Stopping recording before cleanup...")
            await self.stop_recording()

        if self.usb_monitor:
            await self.usb_monitor.stop()

        for handler in list(self.device_handlers.values()):
            await handler.stop()

        self.device_handlers.clear()

        self.initialized = False
        logger.info("DRT cleanup completed")

    def get_connected_devices(self) -> Dict[str, USBSerialDevice]:
        if self.usb_monitor:
            return self.usb_monitor.get_devices()
        return {}

    def get_device_handler(self, port: str) -> Optional[DRTHandler]:
        return self.device_handlers.get(port)
