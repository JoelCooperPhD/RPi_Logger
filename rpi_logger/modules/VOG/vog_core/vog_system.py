"""VOG system coordinator with USB device management for sVOG and wVOG devices."""

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
from .protocols import SVOGProtocol, WVOGProtocol


class VOGSystem(BaseSystem, RecordingStateMixin):
    """Main system coordinator for VOG module.

    Supports both sVOG (wired) and wVOG (wireless) devices with automatic
    protocol detection based on USB VID/PID.
    """

    DEFER_DEVICE_INIT_IN_GUI = True

    # Device identification constants
    SVOG_VID = 0x16C0
    SVOG_PID = 0x0483
    SVOG_BAUD = 115200  # Firmware uses 115200

    WVOG_VID = 0xf057
    WVOG_PID = 0x08AE
    WVOG_BAUD = 57600

    def __init__(self, args):
        super().__init__(args)
        RecordingStateMixin.__init__(self)

        self.usb_monitors: Dict[str, USBDeviceMonitor] = {}
        self.device_handlers: Dict[str, VOGHandler] = {}
        self.output_dir: Optional[Path] = None

        # Track active trial for all handlers
        self.active_trial_number: int = 0

    async def _initialize_devices(self) -> None:
        """Initialize USB device monitoring for sVOG and wVOG devices."""
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

            # Configure device monitors for both device types
            device_configs = self._get_device_configs()

            for device_type, config in device_configs.items():
                monitor = USBDeviceMonitor(
                    config=config,
                    on_connect=self._on_device_connected,
                    on_disconnect=self._on_device_disconnected
                )
                await monitor.start()
                self.usb_monitors[device_type] = monitor
                self.logger.info("Started USB monitor for %s (VID=%s, PID=%s)",
                                 device_type, hex(config.vid), hex(config.pid))

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
                    "usb_monitors_active": len(self.usb_monitors),
                    "devices": list(device_configs.keys())
                })

        except VOGInitializationError:
            raise
        except Exception as e:
            error_msg = f"Failed to initialize VOG: {e}"
            self.logger.error(error_msg, exc_info=True)
            raise VOGInitializationError(error_msg) from e

    def _get_device_configs(self) -> Dict[str, USBDeviceConfig]:
        """Get USB device configurations for monitored devices.

        Returns configuration for both sVOG and wVOG devices. If VID/PID
        are specified in args, those are used for the primary device.
        """
        configs = {}

        # Get primary device from args (maintains backwards compatibility)
        primary_vid = self._parse_hex_value(self.args.device_vid)
        primary_pid = self._parse_hex_value(self.args.device_pid)
        primary_baud = self.args.baudrate

        # Determine which device type args specify
        if primary_vid == self.WVOG_VID and primary_pid == self.WVOG_PID:
            # Args specify wVOG
            configs['wvog'] = USBDeviceConfig(
                vid=primary_vid,
                pid=primary_pid,
                baudrate=primary_baud or self.WVOG_BAUD,
                device_name="wVOG"
            )
            # Also monitor sVOG
            configs['svog'] = USBDeviceConfig(
                vid=self.SVOG_VID,
                pid=self.SVOG_PID,
                baudrate=self.SVOG_BAUD,
                device_name="sVOG"
            )
        elif primary_vid == self.SVOG_VID and primary_pid == self.SVOG_PID:
            # Args specify sVOG
            configs['svog'] = USBDeviceConfig(
                vid=primary_vid,
                pid=primary_pid,
                baudrate=primary_baud or self.SVOG_BAUD,
                device_name="sVOG"
            )
            # Also monitor wVOG
            configs['wvog'] = USBDeviceConfig(
                vid=self.WVOG_VID,
                pid=self.WVOG_PID,
                baudrate=self.WVOG_BAUD,
                device_name="wVOG"
            )
        else:
            # Unknown or no VID/PID specified - monitor both
            configs['svog'] = USBDeviceConfig(
                vid=self.SVOG_VID,
                pid=self.SVOG_PID,
                baudrate=self.SVOG_BAUD,
                device_name="sVOG"
            )
            configs['wvog'] = USBDeviceConfig(
                vid=self.WVOG_VID,
                pid=self.WVOG_PID,
                baudrate=self.WVOG_BAUD,
                device_name="wVOG"
            )

        return configs

    def _parse_hex_value(self, value) -> int:
        """Parse a hex value from string or int."""
        if isinstance(value, str):
            return int(value, 0)  # Auto-detect base
        return value

    def _determine_device_type(self, device: USBSerialDevice) -> str:
        """Determine device type from VID/PID."""
        # USBSerialDevice stores VID/PID in its config
        config = getattr(device, 'config', None)
        if config:
            vid = getattr(config, 'vid', None)
            pid = getattr(config, 'pid', None)
        else:
            vid = getattr(device, 'vid', None)
            pid = getattr(device, 'pid', None)

        if vid == self.WVOG_VID and pid == self.WVOG_PID:
            return 'wvog'
        return 'svog'

    async def _on_device_connected(self, device: USBSerialDevice):
        """Handle new device connection."""
        device_type = self._determine_device_type(device)
        self.logger.info("VOGSystem: %s device connected on %s", device_type.upper(), device.port)

        # Create appropriate protocol
        if device_type == 'wvog':
            protocol = WVOGProtocol()
        else:
            protocol = SVOGProtocol()

        handler = VOGHandler(
            device, device.port, self.output_dir,
            system=self, protocol=protocol
        )
        handler.set_data_callback(self._on_device_data)

        await handler.initialize_device()
        await handler.start()

        self.device_handlers[device.port] = handler
        self.logger.info("VOGSystem: Handler registered for %s (%s)", device.port, device_type)

        if self.mode_instance and hasattr(self.mode_instance, 'on_device_connected'):
            await self.mode_instance.on_device_connected(device.port)

    async def _on_device_disconnected(self, port: str):
        """Handle device disconnection."""
        handler = self.device_handlers.get(port)
        device_type = handler.device_type if handler else 'unknown'

        self.logger.info("%s device disconnected from %s", device_type.upper(), port)

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
        """Start recording on all connected devices.

        This sends both exp>1 (start experiment) and trl>1 (start trial) to
        begin cycling. For proper separation, use start_session() followed
        by start_trial() separately.
        """
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
                # Start experiment first (exp>1)
                exp_ok = await handler.start_experiment()
                if not exp_ok:
                    raise RuntimeError("start_experiment failed")
                # Then start trial (trl>1)
                trial_ok = await handler.start_trial()
                if not trial_ok:
                    raise RuntimeError("start_trial failed")
                success = True
            except Exception as exc:
                self.logger.error(
                    "Exception starting recording on %s: %s",
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
                    await handler.stop_trial()
                    await handler.stop_experiment()
                except Exception as exc:
                    self.logger.warning(
                        "Rollback failed on %s: %s",
                        port, exc, exc_info=True
                    )
            return False

        self.recording = True
        self.logger.info("VOG recording started for all devices (exp>1, trl>1)")
        return True

    async def stop_recording(self) -> bool:
        """Stop recording on all connected devices.

        This sends both trl>0 (stop trial) and exp>0 (stop experiment).
        """
        can_stop, error_msg = self.validate_recording_stop()
        if not can_stop:
            self.logger.warning("Cannot stop recording: %s", error_msg)
            return False

        failures: List[str] = []

        for port, handler in self.device_handlers.items():
            try:
                # Stop trial first (trl>0)
                await handler.stop_trial()
                # Then stop experiment (exp>0)
                await handler.stop_experiment()
                success = True
            except Exception as exc:
                self.logger.error(
                    "Exception stopping recording on %s: %s",
                    port, exc, exc_info=True
                )
                success = False

            if not success:
                failures.append(port)

        if failures:
            self.logger.error("Failed to stop recording on ports: %s", ", ".join(failures))
            return False

        self.recording = False
        self.logger.info("VOG recording stopped for all devices (trl>0, exp>0)")
        return True

    async def peek_open_all(self, lens: str = 'x') -> bool:
        """Send peek/lens open command to all devices.

        Args:
            lens: 'a', 'b', or 'x' (both) - only affects wVOG devices
        """
        for handler in self.device_handlers.values():
            await handler.peek_open(lens)
        return True

    async def peek_close_all(self, lens: str = 'x') -> bool:
        """Send peek/lens close command to all devices.

        Args:
            lens: 'a', 'b', or 'x' (both) - only affects wVOG devices
        """
        for handler in self.device_handlers.values():
            await handler.peek_close(lens)
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

        # Stop all USB monitors
        for device_type, monitor in self.usb_monitors.items():
            self.logger.debug("Stopping USB monitor for %s", device_type)
            await monitor.stop()
        self.usb_monitors.clear()

        # Stop all handlers
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
        """Get all connected USB devices from all monitors."""
        devices = {}
        for monitor in self.usb_monitors.values():
            devices.update(monitor.get_devices())
        return devices

    def get_device_handler(self, port: str) -> Optional[VOGHandler]:
        """Get handler for a specific port."""
        return self.device_handlers.get(port)

    def get_handlers_by_type(self, device_type: str) -> List[VOGHandler]:
        """Get all handlers of a specific device type.

        Args:
            device_type: 'svog' or 'wvog'

        Returns:
            List of handlers matching the device type
        """
        return [h for h in self.device_handlers.values() if h.device_type == device_type]
