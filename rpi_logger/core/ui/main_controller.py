
import asyncio
import datetime
from rpi_logger.core.logging_utils import get_module_logger
import subprocess
import sys
import tkinter as tk
import webbrowser
from concurrent.futures import Future
from pathlib import Path
from tkinter import ttk, messagebox, filedialog
from typing import Optional, Callable, TYPE_CHECKING

from .theme.widgets import RoundedButton
from ..logger_system import LoggerSystem
from ..module_process import ModuleState
from ..config_manager import get_config_manager
from ..paths import CONFIG_PATH, MASTER_LOG_FILE
from ..shutdown_coordinator import get_shutdown_coordinator
from ..devices import InterfaceType, DeviceFamily, DeviceCatalog
from .timer_manager import TimerManager

if TYPE_CHECKING:
    from ..async_bridge import AsyncBridge


def _normalize_module_key(name: str) -> str:
    """Normalize module name for consistent lookup.

    Handles both module_id format (cameras) and name format (Cameras)
    by uppercasing and removing underscores.
    """
    return name.upper().replace("_", "")


def _get_device_based_modules() -> dict[str, tuple[InterfaceType, DeviceFamily]]:
    """Get the module-to-connection mapping from the device catalog.

    All modules are device-based - they show devices in the panel
    instead of auto-launching when their checkbox is toggled.

    Keys are normalized (uppercase, no underscores) for consistent matching
    between module_id format and name format.
    """
    raw_map = DeviceCatalog.get_module_connection_map()
    # Normalize keys for consistent matching
    return {_normalize_module_key(k): v for k, v in raw_map.items()}


def _lookup_device_module(module_name: str) -> tuple[InterfaceType, DeviceFamily] | None:
    """Look up a module in DEVICE_BASED_MODULES (case-insensitive, underscore-insensitive)."""
    return DEVICE_BASED_MODULES.get(_normalize_module_key(module_name))


# Cached module connection map (derived from device registry)
# Keys are normalized (uppercase, no underscores) for consistent lookup
DEVICE_BASED_MODULES = _get_device_based_modules()


