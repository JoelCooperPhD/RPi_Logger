"""DRT system coordinator with centralized device management.

Devices are assigned by the main logger via assign_device command.
No local USB scanning - all discovery is centralized.
"""

import asyncio
from pathlib import Path
from typing import Any, Optional, Dict, List, Tuple

from rpi_logger.modules.base import BaseSystem, RecordingStateMixin
from rpi_logger.core.commands import StatusMessage

from . import DRTInitializationError
from .device_types import DRTDeviceType
from .handlers import BaseDRTHandler, SDRTHandler, WDRTUSBHandler
from .transports import USBTransport


class DRTSystem(BaseSystem, RecordingStateMixin):
    """Main system coordinator for DRT module.

    Supports sDRT (wired) and wDRT (USB and wireless) devices.
    Devices are assigned by the main logger via assign_device command.
    """

    DEFER_DEVICE_INIT_IN_GUI = True

    def __init__(self, args):
        super().__init__(args)
        RecordingStateMixin.__init__(self)

        # Device handlers keyed by device_id
        self.device_handlers: Dict[str, BaseDRTHandler] = {}
        self.device_types: Dict[str, DRTDeviceType] = {}

        # Transport instances (kept for cleanup)
        self._transports: Dict[str, USBTransport] = {}

        self.output_dir: Optional[Path] = None

    async def _initialize_devices(self) -> None:
        """Initialize DRT module (no local device scanning).

        Devices are assigned by the main logger via assign_device command.
        """
        try:
            self.logger.info("Initializing DRT module...")
            self.lifecycle_timer.mark_phase("device_discovery_start")

            self.session_dir.mkdir(parents=True, exist_ok=True)
            self.output_dir = self.session_dir

            self.initialized = True
            self.lifecycle_timer.mark_phase("device_discovery_complete")
            self.lifecycle_timer.mark_phase("initialized")

            self.logger.info("DRT module initialized, waiting for device assignments...")

            if self._should_send_status():
                init_duration = self.lifecycle_timer.get_duration(
                    "device_discovery_start", "initialized"
                )
                StatusMessage.send_with_timing("initialized", init_duration, {
                    "device_type": "drt",
                    "devices": [],  # No devices assigned yet
                })

        except DRTInitializationError:
            raise
        except Exception as e:
            error_msg = f"Failed to initialize DRT: {e}"
            self.logger.error(error_msg, exc_info=True)
            raise DRTInitializationError(error_msg) from e

    # =========================================================================
    # Device Assignment (centralized device discovery)
    # =========================================================================

    async def assign_device(
        self,
        device_id: str,
        device_type: str,
        port: str,
        baudrate: int,
        is_wireless: bool = False,
    ) -> bool:
        """
        Assign a device to this module (called by main logger).

        Args:
            device_id: Unique device identifier
            device_type: Device type string (e.g., "sDRT", "wDRT_USB", "wDRT_Wireless")
            port: Serial port path
            baudrate: Serial baudrate
            is_wireless: Whether this is a wireless device

        Returns:
            True if device was successfully assigned
        """
        if device_id in self.device_handlers:
            self.logger.warning("Device %s already assigned", device_id)
            return True

        self.logger.info(
            "Assigning device: id=%s, type=%s, port=%s, baudrate=%d, wireless=%s",
            device_id, device_type, port, baudrate, is_wireless
        )

        try:
            # Determine device type
            device_type_lower = device_type.lower()

            if 'wdrt' in device_type_lower:
                drt_device_type = DRTDeviceType.WDRT_USB if not is_wireless else DRTDeviceType.WDRT_WIRELESS
            else:
                drt_device_type = DRTDeviceType.SDRT

            if is_wireless:
                # Wireless device - TODO: handle XBee transport
                self.logger.warning("Wireless device assignment not yet implemented")
                return False
            else:
                # USB device - create transport
                transport = USBTransport(port, baudrate)
                await transport.connect()

                if not transport.is_connected:
                    self.logger.error("Failed to connect to device %s on %s", device_id, port)
                    return False

                self._transports[device_id] = transport

                # Create appropriate handler
                if drt_device_type == DRTDeviceType.SDRT:
                    handler = SDRTHandler(
                        transport=transport,
                        port=port,
                        output_dir=self.output_dir,
                    )
                else:
                    handler = WDRTUSBHandler(
                        transport=transport,
                        port=port,
                        output_dir=self.output_dir,
                    )

                handler.data_callback = self._on_device_data
                await handler.start()

                self.device_handlers[device_id] = handler
                self.device_types[device_id] = drt_device_type

                self.logger.info("Device %s assigned and started (%s)", device_id, drt_device_type.value)

                # Notify mode instance
                if self.mode_instance and hasattr(self.mode_instance, 'on_device_connected'):
                    await self.mode_instance.on_device_connected(device_id, drt_device_type)

                return True

        except Exception as e:
            self.logger.error("Failed to assign device %s: %s", device_id, e, exc_info=True)
            # Clean up on failure
            if device_id in self._transports:
                transport = self._transports.pop(device_id)
                await transport.disconnect()
            return False

    async def unassign_device(self, device_id: str) -> None:
        """
        Unassign a device from this module.

        Args:
            device_id: The device to unassign
        """
        if device_id not in self.device_handlers:
            self.logger.warning("Device %s not assigned", device_id)
            return

        self.logger.info("Unassigning device: %s", device_id)

        try:
            handler = self.device_handlers.pop(device_id)
            device_type = self.device_types.pop(device_id, None)

            await handler.stop()

            # Clean up transport
            if device_id in self._transports:
                transport = self._transports.pop(device_id)
                await transport.disconnect()

            # Notify mode instance
            if self.mode_instance and hasattr(self.mode_instance, 'on_device_disconnected'):
                await self.mode_instance.on_device_disconnected(device_id, device_type)

            self.logger.info("Device %s unassigned", device_id)

        except Exception as e:
            self.logger.error("Error unassigning device %s: %s", device_id, e, exc_info=True)

    async def _on_device_data(self, port: str, data_type: str, data: Dict[str, Any]):
        """Handle data received from device."""
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

        started_handlers: List[Tuple[str, BaseDRTHandler]] = []
        failures: List[str] = []

        for device_id, handler in self.device_handlers.items():
            try:
                success = await handler.start_experiment()
            except Exception as exc:
                self.logger.error("Exception starting experiment on %s: %s", device_id, exc, exc_info=True)
                success = False

            if success:
                started_handlers.append((device_id, handler))
            else:
                failures.append(device_id)

        if failures:
            self.logger.error("Failed to start recording on: %s", ", ".join(failures))
            for device_id, handler in started_handlers:
                try:
                    await handler.stop_experiment()
                except Exception as exc:
                    self.logger.warning("Rollback stop_experiment failed on %s: %s", device_id, exc, exc_info=True)
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

        for device_id, handler in self.device_handlers.items():
            try:
                success = await handler.stop_experiment()
            except Exception as exc:
                self.logger.error("Exception stopping experiment on %s: %s", device_id, exc, exc_info=True)
                success = False

            if not success:
                failures.append(device_id)

        if failures:
            self.logger.error("Failed to stop recording on: %s", ", ".join(failures))
            return False

        self.recording = False
        self.logger.info("DRT recording stopped for all devices")
        return True

    async def cleanup(self):
        """Clean up system resources."""
        self.logger.info("Cleaning up DRT system...")

        self.running = False
        self.shutdown_event.set()

        if self.recording:
            self.logger.info("Stopping recording before cleanup...")
            stopped = await self.stop_recording()
            if not stopped:
                self.logger.warning("Recording did not stop cleanly during cleanup")

        # Stop all handlers
        for device_id, handler in list(self.device_handlers.items()):
            try:
                await handler.stop()
            except Exception as exc:
                self.logger.warning(
                    "Error stopping handler during cleanup for %s: %s",
                    device_id, exc, exc_info=True
                )

        self.device_handlers.clear()
        self.device_types.clear()

        # Disconnect all transports
        for device_id, transport in list(self._transports.items()):
            try:
                await transport.disconnect()
            except Exception as exc:
                self.logger.warning(
                    "Error disconnecting transport for %s: %s",
                    device_id, exc, exc_info=True
                )

        self._transports.clear()

        self.initialized = False
        self.logger.info("DRT cleanup completed")

    def get_assigned_device_ids(self) -> List[str]:
        """Get list of assigned device IDs."""
        return list(self.device_handlers.keys())

    def get_connected_devices(self) -> Dict[str, DRTDeviceType]:
        """Return dict of device IDs to their types."""
        return self.device_types.copy()

    def get_device_handler(self, device_id: str) -> Optional[BaseDRTHandler]:
        """Get handler for a specific device."""
        return self.device_handlers.get(device_id)

    def get_device_type(self, device_id: str) -> Optional[DRTDeviceType]:
        """Get the device type for a specific device."""
        return self.device_types.get(device_id)

    def set_output_dir(self, output_dir: Path) -> None:
        """Set the output directory for all handlers."""
        self.output_dir = output_dir
        for handler in self.device_handlers.values():
            handler.output_dir = output_dir
