"""
Device Connection Coordinator - Orchestrates device connection lifecycle.

This module handles the complete connection/disconnection flow for devices,
coordinating between the device system, instance manager, module manager,
and state persistence.
"""

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Optional

from rpi_logger.core.logging_utils import get_module_logger
from .commands import CommandMessage
from .instance_identity import InstanceIdentity
from .instance_state import InstanceState

if TYPE_CHECKING:
    from .devices import DeviceInfo, DeviceSystem
    from .instance_manager import InstanceStateManager
    from .module_manager import ModuleManager
    from .state_facade import StateFacade
    from .window_manager import WindowGeometry


class DeviceConnectionCoordinator:
    """
    Coordinates device connection and disconnection lifecycle.

    This class handles:
    - Starting module instances for device connections
    - Sending assign_device commands to modules
    - Handling connection timeouts and errors
    - Cleaning up after disconnections (graceful or crash)
    - Persisting connection state
    """

    def __init__(
        self,
        device_system: "DeviceSystem",
        instance_manager: "InstanceStateManager",
        module_manager: "ModuleManager",
        state_facade: "StateFacade",
        identity: InstanceIdentity,
        session_dir_getter: Callable[[], Path],
        geometry_loader: Callable[[str, Optional[str]], "WindowGeometry"],
        xbee_callback_setter: Callable[[str], None],
    ):
        """
        Initialize the device connection coordinator.

        Args:
            device_system: The device system for device lookup and UI updates
            instance_manager: The instance state manager for lifecycle management
            module_manager: The module manager for process management
            state_facade: The state facade for persistence
            identity: The instance identity manager
            session_dir_getter: Callable that returns the current session directory
            geometry_loader: Callable to load window geometry for a module/instance
            xbee_callback_setter: Callable to set up XBee send callback for a module
        """
        self.logger = get_module_logger("DeviceConnectionCoordinator")
        self.device_system = device_system
        self.instance_manager = instance_manager
        self.module_manager = module_manager
        self._state = state_facade
        self._identity = identity
        self._get_session_dir = session_dir_getter
        self._load_geometry = geometry_loader
        self._setup_xbee_callback = xbee_callback_setter

    async def connect_device(self, device_id: str) -> bool:
        """Connect a device (called from UI).

        This delegates to connect_and_start_device which handles the full
        connection lifecycle including module startup.

        Args:
            device_id: The device to connect

        Returns:
            True if connection was initiated successfully
        """
        return await self.connect_and_start_device(device_id)

    async def disconnect_device(self, device_id: str) -> None:
        """Disconnect a device (called from UI).

        This delegates to stop_and_disconnect_device which handles the full
        disconnection lifecycle including module shutdown.

        Args:
            device_id: The device to disconnect
        """
        await self.stop_and_disconnect_device(device_id)

    async def connect_and_start_device(self, device_id: str) -> bool:
        """Connect a device and start its module instance.

        Called when user clicks the green dot or Connect button.
        Window is shown automatically when module starts.

        For multi-instance modules (DRT, VOG), each device gets its own
        module process instance (e.g., DRT:ACM0, DRT:ACM1).

        The connection flow uses the InstanceStateManager:
        1. Start instance (STOPPED -> STARTING -> RUNNING)
        2. Send assign_device command (RUNNING -> CONNECTING)
        3. Module sends device_ready (CONNECTING -> CONNECTED)
        4. UI updated via callback from InstanceStateManager

        Args:
            device_id: The device to connect

        Returns:
            True if device connection was initiated successfully.
        """
        self.logger.info("connect_and_start_device: %s", device_id)

        # Check if device uses a module-defined device_id_prefix (e.g., CSI cameras)
        from rpi_logger.core.devices.discovery_loader import get_discovery_registry
        registry = get_discovery_registry()
        device_spec = registry.get_module_for_device_id(device_id)

        camera_index: int | None = None
        uses_cli_init = False  # Modules that init via CLI args rather than assign_device

        if device_spec and device_spec.device_id_prefix:
            uses_cli_init = bool(device_spec.extra_cli_args)
            # Extract index from device_id (e.g., picam:0 → 0)
            if "camera_index" in device_spec.extra_cli_args:
                try:
                    camera_index = int(device_id.split(":")[1])
                except (IndexError, ValueError):
                    self.logger.error("Invalid device_id format for %s: %s",
                                      device_spec.module_id, device_id)
                    return False

        try:
            device = self.device_system.get_device(device_id)
            if not device:
                self.logger.info("Device not found: %s", device_id)
                return False

            module_id = device.module_id
            if not module_id:
                self.logger.info("Device has no module_id: %s", device_id)
                return False

            # Generate instance ID for this device
            instance_id = self._identity.make_instance_id(module_id, device_id)
            self.logger.info("Instance ID for device %s: %s", device_id, instance_id)

            # Check if already connected or in progress
            if self.instance_manager.is_instance_connected(instance_id):
                self.logger.info("Instance %s already connected", instance_id)
                return True
            if self.instance_manager.is_instance_running(instance_id):
                self.logger.info("Instance %s already starting/running", instance_id)
                return True

            # Load geometry for this instance (try instance-specific first for multi-instance)
            window_geometry = await self._load_geometry(module_id, instance_id)

            # Start instance via InstanceStateManager
            # For CSI cameras, pass camera_index so module can init camera directly via CLI arg
            success = await self.instance_manager.start_instance(
                instance_id=instance_id,
                module_id=module_id,
                device_id=device_id,
                window_geometry=window_geometry,
                camera_index=camera_index,
            )

            if not success:
                self.logger.error("Failed to start instance %s", instance_id)
                return False

            # Register device-to-instance mapping
            self._identity.register_device_instance(device_id, instance_id)

            # Set up XBee send callback for the instance
            self._setup_xbee_callback(instance_id)

            # Wait for module to become ready before sending connection command
            if not await self.instance_manager.wait_for_ready(instance_id, timeout=10.0):
                self.logger.error("Instance %s failed to become ready", instance_id)
                return False

            self.logger.info("Instance %s is ready, proceeding with device connection", instance_id)

            # Send assign_device command via InstanceStateManager (non-blocking)
            # Modules with extra_cli_args (e.g., CSI cameras) init via CLI arg, not assign_device
            if uses_cli_init:
                # Module inits on startup via CLI args. The module sends device_ready
                # when device is initialized and ready.
                await self._wait_for_cli_init_connected(instance_id, timeout=30.0)
            elif not device.is_internal:
                self.logger.info("Sending assign_device to non-internal device %s", device_id)
                command_builder = self._build_assign_device_command_builder(device)
                await self.instance_manager.connect_device(instance_id, command_builder)
            else:
                # Internal modules don't send device_ready (no hardware to connect)
                await self._state.on_device_connected(module_id)

            return True

        except Exception as e:
            self.logger.error("Failed to connect device %s: %s", device_id, e)
            return False

    async def _wait_for_cli_init_connected(self, instance_id: str, timeout: float = 30.0) -> bool:
        """Wait for a CLI-initialized instance to reach CONNECTED state.

        Used for modules that initialize via CLI arguments rather than assign_device
        command (e.g., CSI cameras with --camera-index).

        Args:
            instance_id: The instance to wait for
            timeout: Maximum time to wait in seconds (default 30s for device init)

        Returns:
            True if instance reached CONNECTED state, False on timeout
        """
        elapsed = 0.0
        interval = 0.2

        while elapsed < timeout:
            info = self.instance_manager.get_instance(instance_id)
            if not info:
                return False

            if info.state == InstanceState.CONNECTED:
                return True

            if info.state == InstanceState.STOPPED:
                # Process died during init
                return False

            await asyncio.sleep(interval)
            elapsed += interval

        self.logger.warning(
            "Timeout waiting for %s to connect (%.1fs)",
            instance_id, timeout
        )
        return False

    async def stop_and_disconnect_device(self, device_id: str) -> bool:
        """Stop module instance and disconnect device.

        Called when user clicks the green dot (when on) or Disconnect button.

        For multi-instance modules, stops only the instance associated with
        this specific device, leaving other instances running.

        Uses InstanceStateManager for state transitions:
        CONNECTED -> STOPPING -> STOPPED

        Args:
            device_id: The device to disconnect

        Returns:
            True if device is now disconnected.
        """
        self.logger.info("stop_and_disconnect_device: %s", device_id)

        device = self.device_system.get_device(device_id)
        if not device:
            self.logger.debug("Device not found: %s", device_id)
            self._identity.unregister_device_instance(device_id)
            self._notify_device_connected(device_id, False)
            return True

        module_id = device.module_id
        if not module_id:
            self.logger.debug("Device has no module_id: %s", device_id)
            self._identity.unregister_device_instance(device_id)
            self._notify_device_connected(device_id, False)
            return True

        # Get the instance ID for this device
        instance_id = self._identity.get_instance_for_device(device_id)
        if not instance_id:
            # Fall back to generating instance ID
            instance_id = self._identity.make_instance_id(module_id, device_id)

        # Stop instance via InstanceStateManager
        # This handles the STOPPING state and waiting for process exit
        await self.instance_manager.stop_instance(instance_id)

        # Unified cleanup: unregister, update UI, persist state
        await self.cleanup_device_disconnect(device_id, module_id)

        return True

    async def cleanup_device_disconnect(
        self, device_id: str, module_id: str, *, is_crash: bool = False
    ) -> None:
        """Unified cleanup after a device disconnects (from any path).

        This is the single convergence point for all device disconnection:
        - User clicks device label to disconnect
        - User closes module window via X button
        - Module crashes (is_crash=True)

        Args:
            device_id: The device that disconnected
            module_id: The module that owns the device
            is_crash: If True, skip normal persistence (crash uses on_module_crash separately)
        """
        # Get device info to check if internal
        device = self.device_system.get_device(device_id)
        is_internal = device.is_internal if device else False

        self._identity.unregister_device_instance(device_id)
        self._notify_device_connected(device_id, False)

        # Skip persistence for crash path (handled separately by on_module_crash)
        if is_crash:
            return

        if not self._identity.has_other_instances(module_id):
            if is_internal:
                # Internal modules (Notes, etc.): keep visible, just mark as not running
                await self._state.on_internal_module_closed(module_id)
            else:
                # Hardware devices: disable the device type entirely
                await self._state.on_user_disconnect(module_id)

    def _notify_device_connected(self, device_id: str, connected: bool) -> None:
        """Update device connection state in device_system.

        Args:
            device_id: The device identifier
            connected: Whether the device is connected
        """
        self.device_system.set_device_connected(device_id, connected)

    def _build_assign_device_command_builder(
        self, device: "DeviceInfo"
    ) -> Callable[[str], str]:
        """Build a command builder function for assign_device.

        Returns a function that takes a command_id and returns the full
        command JSON string. This is used by the robust connection system
        to inject correlation IDs for tracking.

        Args:
            device: The device info to build the command for

        Returns:
            A function that takes command_id and returns command JSON string
        """
        session_dir = self._get_session_dir()
        session_dir_str = str(session_dir) if session_dir else None

        def builder(command_id: str) -> str:
            return CommandMessage.assign_device(
                device_id=device.device_id,
                device_type=device.device_type.value,
                port=device.port or "",
                baudrate=device.baudrate,
                session_dir=session_dir_str,
                is_wireless=device.is_wireless,
                is_network=device.is_network,
                network_address=device.get_meta("network_address"),
                network_port=device.get_meta("network_port"),
                sounddevice_index=device.get_meta("sounddevice_index"),
                audio_channels=device.get_meta("audio_channels"),
                audio_sample_rate=device.get_meta("audio_sample_rate"),
                is_camera=device.is_camera,
                camera_type=device.get_meta("camera_type"),
                camera_stable_id=device.get_meta("camera_stable_id"),
                camera_dev_path=device.get_meta("camera_dev_path"),
                camera_hw_model=device.get_meta("camera_hw_model"),
                camera_location=device.get_meta("camera_location"),
                camera_index=device.get_meta("camera_index"),
                # Audio sibling info for webcams with built-in microphones
                camera_audio_index=device.get_meta("camera_audio_index"),
                camera_audio_channels=device.get_meta("camera_audio_channels"),
                camera_audio_sample_rate=device.get_meta("camera_audio_sample_rate"),
                camera_audio_alsa_card=device.get_meta("camera_audio_alsa_card"),
                display_name=device.display_name,
                command_id=command_id,  # Inject correlation ID
            )

        return builder

    async def load_pending_auto_connects(
        self,
        modules: list,
        is_module_enabled: Callable[[str], bool],
    ) -> None:
        """Load device connection states and mark modules for auto-connect.

        Only marks modules for auto-connect if they are enabled (checked in
        Modules menu). This ensures disabled modules don't auto-connect their
        devices on startup.

        Args:
            modules: List of available module info objects
            is_module_enabled: Callable to check if a module is enabled
        """
        for module_info in modules:
            # Only auto-connect if the module is enabled
            if not is_module_enabled(module_info.name):
                continue

            # Load persisted state
            state = await self._state.load_module_state(module_info.name)

            if state.device_connected:
                self.logger.info("Module %s marked for auto-connect", module_info.name)
                self.device_system.request_auto_connect(module_info.name)
