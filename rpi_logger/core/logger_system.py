"""
Logger System - Main coordinator for the RPi Logger.

This is the facade that coordinates between ModuleManager, SessionManager,
WindowManager, and other components. It provides a unified API for the UI.
"""

import asyncio
import datetime
import json
from rpi_logger.core.logging_utils import get_module_logger
from pathlib import Path
from typing import Dict, List, Optional, Callable, TYPE_CHECKING

from .module_discovery import ModuleInfo
from .module_process import ModuleState
from .commands import StatusMessage, CommandMessage
from .window_manager import WindowManager, WindowGeometry
from rpi_logger.modules.base import gui_utils
from .config_manager import get_config_manager
from .paths import STATE_FILE
from .module_manager import ModuleManager
from .session_manager import SessionManager
from .devices import DeviceConnectionManager, DeviceInfo, XBeeDongleInfo

if TYPE_CHECKING:
    from .event_logger import EventLogger


class LoggerSystem:
    """
    Main coordinator for the logger system.

    This class acts as a facade, delegating to specialized managers:
    - ModuleManager: Module discovery and lifecycle
    - SessionManager: Session and recording control
    - WindowManager: Window layout and geometry
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

        # Managers
        self.module_manager = ModuleManager(
            session_dir=self._session_dir,
            session_prefix=session_prefix,
            log_level=log_level,
            status_callback=self._module_status_callback,
        )
        self.session_manager = SessionManager()
        self.window_manager = WindowManager()
        self.config_manager = get_config_manager()

        # Device connection manager
        self.device_manager = DeviceConnectionManager()
        self.device_manager.set_devices_changed_callback(self._on_devices_changed)
        self.device_manager.set_device_connected_callback(self._on_device_connected)
        self.device_manager.set_device_disconnected_callback(self._on_device_disconnected)

        # UI callback for device panel updates
        self.devices_ui_callback: Optional[Callable[[List[DeviceInfo], List[XBeeDongleInfo]], None]] = None

        # State
        self.shutdown_event = asyncio.Event()
        self.event_logger: Optional['EventLogger'] = None
        self._gracefully_quitting_modules: set[str] = set()
        self._shutdown_restart_candidates: List[str] = []

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

    async def async_init(self) -> None:
        """Complete async initialization. Must be called after construction."""
        await self._load_enabled_modules()

    async def _load_enabled_modules(self) -> None:
        """Load enabled modules asynchronously, avoiding blocking I/O."""
        running_modules_from_last_session = None

        if STATE_FILE.exists():
            try:
                def read_state():
                    with open(STATE_FILE, 'r') as f:
                        return json.load(f)

                state = await asyncio.to_thread(read_state)
                running_modules_from_last_session = set(state.get('running_modules', []))
                self.logger.info("Loaded running modules from last session: %s", running_modules_from_last_session)

                await asyncio.to_thread(STATE_FILE.unlink)
            except Exception as e:
                self.logger.error("Failed to load running modules state: %s", e)

        if running_modules_from_last_session:
            for module_name in running_modules_from_last_session:
                self.module_manager.module_enabled_state[module_name] = True
                self.logger.info("Module %s will be restored from last session", module_name)
        else:
            await self.module_manager.load_enabled_modules()

    async def _module_status_callback(self, process, status: Optional[StatusMessage]) -> None:
        """Handle status updates from module processes."""
        module_name = process.module_info.name

        if status:
            self.logger.info("Module %s status: %s", module_name, status.get_status_type())

            if status.get_status_type() == "recording_started":
                self.logger.info("Module %s started recording", module_name)
            elif status.get_status_type() == "recording_stopped":
                self.logger.info("Module %s stopped recording", module_name)
            elif status.get_status_type() == "quitting":
                self.logger.info("Module %s is quitting", module_name)
                self._gracefully_quitting_modules.add(module_name)
                self.module_manager.cleanup_stopped_process(module_name)
                if not self.module_manager.is_module_state_changing(module_name):
                    await self.module_manager.set_module_enabled(module_name, False)
                if self.ui_callback:
                    try:
                        await self.ui_callback(module_name, process.get_state(), status)
                    except Exception as e:
                        self.logger.error("UI callback error: %s", e)
                return
            elif status.is_error():
                self.logger.error("Module %s error: %s",
                                module_name,
                                status.get_error_message())

        if not process.is_running() and self.module_manager.is_module_enabled(module_name):
            if module_name not in self._gracefully_quitting_modules:
                self.logger.warning("Module %s crashed/stopped unexpectedly - unchecking", module_name)
                self.module_manager.cleanup_stopped_process(module_name)
                await self.module_manager.set_module_enabled(module_name, False)

        if not process.is_running() and module_name in self._gracefully_quitting_modules:
            self._gracefully_quitting_modules.discard(module_name)

        if self.ui_callback:
            try:
                await self.ui_callback(module_name, process.get_state(), status)
            except Exception as e:
                self.logger.error("UI callback error: %s", e)

    # ========== Module Management (delegate to ModuleManager) ==========

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
        return self.module_manager.is_module_enabled(module_name)

    def get_module_enabled_states(self) -> Dict[str, bool]:
        """Get all module enabled states."""
        return self.module_manager.get_module_enabled_states()

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

    # ========== Session Management (delegate to SessionManager) ==========

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

    # ========== Cleanup and State Management ==========

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
            self.logger.info("⏱️  Paused all modules in %.3fs", time.time() - pause_start)

        if request_geometry:
            self.logger.debug(
                "Skipping legacy geometry requests; module views persist their own layout."
            )

        stop_start = time.time()
        await self.module_manager.stop_all()
        self.logger.info("⏱️  Stopped all modules in %.3fs", time.time() - stop_start)

    async def save_running_modules_state(self) -> bool:
        """Persist snapshot of modules running at shutdown initiation."""
        all_running = self.module_manager.get_running_modules()
        running_modules = [
            module
            for module in all_running
            if module not in self.module_manager.forcefully_stopped_modules
        ]
        skipped = set(all_running) - set(running_modules)
        if skipped:
            self.logger.info(
                "Skipping force-stopped modules from restart snapshot: %s",
                sorted(skipped)
            )
        self._shutdown_restart_candidates = list(running_modules)
        return await self._write_running_modules_state(self._shutdown_restart_candidates)

    async def update_running_modules_state_after_cleanup(self) -> bool:
        """Rewrite restart state excluding modules that failed to stop cleanly."""
        if not self._shutdown_restart_candidates:
            # Ensure stale state is removed if nothing was running
            return await self._write_running_modules_state([])

        filtered = [
            module for module in self._shutdown_restart_candidates
            if module not in self.module_manager.forcefully_stopped_modules
        ]

        excluded = set(self._shutdown_restart_candidates) - set(filtered)
        if excluded:
            self.logger.info(
                "Excluding modules from auto-restart due to forceful stop: %s",
                sorted(excluded)
            )

        self._shutdown_restart_candidates = filtered
        return await self._write_running_modules_state(filtered)

    async def _write_running_modules_state(self, modules: List[str]) -> bool:
        import time
        save_start = time.time()

        try:
            if not modules:
                if STATE_FILE.exists():
                    await asyncio.to_thread(STATE_FILE.unlink)
                    self.logger.info("Cleared running modules state file")
                else:
                    self.logger.debug("No running modules; state file already absent")
                return True

            await asyncio.to_thread(STATE_FILE.parent.mkdir, parents=True, exist_ok=True)

            state = {
                'timestamp': datetime.datetime.now().isoformat(),
                'running_modules': modules,
            }

            def write_json():
                with open(STATE_FILE, 'w') as f:
                    json.dump(state, f, indent=2)

            await asyncio.to_thread(write_json)

            save_duration = time.time() - save_start
            self.logger.info("⏱️  Updated running modules state in %.3fs: %s",
                            save_duration, modules)
            return True

        except Exception as e:
            self.logger.error("Failed to write running modules state: %s", e, exc_info=True)
            return False

    async def cleanup(self, request_geometry: bool = True) -> None:
        """
        Cleanup all resources.

        Args:
            request_geometry: If True, request geometry from modules before stopping.
                             Default is True to ensure geometry is always saved (safe default).
                             Can be set to False for faster shutdown if modules save their own.
        """
        self.logger.info("Cleaning up logger system")
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

    # ========== Device Management ==========

    def set_devices_ui_callback(
        self,
        callback: Callable[[List[DeviceInfo], List[XBeeDongleInfo]], None]
    ) -> None:
        """Set callback for updating device panel UI."""
        self.devices_ui_callback = callback

    async def start_device_scanning(self) -> None:
        """Start USB and XBee device scanning."""
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

    async def show_device_window(self, device_id: str) -> None:
        """Show the window for a device's module.

        If the module is not running, it will be enabled first.
        """
        device = self.device_manager.get_device(device_id)
        if not device:
            self.logger.warning("Device not found: %s", device_id)
            return

        module_id = device.module_id
        if not module_id:
            self.logger.warning("Device has no module_id: %s", device_id)
            return

        # Ensure module is enabled/running
        if not self.module_manager.is_module_enabled(module_id):
            self.logger.info("Enabling module %s to show window for device %s", module_id, device_id)
            success = await self.module_manager.set_module_enabled(module_id, True)
            if not success:
                self.logger.error("Failed to enable module %s", module_id)
                return

        # Send show_window command to module
        command = CommandMessage.show_window()
        await self.module_manager.send_command(module_id, command)
