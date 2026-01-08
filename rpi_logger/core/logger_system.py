"""
Logger System - Main coordinator for Logger.

This is the facade that coordinates between ModuleManager, SessionManager,
WindowManager, and other components. It provides a unified API for the UI.

The LoggerSystem now integrates with ModuleStateManager for centralized
state management and uses observers for state synchronization.
"""

import asyncio
import time
from rpi_logger.core.logging_utils import get_module_logger
from pathlib import Path
from typing import Dict, List, Optional, Callable, Set, TYPE_CHECKING

from .module_discovery import ModuleInfo
from .module_process import ModuleState
from .module_state_manager import (
    ModuleStateManager,
    StateChange,
    StateEvent,
    ActualState,
    DesiredState,
    RUNNING_STATES,
)
from .observers import UIStateObserver
from .platform_info import get_platform_info
from .state_facade import StateFacade
from .commands import StatusMessage, CommandMessage
from .window_manager import WindowManager, WindowGeometry
from rpi_logger.modules.base import gui_utils
from .config_manager import get_config_manager
from .module_manager import ModuleManager
from .session_manager import SessionManager
from .instance_manager import InstanceStateManager
from .instance_state import InstanceState
from .devices import (
    DeviceSystem, InterfaceType, DeviceFamily,
    DeviceInfo,
)

if TYPE_CHECKING:
    from .event_logger import EventLogger


