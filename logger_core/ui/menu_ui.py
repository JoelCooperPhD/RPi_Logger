
import asyncio
import datetime
import logging
import subprocess
import sys
import tkinter as tk
import tkinter.font as tkfont
import webbrowser
from tkinter import ttk, messagebox, filedialog
from pathlib import Path
from typing import Optional, Dict
from PIL import Image, ImageTk

from ..logger_system import LoggerSystem
from ..module_process import ModuleState
from ..config_manager import get_config_manager


class MenuUI:

    def __init__(self, logger_system: LoggerSystem):
        self.logger = logging.getLogger("MenuUI")
        self.logger_system = logger_system
        self.logger_system.ui_callback = self._status_callback

        self.root: Optional[tk.Tk] = None
        self.module_vars: Dict[str, tk.BooleanVar] = {}

        self.session_button: Optional[ttk.Button] = None
        self.trial_button: Optional[ttk.Button] = None
        self.shutdown_button: Optional[ttk.Button] = None

        self.current_time_label: Optional[tk.Label] = None
        self.session_status_label: Optional[tk.Label] = None
        self.session_timer_label: Optional[tk.Label] = None
        self.trial_timer_label: Optional[tk.Label] = None
        self.trial_counter_label: Optional[tk.Label] = None
        self.session_path_label: Optional[tk.Label] = None

        self.trial_label_var: Optional[tk.StringVar] = None
        self.trial_label_entry: Optional[ttk.Entry] = None

        self.session_start_time: Optional[datetime.datetime] = None
        self.trial_start_time: Optional[datetime.datetime] = None
        self.trial_counter: int = 0
        self.session_timer_task: Optional[asyncio.Task] = None
        self.trial_timer_task: Optional[asyncio.Task] = None
        self.clock_timer_task: Optional[asyncio.Task] = None

        self.running = False
        self.session_active = False
        self.trial_active = False

        self.config_path = Path(__file__).parent.parent.parent / "config.txt"

    def build_ui(self) -> None:
        self.root = tk.Tk()
        self.root.title("RS Logger")

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
            self.root.minsize(window_width, window_height)
        else:
            self.root.geometry("800x600")
            self.root.minsize(800, 600)

        self.root.configure(bg='#F5F5F7')

        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=0)
        self.root.rowconfigure(1, weight=1)

        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)

        modules_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Modules", menu=modules_menu)

        for idx, module_info in enumerate(self.logger_system.get_available_modules()):
            is_enabled = self.logger_system.is_module_selected(module_info.name)
            var = tk.BooleanVar(value=is_enabled)
            self.module_vars[module_info.name] = var

            modules_menu.add_checkbutton(
                label=module_info.display_name,
                variable=var,
                command=lambda name=module_info.name: self._on_module_menu_toggle(name)
            )

        help_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Help", menu=help_menu)

        help_menu.add_command(
            label="Quick Start Guide",
            command=self._show_help
        )

        help_menu.add_separator()

        help_menu.add_command(
            label="About RED Scientific",
            command=self._show_about
        )

        help_menu.add_command(
            label="System Information",
            command=self._show_system_info
        )

        help_menu.add_separator()

        help_menu.add_command(
            label="Open Logs Directory",
            command=self._open_logs_directory
        )

        help_menu.add_separator()

        help_menu.add_command(
            label="View Config File",
            command=self._open_config_file
        )

        help_menu.add_command(
            label="Reset Settings",
            command=self._reset_settings
        )

        help_menu.add_separator()

        help_menu.add_command(
            label="Report Issue",
            command=self._report_issue
        )

        header_frame = tk.Frame(self.root, bg='white', height=80)
        header_frame.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 5))
        header_frame.grid_propagate(False)

        try:
            logo_path = Path(__file__).parent / "logo_100.png"
            logo_image = Image.open(logo_path)
            new_size = (int(logo_image.width * 0.6), int(logo_image.height * 0.6))
            logo_image = logo_image.resize(new_size, Image.Resampling.LANCZOS)
            logo_photo = ImageTk.PhotoImage(logo_image)

            logo_label = tk.Label(header_frame, image=logo_photo, bg='white')
            logo_label.image = logo_photo
            logo_label.pack(expand=True, pady=10)
        except Exception as e:
            self.logger.warning("Could not load logo: %s", e)

        main_frame = ttk.Frame(self.root, padding="5")
        main_frame.grid(row=1, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(0, weight=1)  # Control panel expands

        style = ttk.Style()
        style.theme_use('clam')  # Use clam theme for better customization

        available_fonts = tkfont.families()
        button_font = ('Helvetica', 10)
        if 'SF Pro Display' in available_fonts:
            button_font = ('SF Pro Display', 10)
        elif 'Segoe UI' in available_fonts:
            button_font = ('Segoe UI', 10)

        style.configure(
            'Active.TButton',
            background='#007AFF',
            foreground='white',
            borderwidth=1,
            bordercolor='#007AFF',
            relief='flat',
            padding=(3, 3),
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
            padding=(3, 3),
            font=button_font
        )
        style.map('Inactive.TButton',
                  background=[('pressed', '#D1D1D6'), ('active', '#D1D1D6')],
                  foreground=[('pressed', '#8E8E93'), ('active', '#8E8E93')])

        control_frame = ttk.Frame(main_frame)
        control_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 5))
        control_frame.columnconfigure(0, weight=0)
        control_frame.columnconfigure(1, weight=1)
        control_frame.rowconfigure(0, weight=1)

        session_trial_frame = ttk.Frame(control_frame)
        session_trial_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        session_trial_frame.columnconfigure(0, weight=0)
        session_trial_frame.columnconfigure(1, weight=0)
        session_trial_frame.rowconfigure(0, weight=1)
        session_trial_frame.rowconfigure(1, weight=0)

        session_control_frame = tk.LabelFrame(session_trial_frame, text="Session", padx=8, pady=8)
        session_control_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), padx=(0, 2))

        self.session_button = ttk.Button(
            session_control_frame,
            text="Start",
            style='Active.TButton',
            width=10,
            command=self._on_toggle_session
        )
        self.session_button.pack(fill=tk.BOTH, expand=True)

        trial_control_frame = tk.LabelFrame(session_trial_frame, text="Trial", padx=8, pady=8)
        trial_control_frame.grid(row=0, column=1, sticky=(tk.W, tk.E, tk.N, tk.S), padx=(2, 2))

        self.trial_button = ttk.Button(
            trial_control_frame,
            text="Record",
            style='Inactive.TButton',
            width=10,
            command=self._on_toggle_trial
        )
        self.trial_button.pack(fill=tk.BOTH, expand=True)

        trial_label_frame = tk.LabelFrame(session_trial_frame, text="Trial Label", padx=2, pady=2)
        trial_label_frame.grid(row=1, column=0, columnspan=2, sticky=(tk.W, tk.E), padx=(0, 2), pady=(2, 0))

        self.trial_label_var = tk.StringVar()
        self.trial_label_entry = ttk.Entry(
            trial_label_frame,
            textvariable=self.trial_label_var,
            font=("Arial", 10),
            foreground='#999999'
        )
        self.trial_label_entry.pack(fill=tk.X, expand=True)

        self.trial_label_var.set("None")
        self.trial_label_entry.bind("<FocusIn>", self._on_trial_label_focus_in)
        self.trial_label_entry.bind("<FocusOut>", self._on_trial_label_focus_out)

        info_frame = tk.LabelFrame(control_frame, text="Information", padx=2, pady=2)
        info_frame.grid(row=0, column=1, sticky=(tk.W, tk.E, tk.N, tk.S), padx=(5, 0))
        info_frame.columnconfigure(0, weight=0)
        info_frame.columnconfigure(1, weight=1)

        tk.Label(info_frame, text="Current Time:", anchor='w', font=("Arial", 9)).grid(
            row=0, column=0, sticky='w', pady=1
        )
        self.current_time_label = tk.Label(
            info_frame,
            text="--:--:--",
            anchor='e',
            font=("Arial", 9)
        )
        self.current_time_label.grid(row=0, column=1, sticky='e', pady=0)

        tk.Label(info_frame, text="Session Time:", anchor='w', font=("Arial", 9)).grid(
            row=1, column=0, sticky='w', pady=1
        )
        self.session_timer_label = tk.Label(
            info_frame,
            text="--:--:--",
            anchor='e',
            font=("Arial", 9)
        )
        self.session_timer_label.grid(row=1, column=1, sticky='e', pady=0)

        tk.Label(info_frame, text="Trial Time:", anchor='w', font=("Arial", 9)).grid(
            row=2, column=0, sticky='w', pady=1
        )
        self.trial_timer_label = tk.Label(
            info_frame,
            text="--:--:--",
            anchor='e',
            font=("Arial", 9)
        )
        self.trial_timer_label.grid(row=2, column=1, sticky='e', pady=0)

        tk.Label(info_frame, text="Trial Count:", anchor='w', font=("Arial", 9)).grid(
            row=3, column=0, sticky='w', pady=1
        )
        self.trial_counter_label = tk.Label(
            info_frame,
            text="0",
            anchor='e',
            font=("Arial", 9)
        )
        self.trial_counter_label.grid(row=3, column=1, sticky='e', pady=0)

        tk.Label(info_frame, text="Status:", anchor='w', font=("Arial", 9)).grid(
            row=4, column=0, sticky='w', pady=1
        )
        self.session_status_label = tk.Label(
            info_frame,
            text="Idle",
            anchor='e',
            font=("Arial", 9)
        )
        self.session_status_label.grid(row=4, column=1, sticky='e', pady=0)

        tk.Label(info_frame, text="Path:", anchor='w', font=("Arial", 8), foreground='#666666').grid(
            row=5, column=0, sticky='w', pady=(2, 0)
        )
        session_info = self.logger_system.get_session_info()
        self.session_path_label = tk.Label(
            info_frame,
            text=f"{session_info['session_dir']}",
            anchor='e',
            font=("Arial", 8),
            foreground='#666666'
        )
        self.session_path_label.grid(row=5, column=1, sticky='e', pady=(2, 0))

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
            padding=(3, 3),
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

        self.root.protocol("WM_DELETE_WINDOW", self._on_shutdown)


    def _on_trial_label_focus_in(self, event) -> None:
        if self.trial_label_var.get() == "None":
            self.trial_label_var.set("")
            self.trial_label_entry.config(foreground='#000000')

    def _on_trial_label_focus_out(self, event) -> None:
        if not self.trial_label_var.get().strip():
            self.trial_label_var.set("None")
            self.trial_label_entry.config(foreground='#999999')

    def _on_module_menu_toggle(self, module_name: str) -> None:
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

    def _on_toggle_session(self) -> None:
        if self.session_active:
            self.logger.info("Stopping session...")
            asyncio.create_task(self._stop_session_async())
        else:
            config_manager = get_config_manager()
            config = config_manager.read_config(self.config_path)
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

                config_manager.write_config(self.config_path, {'last_session_dir': session_dir})
                self.logger.debug("Saved last session directory to config: %s", session_dir)

                asyncio.create_task(self._start_session_async(Path(session_dir)))
            else:
                self.logger.info("Session start cancelled - no directory selected")

    def _on_toggle_trial(self) -> None:
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

            logs_dir = full_session_dir / "logs"
            logs_dir.mkdir(parents=True, exist_ok=True)

            self.logger_system.session_dir = full_session_dir

            from logger_core.event_logger import EventLogger
            self.logger_system.event_logger = EventLogger(full_session_dir, timestamp)
            await self.logger_system.event_logger.initialize()

            await self.logger_system.event_logger.log_button_press("session_start")
            await self.logger_system.event_logger.log_session_start(str(full_session_dir))

            self.session_active = True
            self.session_start_time = datetime.datetime.now()
            self.trial_counter = 0

            self.session_button.config(text="Stop", style='Active.TButton')
            self.trial_button.config(style='Active.TButton')

            self.session_status_label.config(text="Active")
            self.session_path_label.config(text=f"{full_session_dir}")
            self.trial_counter_label.config(text="0")

            if self.session_timer_task:
                self.session_timer_task.cancel()
            self.session_timer_task = asyncio.create_task(self._update_session_timer())

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
            self.session_start_time = None

            self.session_button.config(text="Start", style='Active.TButton')
            self.trial_button.config(style='Inactive.TButton')

            self.session_status_label.config(text="Idle")
            self.session_timer_label.config(text="--:--:--")

            if self.session_timer_task:
                self.session_timer_task.cancel()
                self.session_timer_task = None

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

            results = await self.logger_system.start_recording_all(next_trial_num)

            failed = [name for name, success in results.items() if not success]
            if failed:
                messagebox.showwarning(
                    "Recording Warning",
                    f"Failed to start recording on: {', '.join(failed)}"
                )

            self.trial_active = True
            self.trial_start_time = datetime.datetime.now()

            self.trial_button.config(text="Pause", style='Active.TButton')

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

            if self.logger_system.event_logger:
                await self.logger_system.event_logger.log_button_press("trial_pause", f"trial={self.trial_counter}")
                await self.logger_system.event_logger.log_trial_stop(self.trial_counter)

            self.trial_button.config(text="Record", style='Active.TButton')

            self.trial_counter_label.config(text=f"{self.trial_counter}")
            self.trial_timer_label.config(text="--:--:--")

            if self.trial_timer_task:
                self.trial_timer_task.cancel()
                self.trial_timer_task = None

            self.logger.info("Trial stopped (trial #%d)", self.trial_counter)

        except Exception as e:
            self.logger.error("Error stopping trial: %s", e, exc_info=True)
            messagebox.showerror("Error", f"Failed to stop trial: {e}")

    def _on_shutdown(self) -> None:
        if self.logger_system.event_logger:
            asyncio.create_task(self.logger_system.event_logger.log_button_press("shutdown"))

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

            if self.clock_timer_task:
                self.clock_timer_task.cancel()
                self.clock_timer_task = None

            await self.logger_system.cleanup()
        finally:
            self.running = False
            if self.root:
                self.root.quit()

    async def _update_clock_timer(self) -> None:
        try:
            while self.running:
                current_time = datetime.datetime.now()
                time_str = current_time.strftime("%H:%M:%S")
                self.current_time_label.config(text=time_str)
                await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            pass

    async def _update_session_timer(self) -> None:
        try:
            while self.session_start_time and self.running:
                elapsed = datetime.datetime.now() - self.session_start_time
                hours = int(elapsed.total_seconds() // 3600)
                minutes = int((elapsed.total_seconds() % 3600) // 60)
                seconds = int(elapsed.total_seconds() % 60)

                self.session_timer_label.config(text=f"{hours:02d}:{minutes:02d}:{seconds:02d}")

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

                self.trial_timer_label.config(text=f"{hours:02d}:{minutes:02d}:{seconds:02d}")

                await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            pass

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

    async def run(self) -> None:
        self.running = True
        self.build_ui()

        self.clock_timer_task = asyncio.create_task(self._update_clock_timer())

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

    def _show_about(self) -> None:
        try:
            from .help_dialogs import AboutDialog
            AboutDialog(self.root)
        except Exception as e:
            self.logger.error("Failed to show About dialog: %s", e)

    def _show_system_info(self) -> None:
        try:
            from .help_dialogs import SystemInfoDialog
            SystemInfoDialog(self.root, self.logger_system)
        except Exception as e:
            self.logger.error("Failed to show System Info dialog: %s", e)

    def _show_help(self) -> None:
        try:
            from .help_dialogs import QuickStartDialog
            QuickStartDialog(self.root)
        except Exception as e:
            self.logger.error("Failed to show Help dialog: %s", e)

    def _open_logs_directory(self) -> None:
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

    def _open_config_file(self) -> None:
        try:
            config_path = Path(__file__).parent.parent.parent / "config.txt"

            if not config_path.exists():
                self.logger.warning("Config file not found: %s", config_path)
                return

            if sys.platform == 'linux':
                subprocess.Popen(['xdg-open', str(config_path)])
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', str(config_path)])
            elif sys.platform == 'win32':
                subprocess.Popen(['notepad.exe', str(config_path)])

            self.logger.info("Opened config file: %s", config_path)
        except Exception as e:
            self.logger.error("Failed to open config file: %s", e)

    def _reset_settings(self) -> None:
        try:
            config_path = Path(__file__).parent.parent.parent / "config.txt"
            from .help_dialogs import ResetSettingsDialog
            ResetSettingsDialog(self.root, config_path)
        except Exception as e:
            self.logger.error("Failed to reset settings: %s", e)

    def _report_issue(self) -> None:
        try:
            url = "https://github.com/JoelCooperPhD/RPi_Logger/issues"
            webbrowser.open(url)
            self.logger.info("Opened issue tracker: %s", url)
        except Exception as e:
            self.logger.error("Failed to open issue tracker: %s", e)
