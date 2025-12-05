
import asyncio
import datetime
from rpi_logger.core.logging_utils import get_module_logger
import subprocess
import sys
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import ttk, messagebox, filedialog
from typing import Optional, Dict, Union

from .theme import RoundedButton
from ..logger_system import LoggerSystem
from ..module_process import ModuleState
from ..config_manager import get_config_manager
from ..paths import CONFIG_PATH
from ..shutdown_coordinator import get_shutdown_coordinator
from .timer_manager import TimerManager


class MainController:

    def __init__(self, logger_system: LoggerSystem, timer_manager: TimerManager):
        self.logger = get_module_logger("MainController")
        self.logger_system = logger_system
        self.logger_system.ui_callback = self._status_callback
        self.timer_manager = timer_manager

        self.root: Optional[tk.Tk] = None
        self.module_vars: Dict[str, tk.BooleanVar] = {}

        self.session_button: Optional[RoundedButton] = None
        self.trial_button: Optional[RoundedButton] = None

        self.session_status_label: Optional[ttk.Label] = None
        self.trial_counter_label: Optional[ttk.Label] = None
        self.session_path_label: Optional[ttk.Label] = None

        self.trial_label_var: Optional[tk.StringVar] = None

        self.trial_counter: int = 0
        self.session_active = False
        self.trial_active = False

        self._pending_tasks: list[asyncio.Task] = []

    def set_widgets(
        self,
        root: tk.Tk,
        module_vars: Dict[str, tk.BooleanVar],
        session_button: RoundedButton,
        trial_button: RoundedButton,
        session_status_label: ttk.Label,
        trial_counter_label: ttk.Label,
        session_path_label: ttk.Label,
        trial_label_var: tk.StringVar
    ) -> None:
        self.root = root
        self.module_vars = module_vars
        self.session_button = session_button
        self.trial_button = trial_button
        self.session_status_label = session_status_label
        self.trial_counter_label = trial_counter_label
        self.session_path_label = session_path_label
        self.trial_label_var = trial_label_var

    def _schedule_task(self, coro) -> None:
        task = asyncio.create_task(coro)
        self._pending_tasks.append(task)
        task.add_done_callback(lambda t: self._pending_tasks.remove(t) if t in self._pending_tasks else None)

    async def on_module_menu_toggle(self, module_name: str) -> None:
        desired_state = self.module_vars[module_name].get()

        if self.logger_system.event_logger:
            action = "enable" if desired_state else "disable"
            await self.logger_system.event_logger.log_button_press(f"module_{module_name}", action)

        await self.logger_system.toggle_module_enabled(module_name, desired_state)

        self.logger.info("%s module: %s", "Starting" if desired_state else "Stopping", module_name)
        self._schedule_task(self._handle_module_toggle(module_name, desired_state))

    async def _handle_module_toggle(self, module_name: str, desired_state: bool) -> None:
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
                self.logger.info("Module %s %s successfully", module_name, "started" if desired_state else "stopped")
                if self.logger_system.event_logger:
                    if desired_state:
                        await self.logger_system.event_logger.log_module_started(module_name)
                    else:
                        await self.logger_system.event_logger.log_module_stopped(module_name)

        except Exception as e:
            self.logger.error("Error toggling module %s: %s", module_name, e, exc_info=True)
            self.module_vars[module_name].set(not desired_state)
            messagebox.showerror("Error", f"Failed to toggle {module_name}: {e}")

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
                self.logger.debug("Saved last session directory to config: %s", session_dir)

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
                    self.logger.warning("User chose to start session with no modules running")

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

            self.session_button.configure(text="Stop", style='danger')
            self.trial_button.configure(style='success')

            self.session_status_label.config(text="Active")
            self.session_path_label.config(text=f"{full_session_dir}")
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

            self.session_button.configure(text="Start", style='success')
            self.trial_button.configure(style='inactive')

            self.session_status_label.config(text="Idle")

            await self.timer_manager.stop_session_timer()

            self.logger.info("Session stopped")

            # Return modules to the idle directory to avoid writing after stop.
            self.logger_system.reset_session_dir()

        except Exception as e:
            self.logger.error("Error stopping session: %s", e, exc_info=True)
            messagebox.showerror("Error", f"Failed to stop session: {e}")

    async def _start_trial_async(self) -> None:
        try:
            trial_label = self.trial_label_var.get() if self.trial_label_var else ""
            next_trial_num = self.trial_counter + 1

            if self.logger_system.event_logger:
                await self.logger_system.event_logger.log_button_press("trial_record", f"trial={next_trial_num}")
                await self.logger_system.event_logger.log_trial_start(next_trial_num, trial_label)

            results = await self.logger_system.record_all(next_trial_num, trial_label)

            failed = [name for name, success in results.items() if not success]
            if failed:
                messagebox.showwarning(
                    "Recording Warning",
                    f"Failed to start recording on: {', '.join(failed)}"
                )

            self.trial_active = True

            self.trial_button.configure(text="Pause", style='danger')

            await self.timer_manager.start_trial_timer()

            self.logger.info("Trial started")

        except Exception as e:
            self.logger.error("Error starting trial: %s", e, exc_info=True)
            messagebox.showerror("Error", f"Failed to start trial: {e}")

    async def _stop_trial_async(self) -> None:
        try:
            results = await self.logger_system.pause_all()

            failed = [name for name, success in results.items() if not success]
            if failed:
                messagebox.showwarning(
                    "Pause Warning",
                    f"Failed to pause recording on: {', '.join(failed)}"
                )

            self.trial_active = False
            self.trial_counter += 1

            if self.logger_system.event_logger:
                await self.logger_system.event_logger.log_button_press("trial_pause", f"trial={self.trial_counter}")
                await self.logger_system.event_logger.log_trial_stop(self.trial_counter)

            self.trial_button.configure(text="Record", style='success')

            self.trial_counter_label.config(text=f"{self.trial_counter}")

            await self.timer_manager.stop_trial_timer()

            self.logger.info("Trial stopped (trial #%d)", self.trial_counter)

            self.logger.info(
                "Trial %d ready for post-processing (run python -m rpi_logger.tools.muxing_tool when convenient)",
                self.trial_counter,
            )

        except Exception as e:
            self.logger.error("Error stopping trial: %s", e, exc_info=True)
            messagebox.showerror("Error", f"Failed to stop trial: {e}")

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

        self._schedule_task(shutdown_coordinator.initiate_shutdown("UI button"))

    async def _status_callback(self, module_name: str, state: ModuleState, status) -> None:
        if module_name in self.module_vars:
            var = self.module_vars[module_name]

            if state == ModuleState.STARTING:
                pass
            elif state in (ModuleState.STOPPED, ModuleState.CRASHED, ModuleState.ERROR):
                if var.get():
                    self.logger.info("Unchecking %s (state: %s)", module_name, state.value)
                    var.set(False)
            elif state in (ModuleState.IDLE, ModuleState.RECORDING, ModuleState.INITIALIZING):
                if not var.get():
                    self.logger.info("Checking %s (state: %s)", module_name, state.value)
                    var.set(True)


    async def auto_start_modules(self) -> None:
        await asyncio.sleep(0.5)

        for module_name, enabled in self.logger_system.get_module_enabled_states().items():
            if enabled:
                self.logger.info("Auto-starting module: %s", module_name)
                success = await self.logger_system.set_module_enabled(module_name, True)
                if not success:
                    self.logger.error("Failed to auto-start module: %s", module_name)
                    self.module_vars[module_name].set(False)

    def show_about(self) -> None:
        try:
            from .help_dialogs import AboutDialog
            AboutDialog(self.root)
        except Exception as e:
            self.logger.error("Failed to show About dialog: %s", e)

    def show_system_info(self) -> None:
        try:
            from .help_dialogs import SystemInfoDialog
            SystemInfoDialog(self.root, self.logger_system)
        except Exception as e:
            self.logger.error("Failed to show System Info dialog: %s", e)

    def show_help(self) -> None:
        try:
            from .help_dialogs import QuickStartDialog
            QuickStartDialog(self.root)
        except Exception as e:
            self.logger.error("Failed to show Help dialog: %s", e)

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

            self.logger.info("Opened logs directory: %s", logs_dir)
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

            self.logger.info("Opened config file: %s", CONFIG_PATH)
        except Exception as e:
            self.logger.error("Failed to open config file: %s", e)

    def reset_settings(self) -> None:
        try:
            from .help_dialogs import ResetSettingsDialog
            ResetSettingsDialog(self.root, CONFIG_PATH)
        except Exception as e:
            self.logger.error("Failed to reset settings: %s", e)

    def report_issue(self) -> None:
        try:
            url = "https://github.com/JoelCooperPhD/RPi_Logger/issues"
            webbrowser.open(url)
            self.logger.info("Opened issue tracker: %s", url)
        except Exception as e:
            self.logger.error("Failed to open issue tracker: %s", e)

    # =========================================================================
    # Device Connection Handlers
    # =========================================================================

    async def on_usb_scan_toggle(self, enabled: bool) -> None:
        """Handle USB scanning toggle from Connections menu."""
        try:
            if enabled:
                self.logger.info("Enabling USB device scanning")
                await self.logger_system.start_device_scanning()
            else:
                self.logger.info("Disabling USB device scanning")
                await self.logger_system.stop_device_scanning()
        except Exception as e:
            self.logger.error("Error toggling USB scan: %s", e, exc_info=True)

    async def on_device_connect_toggle(self, device_id: str, connect: bool) -> None:
        """Handle device connect/disconnect from devices panel."""
        try:
            if connect:
                self.logger.info("Connecting device: %s", device_id)
                success = await self.logger_system.connect_device(device_id)
                if not success:
                    self.logger.error("Failed to connect device: %s", device_id)
            else:
                self.logger.info("Disconnecting device: %s", device_id)
                await self.logger_system.disconnect_device(device_id)
        except Exception as e:
            self.logger.error("Error toggling device connection: %s", e, exc_info=True)

    async def on_device_toggle_window(self, device_id: str, visible: bool) -> None:
        """Handle show/hide window button from devices panel."""
        try:
            action = "Showing" if visible else "Hiding"
            self.logger.info("%s window for device: %s", action, device_id)
            await self.logger_system.toggle_device_window(device_id, visible)
        except Exception as e:
            self.logger.error("Error toggling device window: %s", e, exc_info=True)
