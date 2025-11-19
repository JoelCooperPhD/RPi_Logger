import asyncio
from rpi_logger.core.logging_utils import get_module_logger
from pathlib import Path
from typing import Any, Optional, Dict, List, Tuple

from rpi_logger.modules.base import BaseSystem, RecordingStateMixin, USBDeviceConfig, USBDeviceMonitor, USBSerialDevice
from . import DRTInitializationError
from .drt_handler import DRTHandler

# Remove the module-level logger initialization
# logger = logging.getLogger(__name__)


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
                from rpi_logger.core.commands import StatusMessage
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
                from rpi_logger.core.commands import StatusMessage
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
        elif self.mode_instance:
            logger.warning("DRTSystem: mode_instance missing on_device_connected handler")

    async def _on_device_disconnected(self, port: str):
        logger.info(f"sDRT device disconnected from {port}")

        if port in self.device_handlers:
            handler = self.device_handlers.pop(port)
            await handler.stop()

        if self.mode_instance and hasattr(self.mode_instance, 'on_device_disconnected'):
            await self.mode_instance.on_device_disconnected(port)
        elif self.mode_instance:
            logger.warning('DRTSystem: mode_instance missing on_device_disconnected handler')

    async def _on_device_data(self, port: str, data_type: str, data: Dict[str, Any]):
        if self.mode_instance and hasattr(self.mode_instance, 'on_device_data'):
            await self.mode_instance.on_device_data(port, data_type, data)

    def _create_mode_instance(self, mode_name: str) -> Any:
        if mode_name == "gui":
            from .modes.gui_mode import GUIMode
            return GUIMode(self, enable_commands=self.enable_gui_commands)
        if mode_name == "simple":
            from .modes.simple_mode import SimpleMode
            return SimpleMode(self, enable_commands=self.enable_gui_commands)
        if mode_name == "headless":
            logger.error("Headless mode not implemented for DRT")
            raise ValueError(f"Unsupported mode: {mode_name}")
        raise ValueError(f"Unknown mode: {mode_name}")

    async def start_recording(self) -> bool:
        can_start, error_msg = self.validate_recording_start()
        if not can_start:
            logger.warning("Cannot start recording: %s", error_msg)
            return False

        if not self.device_handlers:
            logger.error("Cannot start recording - no devices connected")
            return False

        started_handlers: List[Tuple[str, DRTHandler]] = []
        failures: List[str] = []

        for port, handler in self.device_handlers.items():
            try:
                success = await handler.start_experiment()
            except Exception as exc:
                logger.error("Exception starting experiment on %s: %s", port, exc, exc_info=True)
                success = False

            if success:
                started_handlers.append((port, handler))
            else:
                failures.append(port)

        if failures:
            logger.error("Failed to start recording on ports: %s", ", ".join(failures))
            for port, handler in started_handlers:
                try:
                    await handler.stop_experiment()
                except Exception as exc:
                    logger.warning("Rollback stop_experiment failed on %s: %s", port, exc, exc_info=True)
            return False

        self.recording = True
        logger.info("DRT recording started for all devices")
        return True

    async def stop_recording(self) -> bool:
        can_stop, error_msg = self.validate_recording_stop()
        if not can_stop:
            logger.warning("Cannot stop recording: %s", error_msg)
            return False

        failures: List[str] = []

        for port, handler in self.device_handlers.items():
            try:
                success = await handler.stop_experiment()
            except Exception as exc:
                logger.error("Exception stopping experiment on %s: %s", port, exc, exc_info=True)
                success = False

            if not success:
                failures.append(port)

        if failures:
            logger.error("Failed to stop recording on ports: %s", ", ".join(failures))
            return False

        self.recording = False
        logger.info("DRT recording stopped for all devices")
        return True

    async def cleanup(self):
        logger.info("Cleaning up DRT system...")

        self.running = False
        self.shutdown_event.set()

        if self.recording:
            logger.info("Stopping recording before cleanup...")
            stopped = await self.stop_recording()
            if not stopped:
                logger.warning("Recording did not stop cleanly during cleanup")

        if self.usb_monitor:
            await self.usb_monitor.stop()

        for handler in list(self.device_handlers.values()):
            try:
                await handler.stop()
            except Exception as exc:
                logger.warning("Error stopping handler for cleanup on %s: %s", getattr(handler, 'port', 'unknown'), exc, exc_info=True)

        self.device_handlers.clear()

        self.initialized = False
        logger.info("DRT cleanup completed")

    def get_connected_devices(self) -> Dict[str, USBSerialDevice]:
        if self.usb_monitor:
            return self.usb_monitor.get_devices()
        return {}

    def get_device_handler(self, port: str) -> Optional[DRTHandler]:
        return self.device_handlers.get(port)
