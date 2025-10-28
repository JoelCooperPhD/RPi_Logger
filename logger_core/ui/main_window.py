
import asyncio
import logging
import tkinter as tk
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText
from pathlib import Path
from typing import Dict, Optional
from PIL import Image, ImageTk

from ..logger_system import LoggerSystem
from ..config_manager import get_config_manager
from ..paths import CONFIG_PATH, LOGO_PATH
from .main_controller import MainController
from .timer_manager import TimerManager


class TextHandler(logging.Handler):

    def __init__(self, text_widget: ScrolledText):
        super().__init__()
        self.text_widget = text_widget
        self.max_lines = 500
        self.setFormatter(
            logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                datefmt='%H:%M:%S'
            )
        )

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record) + '\n'
            self.text_widget.after(0, self._append_log, msg)
        except Exception:
            pass

    def _append_log(self, msg: str) -> None:
        try:
            self.text_widget.config(state='normal')
            self.text_widget.insert(tk.END, msg)
            self.text_widget.see(tk.END)

            num_lines = int(self.text_widget.index('end-1c').split('.')[0])
            if num_lines > self.max_lines:
                self.text_widget.delete('1.0', f'{num_lines - self.max_lines}.0')

            self.text_widget.config(state='disabled')
        except Exception:
            pass


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

        self.current_time_label: Optional[ttk.Label] = None
        self.session_status_label: Optional[ttk.Label] = None
        self.session_timer_label: Optional[ttk.Label] = None
        self.trial_timer_label: Optional[ttk.Label] = None
        self.trial_counter_label: Optional[ttk.Label] = None
        self.session_path_label: Optional[ttk.Label] = None
        self.cpu_label: Optional[ttk.Label] = None
        self.ram_label: Optional[ttk.Label] = None
        self.disk_label: Optional[ttk.Label] = None

        self.trial_label_var: Optional[tk.StringVar] = None
        self.trial_label_entry: Optional[ttk.Entry] = None

        self.logger_frame: Optional[ttk.LabelFrame] = None
        self.logger_text: Optional[ScrolledText] = None
        self.logger_visible_var: Optional[tk.BooleanVar] = None
        self.log_handler: Optional[logging.Handler] = None

    def build_ui(self) -> None:
        self.root = tk.Tk()
        self.root.title("RS Logger")

        config_manager = get_config_manager()

        if CONFIG_PATH.exists():
            config = config_manager.read_config(CONFIG_PATH)
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


        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=0)
        self.root.rowconfigure(1, weight=1)
        self.root.rowconfigure(2, weight=0)

        self._build_menubar()
        self._build_header()
        self._build_main_content()
        self._build_logger_frame()

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
            self.trial_timer_label,
            self.cpu_label,
            self.ram_label,
            self.disk_label
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

        config_manager = get_config_manager()
        logger_visible_default = True
        if CONFIG_PATH.exists():
            config = config_manager.read_config(CONFIG_PATH)
            logger_visible_default = config_manager.get_bool(config, 'gui_logger_visible', default=True)
        self.logger_visible_var = tk.BooleanVar(value=logger_visible_default)

        view_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="View", menu=view_menu)

        view_menu.add_checkbutton(
            label="Show Logger",
            variable=self.logger_visible_var,
            command=self._toggle_logger
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
        header_frame = ttk.Frame(self.root, height=80)
        header_frame.grid(row=0, column=0, sticky=(tk.W, tk.E), padx=5, pady=(5, 0))
        header_frame.grid_propagate(False)

        try:
            logo_image = Image.open(LOGO_PATH)
            new_size = (int(logo_image.width * 0.6), int(logo_image.height * 0.6))
            logo_image = logo_image.resize(new_size, Image.Resampling.LANCZOS)
            logo_photo = ImageTk.PhotoImage(logo_image)

            logo_label = ttk.Label(header_frame, image=logo_photo)
            logo_label.image = logo_photo
            logo_label.pack(expand=True, pady=10)
        except Exception as e:
            self.logger.warning("Could not load logo: %s", e)

    def _build_main_content(self) -> None:
        main_frame = ttk.Frame(self.root)
        main_frame.grid(row=1, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), padx=5, pady=5)
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(0, weight=1)
        main_frame.rowconfigure(1, weight=0)

        self._configure_styles()

        control_frame = ttk.Frame(main_frame)
        control_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 5))
        control_frame.columnconfigure(0, weight=0)
        control_frame.columnconfigure(1, weight=0)
        control_frame.columnconfigure(2, weight=2)
        control_frame.rowconfigure(0, weight=1)
        control_frame.rowconfigure(1, weight=0)

        self._build_session_trial_controls(control_frame)
        self._build_info_panel(control_frame)

        self._build_shutdown_button(main_frame)

    def _configure_styles(self) -> None:
        style = ttk.Style()
        style.theme_use('clam')

        style.configure(
            'Active.TButton',
            background='#007AFF',
            foreground='white',
            borderwidth=1,
            bordercolor='#007AFF',
            relief='flat',
            padding=(3, 3)
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
            padding=(3, 3)
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
            padding=(3, 3)
        )
        style.map('Shutdown.TButton',
                  background=[('pressed', '#CC0000'), ('active', '#E60000')],
                  foreground=[('pressed', 'white'), ('active', 'white')])

    def _build_session_trial_controls(self, parent: ttk.Frame) -> None:
        session_control_frame = ttk.LabelFrame(parent, text="Session", padding=(8, 8))
        session_control_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), padx=(0, 5))
        session_control_frame.columnconfigure(0, weight=1)
        session_control_frame.rowconfigure(0, weight=1)

        self.session_button = ttk.Button(
            session_control_frame,
            text="Start",
            style='Active.TButton',
            width=10,
            command=self.controller.on_toggle_session
        )
        self.session_button.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        trial_control_frame = ttk.LabelFrame(parent, text="Trial", padding=(8, 8))
        trial_control_frame.grid(row=0, column=1, sticky=(tk.W, tk.E, tk.N, tk.S), padx=(0, 5))
        trial_control_frame.columnconfigure(0, weight=1)
        trial_control_frame.rowconfigure(0, weight=1)

        self.trial_button = ttk.Button(
            trial_control_frame,
            text="Record",
            style='Inactive.TButton',
            width=10,
            command=self.controller.on_toggle_trial
        )
        self.trial_button.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        trial_label_frame = ttk.LabelFrame(parent, text="Trial Label", padding=(2, 2))
        trial_label_frame.grid(row=1, column=0, columnspan=2, sticky=(tk.W, tk.E, tk.N, tk.S), padx=(0, 5), pady=(5, 0))
        trial_label_frame.columnconfigure(0, weight=1)
        trial_label_frame.rowconfigure(0, weight=1)

        self.trial_label_var = tk.StringVar()
        self.trial_label_entry = ttk.Entry(
            trial_label_frame,
            textvariable=self.trial_label_var
        )
        self.trial_label_entry.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

    def _build_info_panel(self, parent: ttk.Frame) -> None:
        info_frame = ttk.LabelFrame(parent, text="Information", padding=(2, 2))
        info_frame.grid(row=0, column=2, rowspan=2, sticky=(tk.W, tk.E, tk.N, tk.S), padx=(5, 0))
        info_frame.columnconfigure(0, weight=0)
        info_frame.columnconfigure(1, weight=1)

        ttk.Label(info_frame, text="Current Time:", anchor='w').grid(
            row=0, column=0, sticky='w', pady=1
        )
        self.current_time_label = ttk.Label(
            info_frame,
            text="--:--:--",
            anchor='e'
        )
        self.current_time_label.grid(row=0, column=1, sticky='e', pady=0)

        ttk.Label(info_frame, text="Session Time:", anchor='w').grid(
            row=1, column=0, sticky='w', pady=1
        )
        self.session_timer_label = ttk.Label(
            info_frame,
            text="--:--:--",
            anchor='e'
        )
        self.session_timer_label.grid(row=1, column=1, sticky='e', pady=0)

        ttk.Label(info_frame, text="Trial Time:", anchor='w').grid(
            row=2, column=0, sticky='w', pady=1
        )
        self.trial_timer_label = ttk.Label(
            info_frame,
            text="--:--:--",
            anchor='e'
        )
        self.trial_timer_label.grid(row=2, column=1, sticky='e', pady=0)

        ttk.Label(info_frame, text="Trial Count:", anchor='w').grid(
            row=3, column=0, sticky='w', pady=1
        )
        self.trial_counter_label = ttk.Label(
            info_frame,
            text="0",
            anchor='e'
        )
        self.trial_counter_label.grid(row=3, column=1, sticky='e', pady=0)

        ttk.Label(info_frame, text="Status:", anchor='w').grid(
            row=4, column=0, sticky='w', pady=1
        )
        self.session_status_label = ttk.Label(
            info_frame,
            text="Idle",
            anchor='e'
        )
        self.session_status_label.grid(row=4, column=1, sticky='e', pady=0)

        ttk.Label(info_frame, text="Path:", anchor='w', foreground='#666666').grid(
            row=5, column=0, sticky='w', pady=(2, 0)
        )
        session_info = self.logger_system.get_session_info()
        self.session_path_label = ttk.Label(
            info_frame,
            text=f"{session_info['session_dir']}",
            anchor='e',
            foreground='#666666'
        )
        self.session_path_label.grid(row=5, column=1, sticky='e', pady=(2, 0))

        ttk.Separator(info_frame, orient='horizontal').grid(
            row=6, column=0, columnspan=2, sticky='ew', pady=5
        )

        ttk.Label(info_frame, text="CPU:", anchor='w').grid(
            row=7, column=0, sticky='w', pady=1
        )
        self.cpu_label = ttk.Label(
            info_frame,
            text="--",
            anchor='e'
        )
        self.cpu_label.grid(row=7, column=1, sticky='e', pady=0)

        ttk.Label(info_frame, text="RAM:", anchor='w').grid(
            row=8, column=0, sticky='w', pady=1
        )
        self.ram_label = ttk.Label(
            info_frame,
            text="--",
            anchor='e'
        )
        self.ram_label.grid(row=8, column=1, sticky='e', pady=0)

        ttk.Label(info_frame, text="Free Disk:", anchor='w').grid(
            row=9, column=0, sticky='w', pady=1
        )
        self.disk_label = ttk.Label(
            info_frame,
            text="--",
            anchor='e'
        )
        self.disk_label.grid(row=9, column=1, sticky='e', pady=0)

    def _build_shutdown_button(self, parent: ttk.Frame) -> None:
        self.shutdown_button = ttk.Button(
            parent,
            text="Shutdown Logger",
            style='Shutdown.TButton',
            command=self.controller.on_shutdown
        )
        self.shutdown_button.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=(0, 0))

    def _build_logger_frame(self) -> None:
        self.logger_frame = ttk.LabelFrame(self.root, text="Logger", padding="3")
        self.logger_frame.grid(row=2, column=0, sticky=(tk.W, tk.E), padx=5, pady=(0, 5))
        self.logger_frame.columnconfigure(0, weight=1)

        self.logger_text = ScrolledText(
            self.logger_frame,
            height=2,
            wrap=tk.WORD,
            bg='#f5f5f5',
            fg='#333333',
            state='disabled'
        )
        self.logger_text.grid(row=0, column=0, sticky=(tk.W, tk.E))

        if not self.logger_visible_var.get():
            self.logger_frame.grid_remove()

        self._setup_log_handler()

    def _toggle_logger(self) -> None:
        visible = self.logger_visible_var.get()

        if visible:
            self.logger_frame.grid(row=2, column=0, sticky=(tk.W, tk.E), padx=5, pady=(0, 5))
        else:
            self.logger_frame.grid_remove()

        self.root.update_idletasks()

        config_manager = get_config_manager()
        config_manager.write_config(CONFIG_PATH, {'gui_logger_visible': visible})
        self.logger.debug("Logger visibility set to: %s", visible)

    def _setup_log_handler(self) -> None:
        if self.logger_text is None:
            return

        self.log_handler = TextHandler(self.logger_text)
        self.log_handler.setLevel(logging.INFO)

        root_logger = logging.getLogger()
        root_logger.addHandler(self.log_handler)

        self.logger.info("Logger display initialized")

    def cleanup_log_handler(self) -> None:
        if self.log_handler:
            root_logger = logging.getLogger()
            root_logger.removeHandler(self.log_handler)
            self.log_handler = None

    def save_window_geometry(self) -> None:
        if not self.root:
            return

        try:
            from Modules.base import gui_utils

            geometry_str = self.root.geometry()
            parsed = gui_utils.parse_geometry_string(geometry_str)

            if parsed:
                width, height, x, y = parsed

                config_manager = get_config_manager()
                updates = {
                    'window_x': x,
                    'window_y': y,
                    'window_width': width,
                    'window_height': height,
                }

                if config_manager.write_config(CONFIG_PATH, updates):
                    self.logger.info("Saved main logger window geometry: %dx%d+%d+%d", width, height, x, y)
                else:
                    self.logger.warning("Failed to save window geometry")
            else:
                self.logger.warning("Failed to parse window geometry: %s", geometry_str)
        except Exception as e:
            self.logger.error("Error saving window geometry: %s", e, exc_info=True)

    async def run(self) -> None:
        from async_tkinter_loop import main_loop

        self.build_ui()

        await self.timer_manager.start_clock()

        asyncio.create_task(self.controller.auto_start_modules())

        try:
            await main_loop(self.root)
        except tk.TclError:
            pass
        except Exception as e:
            self.logger.error("UI loop error: %s", e)

        self.logger.info("UI stopped")