class LoggerSystem:
    """
    Main coordinator for the logger system.

    This class acts as a facade, delegating to specialized managers:
    - ModuleManager: Module discovery and lifecycle
    - SessionManager: Session and recording control
    - WindowManager: Window layout and geometry
    - ModuleStateManager: Centralized state tracking
    - ModuleStatePersistence: Centralized state persistence

    State synchronization is handled through:
    - StateFacade: Unified state persistence (lifecycle, geometry, preferences)
    - UIStateObserver: Updates UI elements based on state changes
    """

    def __init__(
        self,
        session_dir: Path,
        session_prefix: str = "session",
        log_level: str = "info",
        ui_callback: Optional[Callable] = None,
    ):
        self.logger = get_module_logger("LoggerSystem")

        # Detect platform early - before module discovery
        self.platform_info = get_platform_info()
        self.logger.info("Platform: %s", self.platform_info)

        self.idle_session_dir = Path(session_dir)
        self._session_dir = Path(session_dir)
        self.session_prefix = session_prefix
        self.log_level = log_level
        self.ui_callback = ui_callback

        # Create the centralized state manager
        self.state_manager = ModuleStateManager()

        # Create managers with shared state manager
        self.module_manager = ModuleManager(
            session_dir=self._session_dir,
            session_prefix=session_prefix,
            log_level=log_level,
            status_callback=self._module_status_callback,
            state_manager=self.state_manager,
        )
        self.session_manager = SessionManager()
        self.window_manager = WindowManager()
        self.config_manager = get_config_manager()

        # Create unified state facade (lifecycle, geometry, preferences)
        module_configs = {
            m.name: m.config_path
            for m in self.module_manager.get_available_modules()
        }
        self._state = StateFacade(module_configs)

        # Create UI observer (only observer we still need)
        self._ui_observer = UIStateObserver()

        # Register UI observer with state manager
        self.state_manager.add_observer(
            self._ui_observer,
            events={
                StateEvent.DESIRED_STATE_CHANGED,
                StateEvent.ACTUAL_STATE_CHANGED,
            }
        )

        # Device system for scanning, UI, and connection lifecycle
        self.device_system = DeviceSystem()
        self.device_system.set_xbee_data_callback(self._route_xbee_to_module)
        # Configure which modules support multiple simultaneous instances
        # These modules auto-connect ALL their devices, not just the first one
        self.device_system.set_multi_instance_modules(self.MULTI_INSTANCE_MODULES)

        # State
        self.event_logger: Optional['EventLogger'] = None
        self._gracefully_quitting_modules: set[str] = set()
        self._startup_modules: Set[str] = set()

        # Device-to-instance mapping for multi-instance modules
        # Maps device_id -> instance_id (e.g., "ACM0" -> "DRT:ACM0")
        self._device_instance_map: Dict[str, str] = {}

        # Instance state manager - single source of truth for instance lifecycle
        self.instance_manager = InstanceStateManager(
            module_manager=self.module_manager,
            ui_update_callback=self._on_instance_ui_update,
        )

    @property
    def session_dir(self) -> Path:
        return self._session_dir

    @session_dir.setter
    def session_dir(self, value: Path) -> None:
        self.set_session_dir(value)

    @property
    def idle_session_path(self) -> Path:
        return self.idle_session_dir

    def set_session_dir(self, session_dir: Path) -> None:
        """Update the active session directory for module coordination."""
        new_path = Path(session_dir)
        self._session_dir = new_path
        self.module_manager.set_session_dir(new_path)
        self.logger.info("Active session directory set to: %s", new_path)

    def set_idle_session_dir(self, session_dir: Path) -> None:
        """Update the idle (pre-session) directory."""
        self.idle_session_dir = Path(session_dir)
        self.logger.info("Idle session directory set to: %s", self.idle_session_dir)
        if not self.session_manager.recording:
            self.set_session_dir(self.idle_session_dir)

    def reset_session_dir(self) -> None:
        """Return to the idle directory after a session finishes."""
        self.set_session_dir(self.idle_session_dir)

    # =========================================================================
    # Initialization
    # =========================================================================

    async def async_init(self) -> None:
        """Complete async initialization. Must be called after construction."""
        await self._load_enabled_modules()
        await self.module_manager.start_health_check()

    async def _load_enabled_modules(self) -> None:
        """
        Load enabled modules asynchronously.

        Priority:
        1. If running_modules.json exists (crash recovery), use that
        2. Otherwise, load from individual module config.txt files
        """
        # Try to load from session recovery file first
        running_modules = await self._state.load_recovery_state()

        if running_modules:
            # Session recovery - restore previously running modules
            self.logger.info("Restoring modules from last session: %s", running_modules)
            self._startup_modules = running_modules.copy()

            # Set desired state for recovered modules
            for module_name in running_modules:
                await self.state_manager.set_desired_state(
                    module_name, True, reconcile=False
                )
                self.state_manager.mark_startup_module(module_name)
        else:
            # Fresh start - load from config files
            await self.module_manager.load_enabled_modules()

    async def on_startup_complete(self) -> None:
        """
        Called after auto_start_modules finishes.

        This verifies startup success and cleans up the recovery state file.
        """
        # Check if all startup modules successfully started
        await self.state_manager.check_startup_complete()

        # Update state file with actually running modules
        running = set(self.module_manager.get_running_modules())
        await self._state.save_startup_snapshot(running)

        # Transition to running phase
        self._state.enter_running_phase()

        # Clear auto-connected devices set to allow future auto-connects
        # if devices are reconnected during the session
        self.device_system.clear_auto_connected_devices()

    # =========================================================================
    # Module Status Callback
    # =========================================================================

    async def _module_status_callback(
        self,
        process,
        status: Optional[StatusMessage],
        instance_id: Optional[str] = None
    ) -> None:
        """Handle status updates from module processes.

        Args:
            process: The module process
            status: The status message (if any)
            instance_id: For multi-instance modules, the instance ID (e.g., "DRT:ACM0")
        """
        module_name = process.module_info.name
        effective_id = instance_id or module_name

        if status:
            self.logger.debug(
                "Module %s status: %s (instance: %s)",
                module_name, status.get_status_type(), effective_id
            )

            if status.get_status_type() == "recording_started":
                self.logger.info("Module %s started recording", module_name)
                await self.state_manager.set_actual_state(
                    module_name, ActualState.RECORDING
                )
            elif status.get_status_type() == "recording_stopped":
                self.logger.info("Module %s stopped recording", module_name)
                await self.state_manager.set_actual_state(
                    module_name, ActualState.IDLE
                )
            elif status.get_status_type() == "quitting":
                self.logger.info("Module/instance quitting: %s", effective_id)
                self._gracefully_quitting_modules.add(effective_id)

                # Route to instance manager for state tracking
                self.instance_manager.on_status_message(
                    effective_id, "quitting", status.get_payload()
                )

                # Unified cleanup - find device and clean up (same for all modules)
                device_id = self._find_device_for_instance(effective_id)
                if device_id:
                    await self._cleanup_device_disconnect(device_id, module_name)
                else:
                    self.logger.warning(
                        "No device found for instance %s, cleanup skipped", effective_id
                    )

                if self.ui_callback:
                    try:
                        await self.ui_callback(effective_id, process.get_state(), status)
                    except Exception as e:
                        self.logger.error("UI callback error: %s", e)
                return

            elif status.get_status_type() == "ready":
                self.instance_manager.on_status_message(
                    effective_id, "ready", status.get_payload()
                )
            elif status.get_status_type() == "device_ready":
                device_id = status.get_payload().get("device_id")
                if device_id:
                    self.logger.info("Device %s ready", device_id)
                    self.instance_manager.on_status_message(
                        effective_id, "device_ready", status.get_payload()
                    )
                    await self._state.on_device_connected(module_name)
                else:
                    self.logger.warning("device_ready status missing device_id")
            elif status.get_status_type() == "device_error":
                device_id = status.get_payload().get("device_id")
                error_msg = status.get_payload().get("error", "Unknown error")
                if device_id:
                    self.logger.error("Device %s failed: %s", device_id, error_msg)
                    self.instance_manager.on_status_message(
                        effective_id, "device_error", status.get_payload()
                    )
                else:
                    self.logger.warning("device_error status missing device_id")
            elif status.get_status_type() in ("window_hidden", "window_shown"):
                pass  # Window visibility tied to connection state
            elif status.get_status_type() == "geometry_changed":
                payload = status.get_payload()
                geom_instance_id = payload.get("instance_id") or module_name
                geometry = WindowGeometry(
                    x=payload.get("x", 0),
                    y=payload.get("y", 0),
                    width=payload.get("width", 800),
                    height=payload.get("height", 600),
                )
                self._state.set_geometry(geom_instance_id, geometry)
            elif status.is_error():
                self.logger.error("Module %s error: %s",
                                module_name,
                                status.get_error_message())

        # Handle unexpected process termination
        if not process.is_running():
            self.instance_manager.on_process_exit(effective_id)

            # Only handle as crash if not gracefully quitting and not shutting down
            if effective_id not in self._gracefully_quitting_modules:
                if not self._state.is_shutting_down():
                    self.logger.warning("Module %s crashed/stopped unexpectedly", effective_id)

                    # Unified cleanup (is_crash=True skips normal persistence)
                    device_id = self._find_device_for_instance(effective_id)
                    if device_id:
                        await self._cleanup_device_disconnect(device_id, module_name, is_crash=True)

                    await self._state.on_module_crash(module_name)

        if not process.is_running() and effective_id in self._gracefully_quitting_modules:
            self._gracefully_quitting_modules.discard(effective_id)

        if self.ui_callback:
            try:
                await self.ui_callback(effective_id, process.get_state(), status)
            except Exception as e:
                self.logger.error("UI callback error: %s", e)

    def _has_other_instances(self, module_name: str) -> bool:
        """Check if other instances of this module are still running."""
        module_prefix = f"{module_name.upper()}:"
        return any(
            inst_id.startswith(module_prefix)
            for inst_id in self._device_instance_map.values()
        )

    def _notify_device_connected(self, device_id: str, connected: bool) -> None:
        """Update device connection state in device_system."""
        self.logger.debug("Device %s connected=%s", device_id, connected)
        self.device_system.set_device_connected(device_id, connected)

    def _notify_device_connecting(self, device_id: str) -> None:
        """Set device to CONNECTING state (yellow indicator)."""
        self.logger.debug("Device %s connecting", device_id)
        self.device_system.set_device_connecting(device_id)

    async def _on_instance_ui_update(
        self, device_id: str, connected: bool, connecting: bool
    ) -> None:
        """Callback from InstanceStateManager to update UI state.

        This is the single point where device UI state is updated based on
        instance lifecycle state.
        """
        self.logger.debug(
            "Instance UI update: device=%s connected=%s connecting=%s",
            device_id, connected, connecting
        )
        if connected:
            self.device_system.set_device_connected(device_id, True)
        elif connecting:
            self.device_system.set_device_connecting(device_id)
        else:
            self.device_system.set_device_connected(device_id, False)

    def notify_devices_changed(self) -> None:
        """Notify UI observers that the device list/state has changed.

        This triggers a UI refresh for the Devices panel. Called when:
        - A connection type is enabled/disabled (module checkbox toggled)
        - Device sections need to be shown/hidden based on module state

        The DeviceUIController observes model changes automatically, but this
        method provides an explicit trigger for cases where the observer chain
        may not fire (e.g., bulk state changes during startup).
        """
        if self.device_system.ui_controller:
            self.device_system.ui_controller._notify_ui_observers()

    # =========================================================================
    # UI Observer Access
    # =========================================================================

    def get_ui_observer(self) -> UIStateObserver:
        """Get the UI state observer for registering checkboxes."""
        return self._ui_observer

    def register_ui_checkbox(self, module_name: str, var) -> None:
        """Register a UI checkbox variable for a module."""
        self._ui_observer.register_checkbox(module_name, var)

    def set_ui_root(self, root) -> None:
        """Set the Tk root for thread-safe UI updates."""
        self._ui_observer.set_root(root)

    def shutdown_ui_observer(self) -> None:
        """Shutdown the UI observer to prevent Tcl errors during cleanup."""
        self._ui_observer.shutdown()

    # =========================================================================
    # Module Management (delegate to ModuleManager)
    # =========================================================================

    def get_available_modules(self) -> List[ModuleInfo]:
        """Get list of all discovered modules."""
        return self.module_manager.get_available_modules()

    def get_selected_modules(self) -> List[str]:
        """Get list of selected module names."""
        return self.module_manager.get_selected_modules()

    async def toggle_module_enabled(self, module_name: str, enabled: bool) -> bool:
        """Update a module's enabled state in config."""
        return await self.module_manager.toggle_module_enabled(module_name, enabled)

    def is_module_running(self, module_name: str) -> bool:
        """Check if a module is running."""
        return self.module_manager.is_module_running(module_name)

    def is_module_quitting(self, module_name: str) -> bool:
        """Check if a module is in the process of shutting down."""
        return module_name in self._gracefully_quitting_modules

    async def wait_for_module_shutdown(
        self, module_name: str, timeout: float = 3.0
    ) -> bool:
        """Wait for a module to finish shutting down.

        Args:
            module_name: The module or instance ID to wait for
            timeout: Maximum time to wait in seconds

        Returns:
            True if module is now stopped, False if timeout
        """
        if not self.is_module_quitting(module_name):
            return True

        self.logger.info("Waiting for %s to finish shutting down...", module_name)
        elapsed = 0.0
        interval = 0.1
        while elapsed < timeout:
            await asyncio.sleep(interval)
            elapsed += interval
            if not self.is_module_quitting(module_name):
                self.logger.info("Module %s shutdown complete", module_name)
                return True

        self.logger.warning("Timeout waiting for %s to shut down", module_name)
        return False

    def get_module_state(self, module_name: str) -> Optional[ModuleState]:
        """Get the state of a module."""
        return self.module_manager.get_module_state(module_name)

    def get_running_modules(self) -> List[str]:
        """Get list of currently running module names."""
        return self.module_manager.get_running_modules()

    async def send_module_command(self, module_name: str, command: str, **kwargs) -> bool:
        """Send a command to a running module via its command interface."""
        payload = CommandMessage.create(command, **kwargs)
        return await self.module_manager.send_command(module_name, payload)

    async def start_module(self, module_name: str) -> bool:
        """Start a module (routes through state machine)."""
        window_geometry = await self._load_module_geometry(module_name)
        self.module_manager.set_window_geometry(module_name, window_geometry)
        success = await self.module_manager.start_module(module_name)
        if success:
            # Set up XBee send callback for the module
            self._setup_xbee_send_callback(module_name)
        return success

    async def set_module_enabled(self, module_name: str, enabled: bool) -> bool:
        """Set module enabled state (central state machine entry point)."""
        if enabled:
            window_geometry = await self._load_module_geometry(module_name)
            self.module_manager.set_window_geometry(module_name, window_geometry)
        success = await self.module_manager.set_module_enabled(module_name, enabled)
        if success and enabled:
            # Set up XBee send callback for the module
            self._setup_xbee_send_callback(module_name)
        return success

    # NOTE: start_module_instance and _connection_timeout_check have been removed.
    # Use InstanceStateManager.start_instance() and connect_device() instead.
    # The instance manager handles state transitions and timeouts automatically.

    async def stop_module_instance(self, instance_id: str) -> bool:
        """Stop a specific module instance.

        Args:
            instance_id: Instance ID to stop (e.g., "DRT:ACM0")

        Returns:
            True if the instance was stopped successfully
        """
        self.logger.info("Stopping module instance %s", instance_id)
        return await self.module_manager.stop_module_instance(instance_id)

    def has_running_instances(self, module_id: str) -> bool:
        """Check if any instances of a module are running."""
        return self.instance_manager.has_running_instances(module_id)

    async def stop_all_instances_for_module(self, module_id: str) -> bool:
        """Stop all running instances of a module.

        Args:
            module_id: Base module ID (e.g., "Cameras", "DRT")

        Returns:
            True if all instances stopped successfully
        """
        self.logger.info("Stopping all instances of module %s", module_id)
        return await self.instance_manager.stop_all_instances_for_module(module_id)

    def is_module_enabled(self, module_name: str) -> bool:
        """Check if module is enabled (checkbox state)."""
        return self.state_manager.is_module_enabled(module_name)

    def get_module_enabled_states(self) -> Dict[str, bool]:
        """Get all module enabled states."""
        return self.state_manager.get_desired_states()

    def _normalize_geometry(self, geometry: WindowGeometry) -> WindowGeometry:
        width, height, x, y = gui_utils.clamp_geometry_to_screen(
            geometry.width,
            geometry.height,
            geometry.x,
            geometry.y,
            screen_height=self.window_manager.screen_height,
        )
        return WindowGeometry(x=x, y=y, width=width, height=height)

    async def _load_module_geometry(
        self, module_name: str, instance_id: Optional[str] = None
    ) -> Optional[WindowGeometry]:
        """Load saved window geometry for a module or instance.

        For multi-instance modules (DRT, VOG), pass instance_id (e.g., "DRT:ACM0")
        to load geometry specific to that device instance.

        Checks InstanceGeometryStore first (primary), then falls back to
        module config files for backwards compatibility.

        Args:
            module_name: The module name (e.g., "DRT")
            instance_id: Optional instance ID for multi-instance modules (e.g., "DRT:ACM0")
        """
        # For multi-instance modules, try instance-specific geometry first
        if instance_id and instance_id != module_name:
            geometry = self._state.get_geometry(instance_id)
            if geometry:
                normalized = self._normalize_geometry(geometry)
                self.logger.debug(
                    "Loaded geometry from store for instance %s: %s",
                    instance_id, geometry.to_geometry_string()
                )
                return normalized

        # Try module-level geometry in store
        geometry = self._state.get_geometry(module_name)
        if geometry:
            normalized = self._normalize_geometry(geometry)
            self.logger.debug(
                "Loaded geometry from store for %s: %s",
                module_name, geometry.to_geometry_string()
            )
            return normalized

        # Fallback: Check module config file
        modules = self.module_manager.get_available_modules()
        module_info = next((m for m in modules if m.name == module_name), None)

        if not module_info or not module_info.config_path:
            self.logger.debug("No config path for module %s", module_name)
            return None

        config = await self.config_manager.read_config_async(module_info.config_path)

        # Try to load from "window_geometry" string in config
        geometry_str = self.config_manager.get_str(config, 'window_geometry', default=None)
        if geometry_str:
            try:
                geometry = WindowGeometry.from_geometry_string(geometry_str)
                if geometry:
                    normalized = self._normalize_geometry(geometry)
                    self.logger.debug("Loaded geometry from config for %s: %s", module_name, geometry_str)
                    return normalized
            except Exception:
                self.logger.warning("Failed to parse window_geometry for %s: %s", module_name, geometry_str)

        # Legacy fallback: decomposed fields
        x = self.config_manager.get_int(config, 'window_x', default=None)
        y = self.config_manager.get_int(config, 'window_y', default=None)
        width = self.config_manager.get_int(config, 'window_width', default=None)
        height = self.config_manager.get_int(config, 'window_height', default=None)

        if all(v is not None for v in [x, y, width, height]):
            geometry = WindowGeometry(x=x, y=y, width=width, height=height)
            self.logger.debug("Loaded legacy geometry for %s: %s", module_name, geometry.to_geometry_string())
            return geometry
        else:
            self.logger.debug("No saved geometry found for %s", module_name)
            return None

    async def stop_module(self, module_name: str) -> bool:
        """Stop a module."""
        return await self.module_manager.stop_module(module_name)

    # =========================================================================
    # Session Management (delegate to SessionManager)
    # =========================================================================

    async def start_session_all(self) -> Dict[str, bool]:
        """Start session on all modules."""
        return await self.session_manager.start_session_all(
            self.module_manager.module_processes,
            self.session_dir
        )

    async def stop_session_all(self) -> Dict[str, bool]:
        """Stop session on all modules."""
        return await self.session_manager.stop_session_all(
            self.module_manager.module_processes
        )

    async def record_all(self, trial_number: int = None, trial_label: str = None) -> Dict[str, bool]:
        """Start recording on all modules."""
        return await self.session_manager.record_all(
            self.module_manager.module_processes,
            self.session_dir,
            trial_number,
            trial_label
        )

    async def pause_all(self) -> Dict[str, bool]:
        """Pause recording on all modules."""
        return await self.session_manager.pause_all(
            self.module_manager.module_processes
        )

    async def get_status_all(self) -> Dict[str, ModuleState]:
        """Get status from all modules."""
        return await self.session_manager.get_status_all(
            self.module_manager.module_processes
        )

    def is_any_recording(self) -> bool:
        """Check if any module is recording."""
        return self.session_manager.is_any_recording(
            self.module_manager.module_processes
        )

    @property
    def recording(self) -> bool:
        """Check if currently recording."""
        return self.session_manager.recording

    # =========================================================================
    # Cleanup and State Management
    # =========================================================================

    async def stop_all(self) -> None:
        """Stop all modules."""
        self.logger.info("Stopping all modules")

        if self.session_manager.recording:
            pause_start = time.time()
            await self.pause_all()
            self.logger.info("Paused all modules in %.3fs", time.time() - pause_start)

        stop_start = time.time()
        await self.module_manager.stop_all()
        self.logger.info("Stopped all modules in %.3fs", time.time() - stop_start)

    async def save_running_modules_state(self) -> bool:
        """Persist snapshot of modules running at shutdown initiation."""
        running_modules = set(self.module_manager.get_running_modules())

        # Mark forcefully stopped modules
        for module_name in self.module_manager.forcefully_stopped_modules:
            self._state.mark_forcefully_stopped(module_name)

        return await self._state.save_shutdown_snapshot(running_modules)

    async def update_running_modules_state_after_cleanup(self) -> bool:
        """Rewrite restart state excluding modules that failed to stop cleanly."""
        running_modules = set(self.module_manager.get_running_modules())

        # Mark any newly forcefully stopped modules
        for module_name in self.module_manager.forcefully_stopped_modules:
            self._state.mark_forcefully_stopped(module_name)

        return await self._state.save_shutdown_snapshot(running_modules)

    async def cleanup(self, request_geometry: bool = False) -> None:
        """Cleanup all resources.

        Args:
            request_geometry: Unused, geometry is saved by modules during quit.
        """
        self.logger.info("Cleaning up logger system")

        # Enter shutdown phase BEFORE stopping modules so status callbacks
        # can detect we're in shutdown mode and preserve device_connected state
        self._state.enter_shutdown_phase()

        await self.module_manager.stop_health_check()
        await self.stop_all()

    def get_session_info(self) -> dict:
        """Get information about the current session."""
        running_modules = self.module_manager.get_running_modules()
        return {
            "session_dir": str(self.session_dir),
            "session_name": self.session_dir.name,
            "recording": self.session_manager.recording,
            "selected_modules": self.module_manager.get_selected_modules(),
            "running_modules": running_modules,
        }

    # =========================================================================
    # Device Management
    # =========================================================================

    async def start_device_scanning(self) -> None:
        """Start USB and XBee device scanning."""
        # Start instance state manager for lifecycle tracking
        await self.instance_manager.start()

        # Load device connection states and mark modules for auto-connect
        await self._load_pending_auto_connects()

        # Start DeviceSystem scanning (provides devices to UI)
        await self.device_system.start_scanning()
        self.logger.info("Device scanning started")

    async def stop_device_scanning(self) -> None:
        """Stop USB and XBee device scanning."""
        await self.instance_manager.stop()
        await self.device_system.stop_scanning()
        self.logger.info("Device scanning stopped")

    def set_connection_enabled(
        self,
        interface: InterfaceType,
        family: DeviceFamily,
        enabled: bool
    ) -> None:
        """Enable or disable a connection type.

        Args:
            interface: The interface type (USB, UART, Network, etc.)
            family: The device family (DRT, VOG, Audio, etc.)
            enabled: Whether to enable or disable the connection
        """
        self.device_system.set_connection_enabled(interface, family, enabled)

    # =========================================================================
    # Multi-Instance Module Support
    # =========================================================================

    # Modules that support multiple simultaneous instances (one per device)
    MULTI_INSTANCE_MODULES = {"DRT", "VOG", "CAMERAS", "CAMERASCSI"}

    def _is_multi_instance_module(self, module_id: str) -> bool:
        """Check if a module supports multiple simultaneous instances."""
        # Normalize to uppercase for comparison
        normalized = module_id.upper()
        return normalized in self.MULTI_INSTANCE_MODULES

    def _make_instance_id(self, module_id: str, device_id: str) -> str:
        """Generate an instance ID for a device-specific module instance.

        For multi-instance modules, returns "MODULE:ShortDeviceId" (e.g., "DRT:ACM0").
        For single-instance modules, returns just the module_id.

        The device_id is shortened by extracting just the device name from paths
        like "/dev/ttyACM0" -> "ACM0".
        """
        if self._is_multi_instance_module(module_id):
            # Extract short device ID from full path
            short_id = self._extract_short_device_id(device_id)
            return f"{module_id.upper()}:{short_id}"
        return module_id

    def _extract_short_device_id(self, device_id: str) -> str:
        """Extract short device ID from full path.

        Examples:
            /dev/ttyACM0 -> ACM0
            /dev/ttyUSB0 -> USB0
            ACM0 -> ACM0 (already short)
        """
        if not device_id:
            return ""
        # Handle full paths like /dev/ttyACM0
        if "/" in device_id:
            short = device_id.split("/")[-1]
            if short.startswith("tty"):
                return short[3:]  # Remove "tty" prefix
            return short
        return device_id

    def _parse_instance_id(self, instance_id: str) -> tuple[str, Optional[str]]:
        """Parse an instance ID into (module_id, device_id).

        Returns (module_id, device_id) for multi-instance IDs like "DRT:ACM0",
        or (module_id, None) for single-instance IDs like "Notes".
        """
        if ":" in instance_id:
            parts = instance_id.split(":", 1)
            return parts[0], parts[1]
        return instance_id, None

    def _get_instance_for_device(self, device_id: str) -> Optional[str]:
        """Get the instance ID for a device, if one is running."""
        return self._device_instance_map.get(device_id)

    def _register_device_instance(self, device_id: str, instance_id: str) -> None:
        """Register a device-to-instance mapping."""
        self._device_instance_map[device_id] = instance_id
        self.logger.debug("Registered device %s -> instance %s", device_id, instance_id)

    def _unregister_device_instance(self, device_id: str) -> Optional[str]:
        """Unregister a device-to-instance mapping. Returns the instance_id if found."""
        instance_id = self._device_instance_map.pop(device_id, None)
        if instance_id:
            self.logger.debug("Unregistered device %s from instance %s", device_id, instance_id)
        return instance_id

    def _find_device_for_instance(self, instance_id: str) -> Optional[str]:
        """Find the device_id associated with an instance_id."""
        for dev_id, inst_id in self._device_instance_map.items():
            if inst_id == instance_id:
                return dev_id
        # Fallback: extract from instance_id format "MODULE:device"
        _, extracted = self._parse_instance_id(instance_id)
        return extracted

    async def _cleanup_device_disconnect(
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

        self._unregister_device_instance(device_id)
        self._notify_device_connected(device_id, False)

        # Skip persistence for crash path (handled separately by on_module_crash)
        if is_crash:
            return

        if not self._has_other_instances(module_id):
            if is_internal:
                # Internal modules (Notes, etc.): keep visible, just mark as not running
                await self._state.on_internal_module_closed(module_id)
            else:
                # Hardware devices: disable the device type entirely
                await self._state.on_user_disconnect(module_id)

    def _build_assign_device_command_builder(self, device: DeviceInfo) -> Callable[[str], str]:
        """Build a command builder function for assign_device.

        Returns a function that takes a command_id and returns the full
        command JSON string. This is used by the robust connection system
        to inject correlation IDs for tracking.
        """
        session_dir_str = str(self.session_dir) if self.session_dir else None

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
                # Audio sibling info for webcams with built-in microphones
                camera_audio_index=device.get_meta("camera_audio_index"),
                camera_audio_channels=device.get_meta("camera_audio_channels"),
                camera_audio_sample_rate=device.get_meta("camera_audio_sample_rate"),
                camera_audio_alsa_card=device.get_meta("camera_audio_alsa_card"),
                display_name=device.display_name,
                command_id=command_id,  # Inject correlation ID
            )

        return builder

    async def connect_device(self, device_id: str) -> bool:
        """Connect a device (called from UI).

        This delegates to connect_and_start_device which handles the full
        connection lifecycle including module startup.
        """
        return await self.connect_and_start_device(device_id)

    async def disconnect_device(self, device_id: str) -> None:
        """Disconnect a device (called from UI).

        This delegates to stop_and_disconnect_device which handles the full
        disconnection lifecycle including module shutdown.
        """
        await self.stop_and_disconnect_device(device_id)

    async def _load_pending_auto_connects(self) -> None:
        """Load device connection states and mark modules for auto-connect.

        Only marks modules for auto-connect if they are enabled (checked in
        Modules menu). This ensures disabled modules don't auto-connect their
        devices on startup.
        """
        modules = self.module_manager.get_available_modules()

        for module_info in modules:
            # Only auto-connect if the module is enabled
            if not self.is_module_enabled(module_info.name):
                continue

            # Load persisted state
            state = await self._state.load_module_state(module_info.name)

            if state.device_connected:
                self.logger.info("Module %s marked for auto-connect", module_info.name)
                self.device_system.request_auto_connect(module_info.name)

    # =========================================================================
    # Device Connection & Visibility API
    # =========================================================================

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

        Returns:
            True if device connection was initiated successfully.
        """
        self.logger.info("connect_and_start_device: %s", device_id)

        # Check if this is a CSI camera
        is_csi_camera = device_id.startswith("picam:")
        camera_index: int | None = None
        if is_csi_camera:
            # Extract camera index from device_id (picam:0 → 0, picam:1 → 1)
            try:
                camera_index = int(device_id.split(":")[1])
            except (IndexError, ValueError):
                self.logger.error("Invalid CSI camera device_id format: %s", device_id)
                return False

        try:
            device = self.device_system.get_device(device_id)
            if not device:
                self.logger.warning("Device not found: %s", device_id)
                return False

            module_id = device.module_id
            if not module_id:
                self.logger.warning("Device has no module_id: %s", device_id)
                return False

            # Generate instance ID for this device
            instance_id = self._make_instance_id(module_id, device_id)
            self.logger.info("Instance ID for device %s: %s", device_id, instance_id)

            # Check if already connected or in progress
            if self.instance_manager.is_instance_connected(instance_id):
                self.logger.info("Instance %s already connected", instance_id)
                return True
            if self.instance_manager.is_instance_running(instance_id):
                self.logger.info("Instance %s already starting/running", instance_id)
                return True

            # Load geometry for this instance (try instance-specific first for multi-instance)
            window_geometry = await self._load_module_geometry(module_id, instance_id)

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
            self._register_device_instance(device_id, instance_id)

            # Set up XBee send callback for the instance
            self._setup_xbee_send_callback(instance_id)

            # Wait for module to become ready before sending connection command
            if not await self.instance_manager.wait_for_ready(instance_id, timeout=10.0):
                self.logger.error("Instance %s failed to become ready", instance_id)
                return False

            self.logger.info("Instance %s is ready, proceeding with device connection", instance_id)

            # Send assign_device command via InstanceStateManager (non-blocking)
            # CSI cameras are special: they init via --camera-index CLI arg, not assign_device
            if is_csi_camera:
                # CSI cameras init on startup via CLI arg. The module sends device_ready
                # when camera is initialized and frames are flowing.
                await self._wait_for_csi_connected(instance_id, timeout=30.0)
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

    async def _wait_for_csi_connected(self, instance_id: str, timeout: float = 30.0) -> bool:
        """Wait for a CSI camera instance to reach CONNECTED state.

        Args:
            instance_id: The instance to wait for
            timeout: Maximum time to wait in seconds (default 30s for camera init)

        Returns:
            True if instance reached CONNECTED state, False on timeout
        """
        from .instance_state import InstanceState

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
            "Timeout waiting for CSI camera %s to connect (%.1fs)",
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

        Returns:
            True if device is now disconnected.
        """
        self.logger.info("stop_and_disconnect_device: %s", device_id)

        device = self.device_system.get_device(device_id)
        if not device:
            self.logger.warning("Device not found: %s", device_id)
            self._unregister_device_instance(device_id)
            self._notify_device_connected(device_id, False)
            return True

        module_id = device.module_id
        if not module_id:
            self.logger.warning("Device has no module_id: %s", device_id)
            self._unregister_device_instance(device_id)
            self._notify_device_connected(device_id, False)
            return True

        # Get the instance ID for this device
        instance_id = self._get_instance_for_device(device_id)
        if not instance_id:
            # Fall back to generating instance ID
            instance_id = self._make_instance_id(module_id, device_id)

        # Stop instance via InstanceStateManager
        # This handles the STOPPING state and waiting for process exit
        await self.instance_manager.stop_instance(instance_id)

        # Unified cleanup: unregister, update UI, persist state
        await self._cleanup_device_disconnect(device_id, module_id)

        return True

    # =========================================================================
    # XBee Wireless Communication Routing
    # =========================================================================

    async def _route_xbee_to_module(self, node_id: str, data: str) -> None:
        """
        Route incoming XBee data to the appropriate module.

        Called when XBee data is received for a connected wireless device.
        Data is forwarded to the module subprocess via the command protocol,
        where XBeeProxyTransport buffers it for the device handler.
        """
        # Find which module owns this device
        device = self.device_system.get_device(node_id)
        if not device:
            self.logger.debug("XBee data for unknown device: %s", node_id)
            return

        # For multi-instance modules, use the device-to-instance mapping
        instance_id = self._get_instance_for_device(node_id)
        if not instance_id:
            # Fall back to module_id for single-instance modules
            instance_id = device.module_id

        if not instance_id:
            self.logger.debug("XBee device %s has no module_id or instance", node_id)
            return

        # Get the module process and forward the data
        module = self.module_manager.get_module(instance_id)
        if module and module.is_running():
            await module.send_xbee_data(node_id, data)
        else:
            self.logger.debug("Module %s not running for XBee device %s", instance_id, node_id)

    async def _send_xbee_from_module(self, node_id: str, data: bytes) -> bool:
        """
        Send data to XBee device on behalf of a module.

        Called when a module process sends an xbee_send status message.
        """
        return await self.device_system.send_to_wireless_device(node_id, data)

    def _setup_xbee_send_callback(self, module_id: str) -> None:
        """Set up XBee send callback for a module."""
        module = self.module_manager.get_module(module_id)
        if module:
            module.set_xbee_send_callback(self._send_xbee_from_module)
