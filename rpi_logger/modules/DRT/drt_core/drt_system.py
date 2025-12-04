import asyncio
from pathlib import Path
from typing import Any, Optional, Dict, List, Tuple

from rpi_logger.modules.base import BaseSystem, RecordingStateMixin
from . import DRTInitializationError
from .device_types import DRTDeviceType
from .connection_manager import ConnectionManager
from .handlers import BaseDRTHandler

class DRTSystem(BaseSystem, RecordingStateMixin):

    DEFER_DEVICE_INIT_IN_GUI = True

    def __init__(self, args):
        super().__init__(args)
        RecordingStateMixin.__init__(self)

        self.connection_manager: Optional[ConnectionManager] = None
        self.device_handlers: Dict[str, BaseDRTHandler] = {}
        self.device_types: Dict[str, DRTDeviceType] = {}
        self.output_dir: Optional[Path] = None

    async def _initialize_devices(self) -> None:
        try:
            self.logger.info("Initializing DRT module...")
            self.lifecycle_timer.mark_phase("device_discovery_start")

            if self._should_send_status():
                from rpi_logger.core.commands import StatusMessage
                StatusMessage.send("discovering", {"device_type": "drt", "timeout": self.device_timeout})

            self.session_dir.mkdir(parents=True, exist_ok=True)
            self.output_dir = self.session_dir

            # Create connection manager for all DRT device types
            self.connection_manager = ConnectionManager(
                output_dir=self.output_dir,
                scan_interval=1.0,
                enable_xbee=True
            )

            # Set up callbacks
            self.connection_manager.on_device_connected = self._on_device_connected
            self.connection_manager.on_device_disconnected = self._on_device_disconnected
            self.connection_manager.on_xbee_status_change = self._on_xbee_status_change

            await self.connection_manager.start()

            self.initialized = True
            self.lifecycle_timer.mark_phase("device_discovery_complete")
            self.lifecycle_timer.mark_phase("initialized")

            self.logger.info("DRT module initialized, scanning for sDRT, wDRT USB, and wDRT wireless devices...")

            if self._should_send_status():
                from rpi_logger.core.commands import StatusMessage
                init_duration = self.lifecycle_timer.get_duration("device_discovery_start", "initialized")
                StatusMessage.send_with_timing("initialized", init_duration, {
                    "device_type": "drt",
                    "connection_manager_active": True,
                    "xbee_enabled": self.connection_manager.xbee_enabled
                })

        except DRTInitializationError:
            raise
        except Exception as e:
            error_msg = f"Failed to initialize DRT: {e}"
            self.logger.error(error_msg, exc_info=True)
            raise DRTInitializationError(error_msg) from e

    async def _on_device_connected(
        self,
        device_id: str,
        device_type: DRTDeviceType,
        handler: BaseDRTHandler
    ):
        """Handle device connection from ConnectionManager."""
        self.logger.info("DRTSystem: %s device connected: %s", device_type.value, device_id)

        # Set up data callback
        handler.data_callback = self._on_device_data

        # Store handler and type
        self.device_handlers[device_id] = handler
        self.device_types[device_id] = device_type
        self.logger.info("DRTSystem: Handler registered for %s", device_id)

        if self.mode_instance and hasattr(self.mode_instance, 'on_device_connected'):
            self.logger.info("DRTSystem: Calling mode_instance.on_device_connected for %s", device_id)
            await self.mode_instance.on_device_connected(device_id, device_type)
            self.logger.info("DRTSystem: mode_instance.on_device_connected completed for %s", device_id)
        elif self.mode_instance:
            self.logger.warning("DRTSystem: mode_instance missing on_device_connected handler")

    async def _on_device_disconnected(self, device_id: str, device_type: DRTDeviceType):
        """Handle device disconnection from ConnectionManager."""
        self.logger.info("%s device disconnected: %s", device_type.value, device_id)

        if device_id in self.device_handlers:
            self.device_handlers.pop(device_id)
        if device_id in self.device_types:
            self.device_types.pop(device_id)

        if self.mode_instance and hasattr(self.mode_instance, 'on_device_disconnected'):
            await self.mode_instance.on_device_disconnected(device_id, device_type)
        elif self.mode_instance:
            self.logger.warning('DRTSystem: mode_instance missing on_device_disconnected handler')

    async def _on_device_data(self, port: str, data_type: str, data: Dict[str, Any]):
        if self.mode_instance and hasattr(self.mode_instance, 'on_device_data'):
            await self.mode_instance.on_device_data(port, data_type, data)

    async def _on_xbee_status_change(self, status: str, detail: str):
        """Handle XBee dongle status changes from ConnectionManager."""
        self.logger.info("=== DRTSYSTEM _ON_XBEE_STATUS_CHANGE ===")
        self.logger.info("Status: %s, Detail: %s", status, detail)
        self.logger.info("mode_instance: %s", self.mode_instance)
        self.logger.info("has on_xbee_status_change: %s", hasattr(self.mode_instance, 'on_xbee_status_change') if self.mode_instance else 'N/A')

        if self.mode_instance and hasattr(self.mode_instance, 'on_xbee_status_change'):
            self.logger.info("Calling mode_instance.on_xbee_status_change")
            await self.mode_instance.on_xbee_status_change(status, detail)
            self.logger.info("mode_instance.on_xbee_status_change completed")
        else:
            self.logger.warning("Cannot call on_xbee_status_change - mode_instance=%s", self.mode_instance)

    def _create_mode_instance(self, mode_name: str) -> Any:
        if mode_name == "gui":
            from .modes.gui_mode import GUIMode
            return GUIMode(self, enable_commands=self.enable_gui_commands)
        if mode_name == "simple":
            from .modes.simple_mode import SimpleMode
            return SimpleMode(self, enable_commands=self.enable_gui_commands)
        if mode_name == "headless":
            self.logger.error("Headless mode not implemented for DRT")
            raise ValueError(f"Unsupported mode: {mode_name}")
        raise ValueError(f"Unknown mode: {mode_name}")

    async def start_recording(self) -> bool:
        can_start, error_msg = self.validate_recording_start()
        if not can_start:
            self.logger.warning("Cannot start recording: %s", error_msg)
            return False

        if not self.device_handlers:
            self.logger.error("Cannot start recording - no devices connected")
            return False

        started_handlers: List[Tuple[str, DRTHandler]] = []
        failures: List[str] = []

        for port, handler in self.device_handlers.items():
            try:
                success = await handler.start_experiment()
            except Exception as exc:
                self.logger.error("Exception starting experiment on %s: %s", port, exc, exc_info=True)
                success = False

            if success:
                started_handlers.append((port, handler))
            else:
                failures.append(port)

        if failures:
            self.logger.error("Failed to start recording on ports: %s", ", ".join(failures))
            for port, handler in started_handlers:
                try:
                    await handler.stop_experiment()
                except Exception as exc:
                    self.logger.warning("Rollback stop_experiment failed on %s: %s", port, exc, exc_info=True)
            return False

        self.recording = True
        self.logger.info("DRT recording started for all devices")
        return True

    async def stop_recording(self) -> bool:
        can_stop, error_msg = self.validate_recording_stop()
        if not can_stop:
            self.logger.warning("Cannot stop recording: %s", error_msg)
            return False

        failures: List[str] = []

        for port, handler in self.device_handlers.items():
            try:
                success = await handler.stop_experiment()
            except Exception as exc:
                self.logger.error("Exception stopping experiment on %s: %s", port, exc, exc_info=True)
                success = False

            if not success:
                failures.append(port)

        if failures:
            self.logger.error("Failed to stop recording on ports: %s", ", ".join(failures))
            return False

        self.recording = False
        self.logger.info("DRT recording stopped for all devices")
        return True

    async def cleanup(self):
        self.logger.info("Cleaning up DRT system...")

        self.running = False
        self.shutdown_event.set()

        if self.recording:
            self.logger.info("Stopping recording before cleanup...")
            stopped = await self.stop_recording()
            if not stopped:
                self.logger.warning("Recording did not stop cleanly during cleanup")

        if self.connection_manager:
            await self.connection_manager.stop()

        self.device_handlers.clear()
        self.device_types.clear()

        self.initialized = False
        self.logger.info("DRT cleanup completed")

    def get_connected_devices(self) -> Dict[str, DRTDeviceType]:
        """Return dict of device IDs to their types."""
        return self.device_types.copy()

    def get_device_handler(self, device_id: str) -> Optional[BaseDRTHandler]:
        """Get handler for a specific device."""
        return self.device_handlers.get(device_id)

    def get_device_type(self, device_id: str) -> Optional[DRTDeviceType]:
        """Get the device type for a specific device."""
        return self.device_types.get(device_id)

    async def rescan_xbee_network(self) -> None:
        """Trigger a rescan of the XBee network for wireless devices."""
        if self.connection_manager:
            self.logger.info("Triggering XBee network rescan...")
            await self.connection_manager.rescan_xbee_network()

    @property
    def xbee_connected(self) -> bool:
        """Check if XBee dongle is connected."""
        return self.connection_manager is not None and self.connection_manager.xbee_connected

    @property
    def xbee_port(self) -> Optional[str]:
        """Return the XBee dongle port if connected, None otherwise."""
        if self.connection_manager:
            return self.connection_manager.xbee_port
        return None
