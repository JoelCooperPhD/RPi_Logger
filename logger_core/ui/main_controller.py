
import asyncio
import datetime
import logging
import subprocess
import sys
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import ttk, messagebox, filedialog
from typing import Optional, Dict

from ..logger_system import LoggerSystem
from ..module_process import ModuleState
from ..config_manager import get_config_manager
from ..paths import CONFIG_PATH
from ..shutdown_coordinator import get_shutdown_coordinator
from .timer_manager import TimerManager


class MainController:

    def __init__(self, logger_system: LoggerSystem, timer_manager: TimerManager):
        self.logger = logging.getLogger("MainController")
        self.logger_system = logger_system
        self.logger_system.ui_callback = self._status_callback
        self.timer_manager = timer_manager

        self.root: Optional[tk.Tk] = None
        self.module_vars: Dict[str, tk.BooleanVar] = {}

        self.session_button: Optional[ttk.Button] = None
        self.trial_button: Optional[ttk.Button] = None
        self.shutdown_button: Optional[ttk.Button] = None

        self.session_status_label: Optional[ttk.Label] = None
        self.trial_counter_label: Optional[ttk.Label] = None
        self.session_path_label: Optional[ttk.Label] = None

        self.trial_label_var: Optional[tk.StringVar] = None

        self.trial_counter: int = 0
        self.session_active = False
        self.trial_active = False

    def set_widgets(
        self,
        root: tk.Tk,
        module_vars: Dict[str, tk.BooleanVar],
        session_button: ttk.Button,
        trial_button: ttk.Button,
        shutdown_button: ttk.Button,
        session_status_label: ttk.Label,
        trial_counter_label: ttk.Label,
        session_path_label: ttk.Label,
        trial_label_var: tk.StringVar
    ) -> None:
        self.root = root
        self.module_vars = module_vars
        self.session_button = session_button
        self.trial_button = trial_button
        self.shutdown_button = shutdown_button
        self.session_status_label = session_status_label
        self.trial_counter_label = trial_counter_label
        self.session_path_label = session_path_label
        self.trial_label_var = trial_label_var

    def on_module_menu_toggle(self, module_name: str) -> None:
        current_state = self.module_vars[module_name].get()

        if self.logger_system.event_logger:
            action = "enable" if current_state else "disable"
            asyncio.create_task(self.logger_system.event_logger.log_button_press(f"module_{module_name}", action))

        self.logger_system.toggle_module_enabled(module_name, current_state)

        if current_state:
            self.logger.info("Starting module: %s", module_name)
            asyncio.create_task(self._start_module_async(module_name))
        else:
            self.logger.info("Stopping module: %s", module_name)
            asyncio.create_task(self._stop_module_async(module_name))

    async def _start_module_async(self, module_name: str) -> None:
        try:
            success = await self.logger_system.start_module(module_name)

            if not success:
                self.module_vars[module_name].set(False)
                messagebox.showerror(
                    "Start Failed",
                    f"Failed to start module: {module_name}\nCheck logs for details."
                )
            else:
                self.logger.info("Module %s started successfully", module_name)
                if self.logger_system.event_logger:
                    await self.logger_system.event_logger.log_module_started(module_name)

        except Exception as e:
            self.logger.error("Error starting module %s: %s", module_name, e, exc_info=True)
            self.module_vars[module_name].set(False)
            messagebox.showerror("Error", f"Failed to start {module_name}: {e}")

    async def _stop_module_async(self, module_name: str) -> None:
        try:
            success = await self.logger_system.stop_module(module_name)

            if not success:
                self.logger.warning("Failed to stop module: %s", module_name)
            else:
                self.logger.info("Module %s stopped successfully", module_name)
                if self.logger_system.event_logger:
                    await self.logger_system.event_logger.log_module_stopped(module_name)

        except Exception as e:
            self.logger.error("Error stopping module %s: %s", module_name, e, exc_info=True)
            messagebox.showerror("Error", f"Failed to stop {module_name}: {e}")

    def on_toggle_session(self) -> None:
        if self.session_active:
            self.logger.info("Stopping session...")
            asyncio.create_task(self._stop_session_async())
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

                asyncio.create_task(self._start_session_async(Path(session_dir)))
            else:
                self.logger.info("Session start cancelled - no directory selected")

    def on_toggle_trial(self) -> None:
        if not self.session_active:
            messagebox.showwarning("No Active Session", "Please start a session first.")
            return

        if self.trial_active:
            self.logger.info("Stopping trial...")
            asyncio.create_task(self._stop_trial_async())
        else:
            self.logger.info("Starting trial...")
            asyncio.create_task(self._start_trial_async())

    async def _start_session_async(self, session_dir: Path) -> None:
        try:
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            session_name = f"{self.logger_system.session_prefix}_{timestamp}"
            full_session_dir = session_dir / session_name
            full_session_dir.mkdir(parents=True, exist_ok=True)

            self.logger_system.session_dir = full_session_dir

            from logger_core.event_logger import EventLogger
            self.logger_system.event_logger = EventLogger(full_session_dir, timestamp)
            await self.logger_system.event_logger.initialize()

            await self.logger_system.event_logger.log_button_press("session_start")
            await self.logger_system.event_logger.log_session_start(str(full_session_dir))

            self.session_active = True
            self.trial_counter = 0

            self.session_button.config(text="Stop", style='Active.TButton')
            self.trial_button.config(style='Active.TButton')

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

            self.session_button.config(text="Start", style='Active.TButton')
            self.trial_button.config(style='Inactive.TButton')

            self.session_status_label.config(text="Idle")

            await self.timer_manager.stop_session_timer()

            self.logger.info("Session stopped")

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

            self.trial_button.config(text="Pause", style='Active.TButton')

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

            self.trial_button.config(text="Record", style='Active.TButton')

            self.trial_counter_label.config(text=f"{self.trial_counter}")

            await self.timer_manager.stop_trial_timer()

            self.logger.info("Trial stopped (trial #%d)", self.trial_counter)

            self._spawn_independent_mux_process(self.trial_counter)

        except Exception as e:
            self.logger.error("Error stopping trial: %s", e, exc_info=True)
            messagebox.showerror("Error", f"Failed to stop trial: {e}")

    def on_shutdown(self) -> None:
        """Handle shutdown button click."""
        if self.logger_system.event_logger:
            asyncio.create_task(self.logger_system.event_logger.log_button_press("shutdown"))

        if self.session_active:
            response = messagebox.askyesno(
                "Confirm Shutdown",
                "Session is active. Shutdown anyway?"
            )
            if not response:
                return

        self.logger.info("Shutdown requested from UI")

        self.shutdown_button.config(state='disabled', text="Shutting Down...")

        shutdown_coordinator = get_shutdown_coordinator()

        asyncio.create_task(shutdown_coordinator.initiate_shutdown("UI button"))

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

        for module_name in self.logger_system.get_selected_modules():
            self.logger.info("Auto-starting module: %s", module_name)
            await self._start_module_async(module_name)

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

    def _spawn_independent_mux_process(self, trial_number: int) -> None:
        import subprocess
        import sys
        from pathlib import Path as PathType

        try:
            session_dir = self.logger_system.session_dir
            project_root = PathType(__file__).parent.parent.parent
            sync_and_mux_script = project_root / "utils" / "sync_and_mux.py"

            if not sync_and_mux_script.exists():
                self.logger.error("Auto-mux script not found: %s", sync_and_mux_script)
                return

            cmd = [
                sys.executable,
                str(sync_and_mux_script),
                str(session_dir),
                "--trial", str(trial_number)
            ]

            subprocess.Popen(
                cmd,
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                cwd=str(project_root)
            )

            self.logger.info("Auto-mux process started for trial %d", trial_number)

        except Exception as e:
            self.logger.error("Failed to spawn auto-mux process: %s", e, exc_info=True)
