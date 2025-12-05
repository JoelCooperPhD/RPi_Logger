"""
Logger System - Main coordinator for the RPi Logger.

This is the facade that coordinates between ModuleManager, SessionManager,
WindowManager, and other components. It provides a unified API for the UI.

The LoggerSystem now integrates with ModuleStateManager for centralized
state management and uses observers for state synchronization.
"""

import asyncio
import datetime
import json
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
from .observers import (
    ConfigPersistenceObserver,
    SessionRecoveryObserver,
    UIStateObserver,
)
from .commands import StatusMessage, CommandMessage
from .window_manager import WindowManager, WindowGeometry
from rpi_logger.modules.base import gui_utils
from .config_manager import get_config_manager
from .paths import STATE_FILE
from .module_manager import ModuleManager
from .session_manager import SessionManager
from .devices import DeviceConnectionManager, DeviceInfo, XBeeDongleInfo, ConnectionState

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

    State synchronization is handled through observers:
    - ConfigPersistenceObserver: Persists enabled state to config files
    - SessionRecoveryObserver: Manages running_modules.json
    - UIStateObserver: Updates UI elements
    """

    def __init__(
        self,
        session_dir: Path,
        session_prefix: str = "session",
        log_level: str = "info",
        ui_callback: Optional[Callable] = None,
    ):
        self.logger = get_module_logger("LoggerSystem")
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

        # Create observers
        self._config_observer = ConfigPersistenceObserver.from_module_infos(
            self.module_manager.get_available_modules()
        )
        self._session_recovery_observer = SessionRecoveryObserver(STATE_FILE)
        self._ui_observer = UIStateObserver()

        # Register observers with state manager
        self.state_manager.add_observer(
            self._config_observer,
            events={StateEvent.DESIRED_STATE_CHANGED}
        )
        self.state_manager.add_observer(
            self._session_recovery_observer,
            events={
                StateEvent.ACTUAL_STATE_CHANGED,
                StateEvent.STARTUP_COMPLETE,
            }
        )
        self.state_manager.add_observer(
            self._ui_observer,
            events={
                StateEvent.DESIRED_STATE_CHANGED,
                StateEvent.ACTUAL_STATE_CHANGED,
            }
        )

        # Device connection manager
        self.device_manager = DeviceConnectionManager()
        self.device_manager.set_devices_changed_callback(self._on_devices_changed)
        self.device_manager.set_device_connected_callback(self._on_device_connected)
        self.device_manager.set_device_disconnected_callback(self._on_device_disconnected)
        self.device_manager.set_save_connection_state_callback(self._save_device_connection_state)
        self.device_manager.set_load_connection_state_callback(self._load_device_connection_state)

        # UI callback for device panel updates
        self.devices_ui_callback: Optional[Callable[[List[DeviceInfo], List[XBeeDongleInfo]], None]] = None

        # UI callbacks for device state changes
        self.device_connected_callback: Optional[Callable[[str, bool], None]] = None
        self.device_visible_callback: Optional[Callable[[str, bool], None]] = None

        # State
        self.shutdown_event = asyncio.Event()
        self.event_logger: Optional['EventLogger'] = None
        self._gracefully_quitting_modules: set[str] = set()
        self._startup_modules: Set[str] = set()

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

        # Start health check
        await self.module_manager.start_health_check()

    async def _load_enabled_modules(self) -> None:
        """
        Load enabled modules asynchronously.

        Priority:
        1. If running_modules.json exists (crash recovery), use that
        2. Otherwise, load from individual module config.txt files
        """
        # Try to load from session recovery file first
        running_modules = await self._session_recovery_observer.load_state_file()

        if running_modules:
            # Session recovery - restore previously running modules
            self.logger.info(
                "Restoring modules from last session: %s",
                running_modules
            )
            self._startup_modules = running_modules.copy()

            # Set desired state for recovered modules
            for module_name in running_modules:
                await self.state_manager.set_desired_state(
                    module_name, True, reconcile=False
                )
                self.state_manager.mark_startup_module(module_name)
                self.logger.info(
                    "Module %s will be restored from last session",
                    module_name
                )

            # Note: We don't delete the state file here - it's deleted
            # after startup completes successfully
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
        await self._session_recovery_observer.write_state_file(running)

    # =========================================================================
    # Module Status Callback
    # =========================================================================

    async def _module_status_callback(self, process, status: Optional[StatusMessage]) -> None:
        """Handle status updates from module processes."""
        module_name = process.module_info.name

        if status:
            self.logger.info("Module %s status: %s", module_name, status.get_status_type())

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
                self.logger.info("Module %s is quitting", module_name)
                self._gracefully_quitting_modules.add(module_name)
                self.module_manager.cleanup_stopped_process(module_name)
                if not self.module_manager.is_module_state_changing(module_name):
                    await self.state_manager.set_desired_state(module_name, False)
                if self.ui_callback:
                    try:
                        await self.ui_callback(module_name, process.get_state(), status)
                    except Exception as e:
                        self.logger.error("UI callback error: %s", e)
                return
            elif status.get_status_type() in ("window_hidden", "window_shown"):
                visible = status.get_status_type() == "window_shown"
                self._notify_device_visible_for_module(module_name, visible)
            elif status.is_error():
                self.logger.error("Module %s error: %s",
                                module_name,
                                status.get_error_message())

        if not process.is_running() and self.state_manager.is_module_enabled(module_name):
            if module_name not in self._gracefully_quitting_modules:
                self.logger.warning("Module %s crashed/stopped unexpectedly - unchecking", module_name)
                self.module_manager.cleanup_stopped_process(module_name)
                await self.state_manager.set_actual_state(module_name, ActualState.CRASHED)
                await self.state_manager.set_desired_state(module_name, False, reconcile=False)

        if not process.is_running() and module_name in self._gracefully_quitting_modules:
            self._gracefully_quitting_modules.discard(module_name)

        if self.ui_callback:
            try:
                await self.ui_callback(module_name, process.get_state(), status)
            except Exception as e:
                self.logger.error("UI callback error: %s", e)

    def _notify_device_connected(self, device_id: str, connected: bool) -> None:
        """Notify UI about device connection state change."""
        if not self.device_connected_callback:
            return

        self.logger.debug("Device %s connected=%s", device_id, connected)
        try:
            self.device_connected_callback(device_id, connected)
        except Exception as e:
            self.logger.error("Device connected callback error: %s", e)

    def _notify_device_visible(self, device_id: str, visible: bool) -> None:
        """Notify UI about device window visibility change."""
        if not self.device_visible_callback:
            return

        self.logger.debug("Device %s visible=%s", device_id, visible)
        try:
            self.device_visible_callback(device_id, visible)
        except Exception as e:
            self.logger.error("Device visible callback error: %s", e)

    def _notify_device_connected_for_module(self, module_name: str, connected: bool) -> None:
        """Notify UI about connection state change for all devices of a module."""
        if not self.device_connected_callback:
            return

        devices = self.device_manager.get_devices_for_module(module_name)
        self.logger.debug(
            "Module %s connected=%s, updating %d devices",
            module_name, connected, len(devices)
        )
        for device in devices:
            try:
                self.device_connected_callback(device.device_id, connected)
            except Exception as e:
                self.logger.error("Device connected callback error: %s", e)

    def _notify_device_visible_for_module(self, module_name: str, visible: bool) -> None:
        """Notify UI about visibility change for all devices of a module."""
        if not self.device_visible_callback:
            return

        devices = self.device_manager.get_devices_for_module(module_name)
        for device in devices:
            try:
                self.device_visible_callback(device.device_id, visible)
            except Exception as e:
                self.logger.error("Device visible callback error: %s", e)

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
        return await self.module_manager.start_module(module_name)

    async def set_module_enabled(self, module_name: str, enabled: bool) -> bool:
        """Set module enabled state (central state machine entry point)."""
        if enabled:
            window_geometry = await self._load_module_geometry(module_name)
            self.module_manager.set_window_geometry(module_name, window_geometry)
        return await self.module_manager.set_module_enabled(module_name, enabled)

    def is_module_enabled(self, module_name: str) -> bool:
        """Check if module is enabled (checkbox state)."""
        return self.state_manager.is_module_enabled(module_name)

    def get_module_enabled_states(self) -> Dict[str, bool]:
        """Get all module enabled states."""
        return self.state_manager.get_desired_states()

    def _normalize_geometry(self, geometry: WindowGeometry) -> WindowGeometry:
        width, height, x, y = gui_utils.normalize_geometry_values(
            geometry.width,
            geometry.height,
            geometry.x,
            geometry.y,
            screen_height=self.window_manager.screen_height,
        )
        return WindowGeometry(x=x, y=y, width=width, height=height)

    async def _load_module_geometry(self, module_name: str) -> Optional[WindowGeometry]:
        """Load saved window geometry for a module."""
        modules = self.module_manager.get_available_modules()
        module_info = next((m for m in modules if m.name == module_name), None)

        if not module_info or not module_info.config_path:
            self.logger.debug("No config path for module %s", module_name)
            return None

        config = await self.config_manager.read_config_async(module_info.config_path)

        # First try to load from "window_geometry" string
        geometry_str = self.config_manager.get_str(config, 'window_geometry', default=None)
        if geometry_str:
            try:
                geometry = WindowGeometry.from_geometry_string(geometry_str)
                if geometry:
                    normalized = self._normalize_geometry(geometry)
                    self.logger.debug("Loaded geometry string for %s: %s", module_name, geometry_str)
                    return normalized
            except Exception:
                self.logger.warning("Failed to parse window_geometry for %s: %s", module_name, geometry_str)

        # Fallback to decomposed fields
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

    async def stop_all(self, request_geometry: bool = True) -> None:
        """
        Stop all modules.

        Args:
            request_geometry: If True, request geometry from modules before stopping.
                             Set to False during final shutdown to speed up exit.
        """
        import time
        self.logger.info("Stopping all modules (request_geometry=%s)", request_geometry)

        if self.session_manager.recording:
            pause_start = time.time()
            await self.pause_all()
            self.logger.info("Paused all modules in %.3fs", time.time() - pause_start)

        if request_geometry:
            self.logger.debug(
                "Skipping legacy geometry requests; module views persist their own layout."
            )

        stop_start = time.time()
        await self.module_manager.stop_all()
        self.logger.info("Stopped all modules in %.3fs", time.time() - stop_start)

    async def save_running_modules_state(self) -> bool:
        """Persist snapshot of modules running at shutdown initiation."""
        running_modules = set(self.module_manager.get_running_modules())

        # Filter out forcefully stopped modules
        filtered = running_modules - self.module_manager.forcefully_stopped_modules
        skipped = running_modules - filtered

        if skipped:
            self.logger.info(
                "Skipping force-stopped modules from restart snapshot: %s",
                sorted(skipped)
            )

        return await self._session_recovery_observer.save_shutdown_state(filtered)

    async def update_running_modules_state_after_cleanup(self) -> bool:
        """Rewrite restart state excluding modules that failed to stop cleanly."""
        # Get modules that should have been running
        running_modules = set(self.module_manager.get_running_modules())

        # Update forcefully stopped tracking
        for module_name in self.module_manager.forcefully_stopped_modules:
            self._session_recovery_observer.mark_forcefully_stopped(module_name)

        return await self._session_recovery_observer.finalize_shutdown_state(running_modules)

    async def cleanup(self, request_geometry: bool = True) -> None:
        """
        Cleanup all resources.

        Args:
            request_geometry: If True, request geometry from modules before stopping.
                             Default is True to ensure geometry is always saved (safe default).
                             Can be set to False for faster shutdown if modules save their own.
        """
        self.logger.info("Cleaning up logger system")

        # Stop health check
        await self.module_manager.stop_health_check()

        # Stop all modules
        await self.stop_all(request_geometry=request_geometry)

        self.shutdown_event.set()

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

    def set_devices_ui_callback(
        self,
        callback: Callable[[List[DeviceInfo], List[XBeeDongleInfo]], None]
    ) -> None:
        """Set callback for updating device panel UI."""
        self.devices_ui_callback = callback

    def set_device_connected_callback(
        self,
        callback: Callable[[str, bool], None]
    ) -> None:
        """Set callback for device connection state changes.

        The callback receives (device_id, connected) when connection state changes.
        """
        self.device_connected_callback = callback

    def set_device_visible_callback(
        self,
        callback: Callable[[str, bool], None]
    ) -> None:
        """Set callback for device window visibility changes.

        The callback receives (device_id, visible) when window visibility changes.
        """
        self.device_visible_callback = callback

    async def start_device_scanning(self) -> None:
        """Start USB and XBee device scanning."""
        # Load device connection states and mark modules for auto-connect
        await self._load_pending_auto_connects()
        await self.device_manager.start_scanning()
        self.logger.info("Device scanning started")

    async def stop_device_scanning(self) -> None:
        """Stop USB and XBee device scanning."""
        await self.device_manager.stop_scanning()
        self.logger.info("Device scanning stopped")

    def _on_devices_changed(self) -> None:
        """Callback when device list changes - update UI."""
        if self.devices_ui_callback:
            devices = self.device_manager.get_all_devices()
            dongles = self.device_manager.get_xbee_dongles()
            self.devices_ui_callback(devices, dongles)

    async def _on_device_connected(self, device: DeviceInfo) -> None:
        """
        Callback when a device is connected.

        This auto-starts the appropriate module and assigns the device to it.
        The module window will be visible after this.
        """
        module_id = device.module_id
        if not module_id:
            self.logger.warning("Device %s has no module_id", device.device_id)
            return

        self.logger.info(
            "Device connected: %s -> module %s",
            device.device_id, module_id
        )

        # Auto-start module if not running
        if not self.is_module_running(module_id):
            self.logger.info("Auto-starting module %s for device %s", module_id, device.device_id)
            success = await self.set_module_enabled(module_id, True)
            if not success:
                self.logger.error("Failed to start module %s", module_id)
                return

        # Send assign_device command to module
        session_dir_str = str(self.session_dir) if self.session_dir else None
        command = CommandMessage.assign_device(
            device_id=device.device_id,
            device_type=device.device_type.value,
            port=device.port or "",
            baudrate=device.baudrate,
            session_dir=session_dir_str,
            is_wireless=device.is_wireless,
        )
        success = await self.module_manager.send_command(module_id, command)
        if not success:
            self.logger.error("Failed to send assign_device to module %s", module_id)
            return

        # Module started with window visible - update UI
        self._notify_device_connected(device.device_id, True)
        self._notify_device_visible(device.device_id, True)

    async def _on_device_disconnected(self, device_id: str) -> None:
        """Callback when a device is disconnected."""
        self.logger.info("Device disconnected: %s", device_id)

        # Find which module had this device
        # For now, we'll iterate through running modules and send unassign
        for module_name in self.module_manager.get_running_modules():
            command = CommandMessage.unassign_device(device_id)
            await self.module_manager.send_command(module_name, command)

    async def connect_device(self, device_id: str) -> bool:
        """Connect a device (called from UI)."""
        return await self.device_manager.connect_device(device_id)

    async def disconnect_device(self, device_id: str) -> None:
        """Disconnect a device (called from UI)."""
        await self.device_manager.disconnect_device(device_id)

    # =========================================================================
    # Device Connection State Persistence
    # =========================================================================

    async def _save_device_connection_state(self, module_id: str, connected: bool) -> None:
        """Save device connection state to module config."""
        modules = self.module_manager.get_available_modules()
        module_info = next((m for m in modules if m.name == module_id), None)

        if not module_info or not module_info.config_path:
            self.logger.warning("Cannot save connection state - no config for %s", module_id)
            return

        success = await self.config_manager.write_config_async(
            module_info.config_path,
            {'device_connected': connected}
        )

        if success:
            self.logger.info("Saved device_connected=%s for module %s", connected, module_id)
        else:
            self.logger.error("Failed to save device_connected for module %s", module_id)

    async def _load_device_connection_state(self, module_id: str) -> bool:
        """Load device connection state from module config."""
        modules = self.module_manager.get_available_modules()
        module_info = next((m for m in modules if m.name == module_id), None)

        if not module_info or not module_info.config_path:
            return False

        config = await self.config_manager.read_config_async(module_info.config_path)
        return self.config_manager.get_bool(config, 'device_connected', default=False)

    async def _load_pending_auto_connects(self) -> None:
        """Load device connection states and mark modules for auto-connect."""
        modules = self.module_manager.get_available_modules()

        for module_info in modules:
            if not module_info.config_path:
                continue

            config = await self.config_manager.read_config_async(module_info.config_path)
            was_connected = self.config_manager.get_bool(config, 'device_connected', default=False)

            if was_connected:
                self.logger.info("Module %s had device connected - marking for auto-connect", module_info.name)
                self.device_manager.set_pending_auto_connect(module_info.name)

    # =========================================================================
    # Device Connection & Visibility API
    # =========================================================================

    async def connect_and_start_device(self, device_id: str) -> bool:
        """Connect a device and start its module.

        Called when user clicks the green dot or Connect button.
        Window is shown automatically when module starts.

        Returns:
            True if device is now connected with module running.
        """
        self.logger.info("connect_and_start_device: %s", device_id)

        device = self.device_manager.get_device(device_id)
        if not device:
            self.logger.warning("Device not found: %s", device_id)
            return False

        module_id = device.module_id
        if not module_id:
            self.logger.warning("Device has no module_id: %s", device_id)
            return False

        # Step 1: Connect device if not connected
        if device.state != ConnectionState.CONNECTED:
            self.logger.info("Connecting device %s", device_id)
            connected = await self.connect_device(device_id)
            if not connected:
                self.logger.error("Failed to connect device %s", device_id)
                return False
            # connect_device triggers _on_device_connected which starts module
            self._notify_device_connected(device_id, True)
            self._notify_device_visible(device_id, True)
            return True

        # Step 2: Start module if not running (device already connected)
        if not self.is_module_running(module_id):
            self.logger.info("Starting module %s for device %s", module_id, device_id)
            success = await self.set_module_enabled(module_id, True)
            if not success:
                self.logger.error("Failed to start module %s", module_id)
                return False
            self._notify_device_connected(device_id, True)
            self._notify_device_visible(device_id, True)
            return True

        # Already connected and running
        self._notify_device_connected(device_id, True)
        return True

    async def stop_and_disconnect_device(self, device_id: str) -> bool:
        """Stop module and disconnect device.

        Called when user clicks the green dot (when on) or Disconnect button.

        Returns:
            True if device is now disconnected.
        """
        self.logger.info("stop_and_disconnect_device: %s", device_id)

        device = self.device_manager.get_device(device_id)
        if not device:
            self.logger.warning("Device not found: %s", device_id)
            self._notify_device_connected(device_id, False)
            self._notify_device_visible(device_id, False)
            return True

        module_id = device.module_id
        if not module_id:
            self.logger.warning("Device has no module_id: %s", device_id)
            self._notify_device_connected(device_id, False)
            return True

        # Step 1: Stop module if running
        if self.is_module_running(module_id):
            self.logger.info("Stopping module %s", module_id)
            await self.set_module_enabled(module_id, False)

        # Step 2: Disconnect device
        # (The device manager handles actual disconnection)

        # Notify UI
        self._notify_device_connected(device_id, False)
        self._notify_device_visible(device_id, False)
        return True

    async def show_device_window(self, device_id: str) -> bool:
        """Show the device's module window.

        If the device is not connected, connects first.

        Returns:
            True if window is now visible.
        """
        self.logger.info("show_device_window: %s", device_id)

        device = self.device_manager.get_device(device_id)
        if not device:
            self.logger.warning("Device not found: %s", device_id)
            return False

        module_id = device.module_id
        if not module_id:
            self.logger.warning("Device has no module_id: %s", device_id)
            return False

        # If not connected, connect first (which starts module and shows window)
        if device.state != ConnectionState.CONNECTED:
            success = await self.connect_and_start_device(device_id)
            return success

        # If module not running, start it (which shows window)
        if not self.is_module_running(module_id):
            self.logger.info("Starting module %s for device %s", module_id, device_id)
            success = await self.set_module_enabled(module_id, True)
            if success:
                self._notify_device_visible(device_id, True)
            return success

        # Module running - just show window
        self.logger.info("Sending show_window to module %s", module_id)
        command = CommandMessage.show_window()
        success = await self.module_manager.send_command(module_id, command)
        if success:
            self._notify_device_visible(device_id, True)
        return success

    async def hide_device_window(self, device_id: str) -> bool:
        """Hide the device's module window.

        Does NOT stop the module - it keeps running in the background.

        Returns:
            True if window is now hidden.
        """
        self.logger.info("hide_device_window: %s", device_id)

        device = self.device_manager.get_device(device_id)
        if not device:
            self.logger.warning("Device not found: %s", device_id)
            self._notify_device_visible(device_id, False)
            return True

        module_id = device.module_id
        if not module_id:
            self.logger.warning("Device has no module_id: %s", device_id)
            self._notify_device_visible(device_id, False)
            return True

        # Hide window if module is running
        if self.is_module_running(module_id):
            self.logger.info("Sending hide_window to module %s", module_id)
            command = CommandMessage.hide_window()
            await self.module_manager.send_command(module_id, command)

        # Notify UI
        self._notify_device_visible(device_id, False)
        return True
