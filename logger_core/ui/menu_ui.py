
import asyncio
import datetime
import logging
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, messagebox
from pathlib import Path
from typing import Optional, Dict

from ..logger_system import LoggerSystem
from ..module_process import ModuleState
from ..config_manager import get_config_manager


class MenuUI:

    def __init__(self, logger_system: LoggerSystem):
        self.logger = logging.getLogger("MenuUI")
        self.logger_system = logger_system
        self.logger_system.ui_callback = self._status_callback

        self.root: Optional[tk.Tk] = None
        self.module_status_indicators: Dict[str, tk.Menu] = {}  # Menu reference for each module
        self.module_menu_indices: Dict[str, int] = {}  # Menu index for each module
        self.module_vars: Dict[str, tk.BooleanVar] = {}

        self.start_session_button: Optional[ttk.Button] = None
        self.stop_session_button: Optional[ttk.Button] = None
        self.start_trial_button: Optional[ttk.Button] = None
        self.stop_trial_button: Optional[ttk.Button] = None
        self.shutdown_button: Optional[ttk.Button] = None

        self.session_status_label: Optional[tk.Label] = None
        self.session_timer_label: Optional[tk.Label] = None
        self.trial_timer_label: Optional[tk.Label] = None
        self.trial_counter_label: Optional[tk.Label] = None
        self.session_path_label: Optional[tk.Label] = None

        self.session_start_time: Optional[datetime.datetime] = None
        self.trial_start_time: Optional[datetime.datetime] = None
        self.trial_counter: int = 0
        self.session_timer_task: Optional[asyncio.Task] = None
        self.trial_timer_task: Optional[asyncio.Task] = None

        self.running = False
        self.session_active = False
        self.trial_active = False

    def build_ui(self) -> None:
        self.root = tk.Tk()
        self.root.title("RPi Logger")

        config_path = Path(__file__).parent.parent.parent / "config.txt"
        config_manager = get_config_manager()

        if config_path.exists():
            config = config_manager.read_config(config_path)
            window_x = config_manager.get_int(config, 'window_x', default=0)
            window_y = config_manager.get_int(config, 'window_y', default=0)
            window_width = config_manager.get_int(config, 'window_width', default=800)
            window_height = config_manager.get_int(config, 'window_height', default=600)

            if window_x != 0 or window_y != 0:
                self.root.geometry(f"{window_width}x{window_height}+{window_x}+{window_y}")
                self.logger.info("Applied saved window geometry: %dx%d+%d+%d", window_width, window_height, window_x, window_y)
            else:
                self.root.geometry(f"{window_width}x{window_height}")
        else:
            self.root.geometry("800x600")

        self.root.minsize(700, 500)

        self.root.configure(bg='#F5F5F7')

        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)

        modules_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Modules", menu=modules_menu)

        for idx, module_info in enumerate(self.logger_system.get_available_modules()):
            is_enabled = self.logger_system.is_module_selected(module_info.name)
            var = tk.BooleanVar(value=is_enabled)
            self.module_vars[module_info.name] = var

            modules_menu.add_checkbutton(
                label=f"{module_info.display_name}  [Inactive]",
                variable=var,
                command=lambda name=module_info.name: self._on_module_menu_toggle(name)
            )

            self.module_status_indicators[module_info.name] = modules_menu
            self.module_menu_indices[module_info.name] = idx

        main_frame = ttk.Frame(self.root, padding="20")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(0, weight=1)  # Control panel expands

        style = ttk.Style()
        style.theme_use('clam')  # Use clam theme for better customization

        available_fonts = tkfont.families()
        button_font = ('Helvetica', 14, 'bold')
        if 'SF Pro Display' in available_fonts:
            button_font = ('SF Pro Display', 14, 'bold')
        elif 'Segoe UI' in available_fonts:
            button_font = ('Segoe UI', 14, 'bold')

        style.configure(
            'Active.TButton',
            background='#007AFF',
            foreground='white',
            borderwidth=1,
            bordercolor='#007AFF',
            relief='flat',
            padding=(20, 15),
            font=button_font
        )
        style.map('Active.TButton',
                  background=[('pressed', '#0051D5'), ('active', '#0062CC')],
                  foreground=[('pressed', 'white'), ('active', 'white')])

        style.configure(
            'Inactive.TButton',
            background='#E5E5EA',
            foreground='#8E8E93',
            borderwidth=1,
            bordercolor='#C7C7CC',
            relief='flat',
            padding=(20, 15),
            font=button_font
        )
        style.map('Inactive.TButton',
                  background=[('pressed', '#D1D1D6'), ('active', '#D1D1D6')],
                  foreground=[('pressed', '#8E8E93'), ('active', '#8E8E93')])

        control_frame = ttk.Frame(main_frame)
        control_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 15))
        control_frame.columnconfigure(0, weight=1)
        control_frame.columnconfigure(1, weight=1)
        control_frame.rowconfigure(0, weight=1)

        session_control_frame = ttk.LabelFrame(control_frame, text="Session", padding="25")
        session_control_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), padx=(0, 10))
        session_control_frame.columnconfigure(0, weight=1)

        self.start_session_button = ttk.Button(
            session_control_frame,
            text="Start Session",
            style='Active.TButton',
            command=self._on_start_session
        )
        self.start_session_button.pack(fill=tk.X, pady=(0, 10))

        self.stop_session_button = ttk.Button(
            session_control_frame,
            text="Stop Session",
            style='Inactive.TButton',
            command=self._on_stop_session
        )
        self.stop_session_button.pack(fill=tk.X, pady=(0, 20))

        self.session_status_label = ttk.Label(
            session_control_frame,
            text="Status: Idle",
            font=("Helvetica", 12)
        )
        self.session_status_label.pack(pady=(0, 5))

        self.session_timer_label = ttk.Label(
            session_control_frame,
            text="Session Time: --:--:--",
            font=("Helvetica", 11)
        )
        self.session_timer_label.pack()

        trial_control_frame = ttk.LabelFrame(control_frame, text="Trial", padding="25")
        trial_control_frame.grid(row=0, column=1, sticky=(tk.W, tk.E, tk.N, tk.S), padx=(10, 0))
        trial_control_frame.columnconfigure(0, weight=1)

        self.start_trial_button = ttk.Button(
            trial_control_frame,
            text="Start Trial",
            style='Inactive.TButton',
            command=self._on_start_trial
        )
        self.start_trial_button.pack(fill=tk.X, pady=(0, 10))

        self.stop_trial_button = ttk.Button(
            trial_control_frame,
            text="Stop Trial",
            style='Inactive.TButton',
            command=self._on_stop_trial
        )
        self.stop_trial_button.pack(fill=tk.X, pady=(0, 20))

        self.trial_counter_label = ttk.Label(
            trial_control_frame,
            text="Trials Completed: 0",
            font=("Helvetica", 12)
        )
        self.trial_counter_label.pack(pady=(0, 5))

        self.trial_timer_label = ttk.Label(
            trial_control_frame,
            text="Trial Time: --:--:--",
            font=("Helvetica", 11)
        )
        self.trial_timer_label.pack()

        info_frame = ttk.LabelFrame(main_frame, text="Session Information", padding="10")
        info_frame.grid(row=2, column=0, sticky=(tk.W, tk.E), pady=(0, 10))

        session_info = self.logger_system.get_session_info()
        self.session_path_label = ttk.Label(
            info_frame,
            text=f"Path: {session_info['session_dir']}",
            font=("Arial", 9)
        )
        self.session_path_label.pack(anchor=tk.W)

        shutdown_frame = ttk.Frame(main_frame)
        shutdown_frame.grid(row=3, column=0, sticky=(tk.W, tk.E), pady=(0, 0))
        shutdown_frame.columnconfigure(0, weight=1)

        style.configure(
            'Shutdown.TButton',
            background='#FF3B30',
            foreground='white',
            borderwidth=1,
            bordercolor='#FF3B30',
            relief='flat',
            padding=(20, 12),
            font=button_font
        )
        style.map('Shutdown.TButton',
                  background=[('pressed', '#CC0000'), ('active', '#E60000')],
                  foreground=[('pressed', 'white'), ('active', 'white')])

        self.shutdown_button = ttk.Button(
            shutdown_frame,
            text="Shutdown Logger",
            style='Shutdown.TButton',
            command=self._on_shutdown
        )
        self.shutdown_button.pack(fill=tk.X)

        self.root.protocol("WM_DELETE_WINDOW", self._on_quit)


    def _on_module_menu_toggle(self, module_name: str) -> None:
        current_state = self.module_vars[module_name].get()

        self.logger_system.toggle_module_enabled(module_name, current_state)

        if current_state:
            self.logger.info("Starting module: %s", module_name)
            asyncio.create_task(self._start_module_async(module_name))
        else:
            self.logger.info("Stopping module: %s", module_name)
            asyncio.create_task(self._stop_module_async(module_name))

    async def _start_module_async(self, module_name: str) -> None:
        try:
            self._update_menu_label(module_name, "Starting...")

            success = await self.logger_system.start_module(module_name)

            if not success:
                self.module_vars[module_name].set(False)
                self._update_menu_label(module_name, "Error")
                messagebox.showerror(
                    "Start Failed",
                    f"Failed to start module: {module_name}\nCheck logs for details."
                )
            else:
                self.logger.info("Module %s started successfully", module_name)

        except Exception as e:
            self.logger.error("Error starting module %s: %s", module_name, e, exc_info=True)
            self.module_vars[module_name].set(False)
            self._update_menu_label(module_name, "Error")
            messagebox.showerror("Error", f"Failed to start {module_name}: {e}")

    async def _stop_module_async(self, module_name: str) -> None:
        try:
            self._update_menu_label(module_name, "Stopping...")

            success = await self.logger_system.stop_module(module_name)

            if not success:
                self.logger.warning("Failed to stop module: %s", module_name)
            else:
                self.logger.info("Module %s stopped successfully", module_name)

            self._update_menu_label(module_name, "Inactive")

        except Exception as e:
            self.logger.error("Error stopping module %s: %s", module_name, e, exc_info=True)
            self._update_menu_label(module_name, "Error")
            messagebox.showerror("Error", f"Failed to stop {module_name}: {e}")

    def _update_menu_label(self, module_name: str, status: str) -> None:
        if module_name in self.module_status_indicators and module_name in self.module_menu_indices:
            menu = self.module_status_indicators[module_name]
            idx = self.module_menu_indices[module_name]

            module_info = next(
                (m for m in self.logger_system.get_available_modules() if m.name == module_name),
                None
            )
            if module_info:
                menu.entryconfig(idx, label=f"{module_info.display_name}  [{status}]")

    def _on_start_session(self) -> None:
        self.logger.info("Starting session...")
        asyncio.create_task(self._start_session_async())

    def _on_stop_session(self) -> None:
        self.logger.info("Stopping session...")
        asyncio.create_task(self._stop_session_async())

    async def _start_session_async(self) -> None:
        try:
            has_running = any(
                self.logger_system.is_module_running(name)
                for name in self.module_vars.keys()
            )

            if not has_running:
                messagebox.showwarning(
                    "No Modules",
                    "Please select at least one module before starting a session."
                )
                return

            self.session_active = True
            self.session_start_time = datetime.datetime.now()
            self.trial_counter = 0

            self.start_session_button.config(style='Inactive.TButton')
            self.stop_session_button.config(style='Active.TButton')

            self.session_status_label.config(text="Status: Active")

            self.start_trial_button.config(style='Active.TButton')

            if self.session_timer_task:
                self.session_timer_task.cancel()
            self.session_timer_task = asyncio.create_task(self._update_session_timer())

            self.logger.info("Session started")

        except Exception as e:
            self.logger.error("Error starting session: %s", e, exc_info=True)
            messagebox.showerror("Error", f"Failed to start session: {e}")
            self.session_active = False

    async def _stop_session_async(self) -> None:
        try:
            if self.trial_active:
                await self._stop_trial_async()

            self.session_active = False
            self.session_start_time = None

            self.start_session_button.config(style='Active.TButton')
            self.stop_session_button.config(style='Inactive.TButton')

            self.session_status_label.config(text="Status: Idle")
            self.session_timer_label.config(text="Session Time: --:--:--")

            self.start_trial_button.config(style='Inactive.TButton')
            self.stop_trial_button.config(style='Inactive.TButton')

            if self.session_timer_task:
                self.session_timer_task.cancel()
                self.session_timer_task = None

            self.logger.info("Session stopped")

        except Exception as e:
            self.logger.error("Error stopping session: %s", e, exc_info=True)
            messagebox.showerror("Error", f"Failed to stop session: {e}")

    def _on_start_trial(self) -> None:
        if not self.session_active:
            messagebox.showwarning("No Active Session", "Please start a session first.")
            return
        self.logger.info("Starting trial...")
        asyncio.create_task(self._start_trial_async())

    def _on_stop_trial(self) -> None:
        self.logger.info("Stopping trial...")
        asyncio.create_task(self._stop_trial_async())

    async def _start_trial_async(self) -> None:
        try:
            results = await self.logger_system.start_recording_all()

            failed = [name for name, success in results.items() if not success]
            if failed:
                messagebox.showwarning(
                    "Recording Warning",
                    f"Failed to start recording on: {', '.join(failed)}"
                )

            self.trial_active = True
            self.trial_start_time = datetime.datetime.now()

            self.start_trial_button.config(style='Inactive.TButton')
            self.stop_trial_button.config(style='Active.TButton')

            if self.trial_timer_task:
                self.trial_timer_task.cancel()
            self.trial_timer_task = asyncio.create_task(self._update_trial_timer())

            self.logger.info("Trial started")

        except Exception as e:
            self.logger.error("Error starting trial: %s", e, exc_info=True)
            messagebox.showerror("Error", f"Failed to start trial: {e}")

    async def _stop_trial_async(self) -> None:
        try:
            results = await self.logger_system.stop_recording_all()

            failed = [name for name, success in results.items() if not success]
            if failed:
                messagebox.showwarning(
                    "Stop Warning",
                    f"Failed to stop recording on: {', '.join(failed)}"
                )

            self.trial_active = False
            self.trial_start_time = None
            self.trial_counter += 1

            self.start_trial_button.config(style='Active.TButton')
            self.stop_trial_button.config(style='Inactive.TButton')

            self.trial_counter_label.config(text=f"Trials Completed: {self.trial_counter}")
            self.trial_timer_label.config(text="Trial Time: --:--:--")

            if self.trial_timer_task:
                self.trial_timer_task.cancel()
                self.trial_timer_task = None

            self.logger.info("Trial stopped (trial #%d)", self.trial_counter)

        except Exception as e:
            self.logger.error("Error stopping trial: %s", e, exc_info=True)
            messagebox.showerror("Error", f"Failed to stop trial: {e}")

    def _on_shutdown(self) -> None:
        if self.session_active:
            response = messagebox.askyesno(
                "Confirm Shutdown",
                "Session is active. Shutdown anyway?"
            )
            if not response:
                return

        self.logger.info("Shutting down logger (preserving module state)...")

        self.shutdown_button.config(state='disabled')
        self.shutdown_button.config(text="Shutting Down...")

        self.running = False

        asyncio.create_task(self._quit_async(save_running_modules=True))

    def _on_quit(self) -> None:
        if self.session_active:
            if not messagebox.askyesno("Confirm", "Session is active. Quit anyway?"):
                return

        self.logger.info("Quitting (preserving module state)...")

        self.running = False

        asyncio.create_task(self._quit_async(save_running_modules=True))

    async def _quit_async(self, save_running_modules: bool = False) -> None:
        try:
            # Save window geometry before quitting
            if self.root:
                try:
                    from Modules.base import gui_utils

                    geometry_str = self.root.geometry()
                    parsed = gui_utils.parse_geometry_string(geometry_str)

                    if parsed:
                        width, height, x, y = parsed

                        config_path = Path(__file__).parent.parent.parent / "config.txt"
                        config_manager = get_config_manager()
                        updates = {
                            'window_x': x,
                            'window_y': y,
                            'window_width': width,
                            'window_height': height,
                        }
                        if config_manager.write_config(config_path, updates):
                            self.logger.info("Saved main logger window geometry: %dx%d+%d+%d", width, height, x, y)
                        else:
                            self.logger.warning("Failed to save window geometry")
                    else:
                        self.logger.warning("Failed to parse window geometry: %s", geometry_str)
                except Exception as e:
                    self.logger.error("Error saving window geometry: %s", e)

            if save_running_modules:
                await self.logger_system.save_running_modules_state()

            await self.logger_system.cleanup()
        finally:
            self.running = False
            if self.root:
                self.root.quit()

    async def _update_session_timer(self) -> None:
        try:
            while self.session_start_time and self.running:
                elapsed = datetime.datetime.now() - self.session_start_time
                hours = int(elapsed.total_seconds() // 3600)
                minutes = int((elapsed.total_seconds() % 3600) // 60)
                seconds = int(elapsed.total_seconds() % 60)

                self.session_timer_label.config(text=f"Session Time: {hours:02d}:{minutes:02d}:{seconds:02d}")

                await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            pass

    async def _update_trial_timer(self) -> None:
        try:
            while self.trial_start_time and self.running:
                elapsed = datetime.datetime.now() - self.trial_start_time
                hours = int(elapsed.total_seconds() // 3600)
                minutes = int((elapsed.total_seconds() % 3600) // 60)
                seconds = int(elapsed.total_seconds() % 60)

                self.trial_timer_label.config(text=f"Trial Time: {hours:02d}:{minutes:02d}:{seconds:02d}")

                await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            pass

    async def _status_callback(self, module_name: str, state: ModuleState, status) -> None:
        status_text = "Unknown"

        if state == ModuleState.STOPPED:
            status_text = "Inactive"
        elif state == ModuleState.STARTING:
            status_text = "Starting..."
        elif state == ModuleState.INITIALIZING:
            status_text = "Initializing..."
        elif state == ModuleState.IDLE:
            status_text = "Ready"
        elif state == ModuleState.RECORDING:
            status_text = "RECORDING"
        elif state == ModuleState.STOPPING:
            status_text = "Stopping..."
        elif state == ModuleState.ERROR:
            status_text = "Error"
        elif state == ModuleState.CRASHED:
            status_text = "Crashed"

        self._update_menu_label(module_name, status_text)

        if module_name in self.module_vars:
            var = self.module_vars[module_name]

            if status_text == "Starting...":
                pass
            elif state in (ModuleState.STOPPED, ModuleState.CRASHED, ModuleState.ERROR):
                if var.get():
                    self.logger.info("Unchecking %s (state: %s)", module_name, state.value)
                    var.set(False)
            elif state in (ModuleState.IDLE, ModuleState.RECORDING, ModuleState.INITIALIZING):
                if not var.get():
                    self.logger.info("Checking %s (state: %s)", module_name, state.value)
                    var.set(True)

    async def run(self) -> None:
        self.running = True
        self.build_ui()

        await self._auto_start_modules()

        while self.running:
            try:
                self.root.update()
                await asyncio.sleep(0.01)  # 10ms update rate
            except tk.TclError:
                break
            except Exception as e:
                self.logger.error("UI loop error: %s", e)
                break

        self.logger.info("UI stopped")

    async def _auto_start_modules(self) -> None:
        await asyncio.sleep(0.5)

        for module_name in self.logger_system.get_selected_modules():
            self.logger.info("Auto-starting module: %s", module_name)
            await self._start_module_async(module_name)
