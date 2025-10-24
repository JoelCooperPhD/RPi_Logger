
import asyncio
import logging
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk
from pathlib import Path
from typing import Dict, Optional
from PIL import Image, ImageTk

from ..logger_system import LoggerSystem
from ..config_manager import get_config_manager
from .main_controller import MainController
from .timer_manager import TimerManager


class MainWindow:

    def __init__(self, logger_system: LoggerSystem):
        self.logger = logging.getLogger("MainWindow")
        self.logger_system = logger_system

        self.timer_manager = TimerManager()
        self.controller = MainController(logger_system, self.timer_manager)

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

        self._build_menubar()
        self._build_header()
        self._build_main_content()

        self.root.protocol("WM_DELETE_WINDOW", self.controller.on_shutdown)

        self.controller.set_widgets(
            self.root,
            self.module_vars,
            self.session_button,
            self.trial_button,
            self.shutdown_button,
            self.session_status_label,
            self.trial_counter_label,
            self.session_path_label,
            self.trial_label_var
        )

        self.timer_manager.set_labels(
            self.current_time_label,
            self.session_timer_label,
            self.trial_timer_label
        )

    def _build_menubar(self) -> None:
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
                command=lambda name=module_info.name: self.controller.on_module_menu_toggle(name)
            )

        help_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Help", menu=help_menu)

        help_menu.add_command(
            label="Quick Start Guide",
            command=self.controller.show_help
        )

        help_menu.add_separator()

        help_menu.add_command(
            label="About RED Scientific",
            command=self.controller.show_about
        )

        help_menu.add_command(
            label="System Information",
            command=self.controller.show_system_info
        )

        help_menu.add_separator()

        help_menu.add_command(
            label="Open Logs Directory",
            command=self.controller.open_logs_directory
        )

        help_menu.add_separator()

        help_menu.add_command(
            label="View Config File",
            command=self.controller.open_config_file
        )

        help_menu.add_command(
            label="Reset Settings",
            command=self.controller.reset_settings
        )

        help_menu.add_separator()

        help_menu.add_command(
            label="Report Issue",
            command=self.controller.report_issue
        )

    def _build_header(self) -> None:
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

    def _build_main_content(self) -> None:
        main_frame = ttk.Frame(self.root, padding="5")
        main_frame.grid(row=1, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(0, weight=1)

        self._configure_styles()

        control_frame = ttk.Frame(main_frame)
        control_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 5))
        control_frame.columnconfigure(0, weight=0)
        control_frame.columnconfigure(1, weight=1)
        control_frame.rowconfigure(0, weight=1)

        self._build_session_trial_controls(control_frame)
        self._build_info_panel(control_frame)
        self._build_shutdown_button(main_frame)

    def _configure_styles(self) -> None:
        style = ttk.Style()
        style.theme_use('clam')

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

    def _build_session_trial_controls(self, parent: ttk.Frame) -> None:
        session_trial_frame = ttk.Frame(parent)
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
            command=self.controller.on_toggle_session
        )
        self.session_button.pack(fill=tk.BOTH, expand=True)

        trial_control_frame = tk.LabelFrame(session_trial_frame, text="Trial", padx=8, pady=8)
        trial_control_frame.grid(row=0, column=1, sticky=(tk.W, tk.E, tk.N, tk.S), padx=(2, 2))

        self.trial_button = ttk.Button(
            trial_control_frame,
            text="Record",
            style='Inactive.TButton',
            width=10,
            command=self.controller.on_toggle_trial
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

    def _build_info_panel(self, parent: ttk.Frame) -> None:
        info_frame = tk.LabelFrame(parent, text="Information", padx=2, pady=2)
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

    def _build_shutdown_button(self, parent: ttk.Frame) -> None:
        shutdown_frame = ttk.Frame(parent)
        shutdown_frame.grid(row=3, column=0, sticky=(tk.W, tk.E), pady=(0, 0))
        shutdown_frame.columnconfigure(0, weight=1)

        self.shutdown_button = ttk.Button(
            shutdown_frame,
            text="Shutdown Logger",
            style='Shutdown.TButton',
            command=self.controller.on_shutdown
        )
        self.shutdown_button.pack(fill=tk.X)

    def _on_trial_label_focus_in(self, event) -> None:
        if self.trial_label_var.get() == "None":
            self.trial_label_var.set("")
            self.trial_label_entry.config(foreground='#000000')

    def _on_trial_label_focus_out(self, event) -> None:
        if not self.trial_label_var.get().strip():
            self.trial_label_var.set("None")
            self.trial_label_entry.config(foreground='#999999')

    async def run(self) -> None:
        self.controller.running = True
        self.build_ui()

        await self.timer_manager.start_clock()

        await self.controller.auto_start_modules()

        while self.controller.running:
            try:
                self.root.update()
                await asyncio.sleep(0.01)
            except tk.TclError:
                break
            except Exception as e:
                self.logger.error("UI loop error: %s", e)
                break

        self.logger.info("UI stopped")