class MainController:

    def __init__(self, logger_system: LoggerSystem, timer_manager: TimerManager):
        self.logger = get_module_logger("MainController")
        self.logger_system = logger_system
        self.logger_system.ui_callback = self._status_callback
        self.timer_manager = timer_manager

        self.root: Optional[tk.Tk] = None

        self.session_button: Optional[RoundedButton] = None
        self.trial_button: Optional[RoundedButton] = None

        self.trial_counter_label: Optional[ttk.Label] = None

        self.trial_label_var: Optional[tk.StringVar] = None

        self.trial_counter: int = 0
        self.session_active = False
        self.trial_active = False

        self._pending_tasks: list[Future] = []

        # AsyncBridge for scheduling async work from UI thread
        self._bridge: Optional["AsyncBridge"] = None

        # Recording bar callbacks
        self._on_trial_start: Optional[Callable[[], None]] = None
        self._on_trial_stop: Optional[Callable[[], None]] = None

    def set_bridge(self, bridge: "AsyncBridge") -> None:
        self._bridge = bridge

    def set_recording_bar_callbacks(
        self,
        on_trial_start: Callable[[], None],
        on_trial_stop: Callable[[], None]
    ) -> None:
        self._on_trial_start = on_trial_start
        self._on_trial_stop = on_trial_stop

    def set_widgets(
        self,
        root: tk.Tk,
        module_vars: dict[str, tk.BooleanVar],
        session_button: RoundedButton,
        trial_button: RoundedButton,
        trial_counter_label: ttk.Label,
        trial_label_var: tk.StringVar
    ) -> None:
        self.root = root
        self.module_vars = module_vars
        self.session_button = session_button
        self.trial_button = trial_button
        self.trial_counter_label = trial_counter_label
        self.trial_label_var = trial_label_var

    def _schedule_task(self, coro) -> None:
        if self._bridge:
            future = self._bridge.run_coroutine(coro)
            self._pending_tasks.append(future)
            future.add_done_callback(lambda f: self._pending_tasks.remove(f) if f in self._pending_tasks else None)
        else:
            self.logger.warning("Cannot schedule task - bridge not initialized")

    def on_toggle_session(self) -> None:
        if self.session_active:
            self.logger.info("Stopping session...")
            self._schedule_task(self._stop_session_async())
        else:
            config_manager = get_config_manager()
            config = config_manager.read_config(CONFIG_PATH)
            last_dir = config_manager.get_str(config, 'last_session_dir', default='')

            if last_dir and Path(last_dir).exists():
                initial_dir = last_dir
            else:
                initial_dir = str(Path.home())

            session_dir = filedialog.askdirectory(
                title="Select Session Directory",
                initialdir=initial_dir
            )

            if session_dir:
                self.logger.info("Starting session in: %s", session_dir)

                config_manager.write_config(CONFIG_PATH, {'last_session_dir': session_dir})

                running_modules = self.logger_system.get_running_modules()
                if not running_modules:
                    response = messagebox.askyesno(
                        "No Modules Running",
                        "No modules are currently running. Start session anyway?\n\n"
                        "You can start modules later, but no data will be recorded until they are running."
                    )
                    if not response:
                        self.logger.info("Session start cancelled - no modules running")
                        return
                    self.logger.info("User chose to start session with no modules running")

                self._schedule_task(self._start_session_async(Path(session_dir)))
            else:
                self.logger.info("Session start cancelled - no directory selected")

    def on_toggle_trial(self) -> None:
        if not self.session_active:
            messagebox.showwarning("No Active Session", "Please start a session first.")
            return

        if self.trial_active:
            self.logger.info("Stopping trial...")
            self._schedule_task(self._stop_trial_async())
        else:
            self.logger.info("Starting trial...")
            self._schedule_task(self._start_trial_async())

    async def _start_session_async(self, session_dir: Path) -> None:
        try:
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            session_name = f"{self.logger_system.session_prefix}_{timestamp}"
            full_session_dir = session_dir / session_name
            full_session_dir.mkdir(parents=True, exist_ok=True)

            self.logger_system.set_session_dir(full_session_dir)

            from rpi_logger.core.event_logger import EventLogger
            self.logger_system.event_logger = EventLogger(full_session_dir, timestamp)
            await self.logger_system.event_logger.initialize()

            await self.logger_system.event_logger.log_button_press("session_start")
            await self.logger_system.event_logger.log_session_start(str(full_session_dir))

            self.session_active = True
            self.trial_counter = 0

            # Notify device controller that session is active (disables rescan)
            if self.logger_system.device_system.ui_controller:
                self.logger_system.device_system.ui_controller.set_session_active(True)

            self.session_button.configure(text="Stop", style='danger')
            self.trial_button.configure(style='success')
            self.trial_counter_label.config(text="0")

            await self.timer_manager.start_session_timer()

            self.logger.info("Session started in: %s", full_session_dir)

            await self.logger_system.start_session_all()

        except Exception as e:
            self.logger.error("Error starting session: %s", e, exc_info=True)
            messagebox.showerror("Error", f"Failed to start session: {e}")
            self.session_active = False

    async def _stop_session_async(self) -> None:
        try:
            if self.trial_active:
                await self._stop_trial_async()

            if self.logger_system.event_logger:
                await self.logger_system.event_logger.log_button_press("session_stop")
                await self.logger_system.event_logger.log_session_stop()

            await self.logger_system.stop_session_all()

            self.session_active = False

            # Notify device controller that session ended (re-enables rescan)
            if self.logger_system.device_system.ui_controller:
                self.logger_system.device_system.ui_controller.set_session_active(False)

            self.session_button.configure(text="Start", style='success')
            self.trial_button.configure(style='inactive')

            await self.timer_manager.stop_session_timer()

            self.logger.info("Session stopped")

            # Return modules to the idle directory to avoid writing after stop.
            self.logger_system.reset_session_dir()

        except Exception as e:
            self.logger.error("Error stopping session: %s", e, exc_info=True)
            messagebox.showerror("Error", f"Failed to stop session: {e}")

    async def _start_trial_async(self) -> None:
        try:
            # Update button immediately for responsive UI
            self.trial_button.configure(text="Pause", style='danger')

            # Increment counter on Record click (shows trial in progress)
            self.trial_counter += 1
            self.trial_counter_label.config(text=f"{self.trial_counter}")

            trial_label = self.trial_label_var.get() if self.trial_label_var else ""

            if self.logger_system.event_logger:
                await self.logger_system.event_logger.log_button_press("trial_record", f"trial={self.trial_counter}")
                await self.logger_system.event_logger.log_trial_start(self.trial_counter, trial_label)

            results = await self.logger_system.record_all(self.trial_counter, trial_label)

            failed = [name for name, success in results.items() if not success]
            if failed:
                messagebox.showwarning(
                    "Recording Warning",
                    f"Failed to start recording on: {', '.join(failed)}"
                )

            self.trial_active = True

            # Show recording bar
            if self._on_trial_start:
                self._on_trial_start()

            await self.timer_manager.start_trial_timer()

            self.logger.info("Trial started")

        except Exception as e:
            self.logger.error("Error starting trial: %s", e, exc_info=True)
            messagebox.showerror("Error", f"Failed to start trial: {e}")
            # Revert button state on failure
            self.trial_button.configure(text="Record", style='success')

    async def _stop_trial_async(self) -> None:
        try:
            # Update button immediately for responsive UI
            self.trial_button.configure(text="Record", style='success')

            results = await self.logger_system.pause_all()

            failed = [name for name, success in results.items() if not success]
            if failed:
                messagebox.showwarning(
                    "Pause Warning",
                    f"Failed to pause recording on: {', '.join(failed)}"
                )

            self.trial_active = False

            # Hide recording bar
            if self._on_trial_stop:
                self._on_trial_stop()

            if self.logger_system.event_logger:
                await self.logger_system.event_logger.log_button_press("trial_pause", f"trial={self.trial_counter}")
                await self.logger_system.event_logger.log_trial_stop(self.trial_counter)

            await self.timer_manager.stop_trial_timer()

            self.logger.info("Trial stopped (trial #%d)", self.trial_counter)

            self.logger.info(
                "Trial %d ready for post-processing (run python -m rpi_logger.tools.muxing_tool when convenient)",
                self.trial_counter,
            )

        except Exception as e:
            self.logger.error("Error stopping trial: %s", e, exc_info=True)
            messagebox.showerror("Error", f"Failed to stop trial: {e}")
            # Revert button state on failure
            self.trial_button.configure(text="Pause", style='danger')

    def on_shutdown(self) -> None:
        """Handle shutdown button click."""
        if self.logger_system.event_logger:
            self._schedule_task(self.logger_system.event_logger.log_button_press("shutdown"))

        if self.session_active:
            response = messagebox.askyesno(
                "Confirm Shutdown",
                "Session is active. Shutdown anyway?"
            )
            if not response:
                return

        self.logger.info("Shutdown requested from UI")

        shutdown_coordinator = get_shutdown_coordinator()

        async def shutdown_and_quit():
            # Stop timer tasks before shutdown cleanup
            await self.timer_manager.stop_all()

            await shutdown_coordinator.initiate_shutdown("UI button")

            # After cleanup completes, quit the mainloop from the GUI thread
            try:
                if self._bridge and self.root:
                    self._bridge.call_in_gui(self.root.quit)
            except Exception as e:
                self.logger.debug("Could not quit mainloop via bridge: %s", e)
                # Fallback: try direct quit if bridge failed
                if self.root:
                    try:
                        self.root.quit()
                    except Exception:
                        pass

        self._schedule_task(shutdown_and_quit())

    async def _status_callback(self, module_name: str, state: ModuleState, status) -> None:
        """Handle module state changes - log only, no UI checkboxes to update."""
        pass  # State changes logged by ModuleStateManager

    async def on_module_menu_toggle(self, module_name: str) -> None:
        """Handle module menu checkbox toggle."""
        desired_state = self.module_vars[module_name].get()

        if self.logger_system.event_logger:
            action = "enable" if desired_state else "disable"
            await self.logger_system.event_logger.log_button_press(f"module_{module_name}", action)

        # Check if this is a device-based module (DRT, VOG, Audio, Cameras)
        # These modules show devices in the panel instead of auto-launching
        device_module_info = _lookup_device_module(module_name)
        if device_module_info:
            interface, family = device_module_info
            self.logger.debug(
                "%s device section: %s (%s > %s)",
                "Showing" if desired_state else "Hiding",
                module_name, interface.value, family.value
            )
            # Toggle the connection type which controls section visibility
            self._schedule_task(self._handle_device_module_toggle(module_name, interface, family, desired_state))
            return

        await self.logger_system.toggle_module_enabled(module_name, desired_state)

        self.logger.debug("%s module: %s", "Starting" if desired_state else "Stopping", module_name)
        self._schedule_task(self._handle_module_toggle(module_name, desired_state))

    async def _handle_module_toggle(self, module_name: str, desired_state: bool) -> None:
        """Handle the actual module start/stop after toggle."""
        try:
            success = await self.logger_system.set_module_enabled(module_name, desired_state)

            if not success:
                self.module_vars[module_name].set(not desired_state)
                action = "start" if desired_state else "stop"
                messagebox.showerror(
                    f"{action.capitalize()} Failed",
                    f"Failed to {action} module: {module_name}\nCheck logs for details."
                )
            else:
                self.logger.debug("Module %s %s successfully", module_name, "started" if desired_state else "stopped")
                if self.logger_system.event_logger:
                    if desired_state:
                        await self.logger_system.event_logger.log_module_started(module_name)
                    else:
                        await self.logger_system.event_logger.log_module_stopped(module_name)
        except Exception as e:
            self.logger.error("Error toggling module %s: %s", module_name, e, exc_info=True)
            self.module_vars[module_name].set(not desired_state)

    async def _handle_device_module_toggle(
        self,
        module_name: str,
        interface: InterfaceType,
        family: DeviceFamily,
        enabled: bool
    ) -> None:
        """Handle toggle for device-based modules.

        When enabling:
        1. Enable the connection type (shows device section in panel)
        2. Save the enabled state to config
        3. Wait for user to connect to a specific device

        When disabling:
        1. Stop the module if it's running
        2. Disable the connection type (hides device section)
        3. Save the disabled state to config
        """
        try:
            if not enabled:
                # Stop all running instances of this module
                if self.logger_system.has_running_instances(module_name):
                    self.logger.debug("Stopping all instances of %s before disabling", module_name)
                    await self.logger_system.stop_all_instances_for_module(module_name)

            # Enable/disable the connection type (updates both device_system and device_manager)
            self.logger_system.set_connection_enabled(interface, family, enabled)

            # Save enabled state to module config
            await self.logger_system.toggle_module_enabled(module_name, enabled)

            # Notify devices changed to refresh UI
            self.logger_system.notify_devices_changed()

            self.logger.debug(
                "Device module %s %s (section %s)",
                module_name, "enabled" if enabled else "disabled", family.value
            )

        except Exception as e:
            self.logger.error("Error toggling device module %s: %s", module_name, e, exc_info=True)
            self.module_vars[module_name].set(not enabled)

    async def auto_start_modules(self) -> None:
        await asyncio.sleep(0.5)

        for module_name, enabled in self.logger_system.get_module_enabled_states().items():
            if enabled:
                device_module_info = _lookup_device_module(module_name)
                if device_module_info:
                    interface, family = device_module_info
                    self.logger.debug("Auto-enabling device section: %s", module_name)
                    self.logger_system.set_connection_enabled(interface, family, True)
                else:
                    self.logger.debug("Auto-starting module: %s", module_name)
                    success = await self.logger_system.set_module_enabled(module_name, True)
                    if not success:
                        self.logger.warning("Failed to auto-start module: %s", module_name)

        # Refresh UI after enabling device sections
        self.logger_system.notify_devices_changed()

        # Signal that startup is complete
        await self.logger_system.on_startup_complete()

    def show_about(self) -> None:
        try:
            from .dialogs.about import AboutDialog
            AboutDialog(self.root)
        except Exception as e:
            self.logger.error("Failed to show About dialog: %s", e)

    def show_system_info(self) -> None:
        try:
            from .dialogs.system_info import SystemInfoDialog
            SystemInfoDialog(self.root, self.logger_system)
        except Exception as e:
            self.logger.error("Failed to show System Info dialog: %s", e)

    def show_help(self) -> None:
        try:
            from .dialogs.quick_start import QuickStartDialog
            QuickStartDialog(self.root)
        except Exception as e:
            self.logger.error("Failed to show Help dialog: %s", e)

    def open_last_session_location(self) -> None:
        """Open the last session directory in the file manager.

        This is the same folder that is used as the initial directory
        when starting a new session.
        """
        try:
            config_manager = get_config_manager()
            config = config_manager.read_config(CONFIG_PATH)
            last_dir = config_manager.get_str(config, 'last_session_dir', default='')

            if not last_dir:
                messagebox.showinfo(
                    "No Session Location",
                    "No previous session location found.\n\n"
                    "Start a session first to set the location."
                )
                return

            target_dir = Path(last_dir)
            if not target_dir.exists():
                messagebox.showwarning(
                    "Location Not Found",
                    f"The last session location no longer exists:\n\n{last_dir}"
                )
                return

            if sys.platform == 'linux':
                subprocess.Popen(['xdg-open', str(target_dir)])
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', str(target_dir)])
            elif sys.platform == 'win32':
                subprocess.Popen(['explorer', str(target_dir)])

            self.logger.debug("Opened last session location: %s", target_dir)
        except Exception as e:
            self.logger.error("Failed to open last session location: %s", e)

    def open_log_file(self) -> None:
        """Open the master log file in the default application."""
        try:
            if not MASTER_LOG_FILE.exists():
                messagebox.showinfo(
                    "Log File Not Found",
                    f"The log file does not exist yet:\n\n{MASTER_LOG_FILE}"
                )
                return

            if sys.platform == 'linux':
                subprocess.Popen(['xdg-open', str(MASTER_LOG_FILE)])
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', str(MASTER_LOG_FILE)])
            elif sys.platform == 'win32':
                subprocess.Popen(['notepad.exe', str(MASTER_LOG_FILE)])

            self.logger.debug("Opened log file: %s", MASTER_LOG_FILE)
        except Exception as e:
            self.logger.error("Failed to open log file: %s", e)

    def open_logs_directory(self) -> None:
        try:
            session_info = self.logger_system.get_session_info()
            session_dir = Path(session_info['session_dir'])
            logs_dir = session_dir / "logs"

            if not logs_dir.exists():
                logs_dir = session_dir

            if sys.platform == 'linux':
                subprocess.Popen(['xdg-open', str(logs_dir)])
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', str(logs_dir)])
            elif sys.platform == 'win32':
                subprocess.Popen(['explorer', str(logs_dir)])

            self.logger.debug("Opened logs directory: %s", logs_dir)
        except Exception as e:
            self.logger.error("Failed to open logs directory: %s", e)

    def open_config_file(self) -> None:
        try:
            if not CONFIG_PATH.exists():
                self.logger.warning("Config file not found: %s", CONFIG_PATH)
                return

            if sys.platform == 'linux':
                subprocess.Popen(['xdg-open', str(CONFIG_PATH)])
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', str(CONFIG_PATH)])
            elif sys.platform == 'win32':
                subprocess.Popen(['notepad.exe', str(CONFIG_PATH)])

            self.logger.debug("Opened config file: %s", CONFIG_PATH)
        except Exception as e:
            self.logger.error("Failed to open config file: %s", e)

    def reset_settings(self) -> None:
        try:
            from .dialogs.reset_settings import ResetSettingsDialog
            ResetSettingsDialog(self.root, CONFIG_PATH)
        except Exception as e:
            self.logger.error("Failed to reset settings: %s", e)

    def report_issue(self) -> None:
        try:
            url = "https://github.com/JoelCooperPhD/Logger/issues"
            webbrowser.open(url)
            self.logger.debug("Opened issue tracker: %s", url)
        except Exception as e:
            self.logger.error("Failed to open issue tracker: %s", e)

    def export_logs(self) -> None:
        """Open the Export Logs dialog."""
        try:
            from .dialogs.export_logs import ExportLogsDialog
            ExportLogsDialog(self.root)
        except Exception as e:
            self.logger.error("Failed to show Export Logs dialog: %s", e)

    # =========================================================================
    # Device Connection Handlers
    # =========================================================================

    async def on_usb_scan_toggle(self, enabled: bool) -> None:
        """Handle USB scanning toggle triggered by module enable/disable."""
        try:
            if enabled:
                self.logger.debug("Enabling USB device scanning")
                await self.logger_system.start_device_scanning()
            else:
                self.logger.debug("Disabling USB device scanning")
                await self.logger_system.stop_device_scanning()
        except Exception as e:
            self.logger.error("Error toggling USB scan: %s", e, exc_info=True)

    async def on_device_connect_change(self, device_id: str, connect: bool) -> None:
        """Handle device connection change request from UI (dot or Connect button).

        connect=True: Connect device, start module, and show window
        connect=False: Hide window, stop module, and disconnect device
        """
        try:
            if connect:
                self.logger.debug("Connecting device: %s", device_id)
                success = await self.logger_system.connect_and_start_device(device_id)
                if not success:
                    self.logger.warning("Failed to connect device: %s", device_id)
            else:
                self.logger.debug("Disconnecting device: %s", device_id)
                await self.logger_system.stop_and_disconnect_device(device_id)
        except Exception as e:
            self.logger.error("Error changing device connection: %s", e, exc_info=True)
