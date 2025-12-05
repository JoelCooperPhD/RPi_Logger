
import asyncio
import logging
from rpi_logger.core.logging_utils import get_module_logger
import tkinter as tk
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText
from pathlib import Path
from typing import Dict, Optional
from PIL import Image
import io

from ..logger_system import LoggerSystem
from ..config_manager import get_config_manager
from ..paths import CONFIG_PATH, LOGO_PATH
from .main_controller import MainController
from .timer_manager import TimerManager
from .devices_panel import USBDevicesPanel
from .theme import Theme, Colors, RoundedButton


class TextHandler(logging.Handler):

    def __init__(self, text_widget: ScrolledText):
        super().__init__()
        self.text_widget = text_widget
        self.max_lines = 500
        self._closed = False
        self.setFormatter(
            logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                datefmt='%H:%M:%S'
            )
        )

    def emit(self, record: logging.LogRecord) -> None:
        if self._closed:
            return
        try:
            msg = self.format(record) + '\n'
            self.text_widget.after(0, self._append_log, msg)
        except Exception:
            pass

    def _append_log(self, msg: str) -> None:
        if self._closed:
            return
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

    def close(self) -> None:
        self._closed = True
        super().close()


class MainWindow:

    def __init__(self, logger_system: LoggerSystem):
        self.logger = get_module_logger("MainWindow")
        self.logger_system = logger_system

        self.timer_manager = TimerManager()
        self.controller = MainController(logger_system, self.timer_manager)

        self.root: Optional[tk.Tk] = None
        self.module_vars: Dict[str, tk.BooleanVar] = {}

        self.session_button: Optional[RoundedButton] = None
        self.trial_button: Optional[RoundedButton] = None

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

        # USB Devices panel
        self.devices_panel: Optional[USBDevicesPanel] = None
        self._main_frame: Optional[ttk.Frame] = None

        self._pending_tasks: list[asyncio.Task] = []


    def build_ui(self) -> None:
        self.root = tk.Tk()
        self.root.title("RED Scientific - Data Logger")

        # Apply theme styles immediately after creating root window
        # This must happen before any ttk widgets are created
        Theme.apply(self.root)

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
        self.root.rowconfigure(0, weight=0)  # Header
        self.root.rowconfigure(1, weight=1)  # Main content (2-column: left controls, right devices)
        self.root.rowconfigure(2, weight=0)  # Logger frame

        self._build_menubar()
        self._build_header()
        self._build_main_content()
        self._build_devices_panel()
        self._build_logger_frame()

        self.root.protocol("WM_DELETE_WINDOW", self.controller.on_shutdown)

        self.controller.set_widgets(
            self.root,
            self.module_vars,
            self.session_button,
            self.trial_button,
            self.session_status_label,
            self.trial_counter_label,
            self.session_path_label,
            self.trial_label_var
        )

        # Wire up device UI callback
        self.logger_system.set_devices_ui_callback(self.update_devices_display)

        # Wire up window visibility callback for Show/Hide button state
        self.logger_system.set_window_visibility_callback(self.on_window_visibility_changed)

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
        Theme.configure_menu(menubar)
        self.root.config(menu=menubar)

        modules_menu = tk.Menu(menubar, tearoff=0)
        Theme.configure_menu(modules_menu)
        menubar.add_cascade(label="Modules", menu=modules_menu)

        for idx, module_info in enumerate(self.logger_system.get_available_modules()):
            is_enabled = self.logger_system.is_module_enabled(module_info.name)
            var = tk.BooleanVar(value=is_enabled)
            self.module_vars[module_info.name] = var

            modules_menu.add_checkbutton(
                label=module_info.display_name,
                variable=var,
                command=lambda name=module_info.name: self._schedule_task(
                    self.controller.on_module_menu_toggle(name)
                )
            )

        config_manager = get_config_manager()
        logger_visible_default = True
        if CONFIG_PATH.exists():
            config = config_manager.read_config(CONFIG_PATH)
            logger_visible_default = config_manager.get_bool(config, 'gui_logger_visible', default=True)
        self.logger_visible_var = tk.BooleanVar(value=logger_visible_default)

        view_menu = tk.Menu(menubar, tearoff=0)
        Theme.configure_menu(view_menu)
        menubar.add_cascade(label="View", menu=view_menu)

        view_menu.add_checkbutton(
            label="Show System Log",
            variable=self.logger_visible_var,
            command=self._toggle_logger
        )

        help_menu = tk.Menu(menubar, tearoff=0)
        Theme.configure_menu(help_menu)
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
            logo_image = Image.open(LOGO_PATH).convert("RGB")
            new_size = (int(logo_image.width * 0.6), int(logo_image.height * 0.6))
            logo_image = logo_image.resize(new_size, Image.Resampling.LANCZOS)
            # Use native Tk PhotoImage with PPM to avoid PIL ImageTk issues on Python 3.13
            ppm_data = io.BytesIO()
            logo_image.save(ppm_data, format="PPM")
            logo_photo = tk.PhotoImage(data=ppm_data.getvalue())

            # Create a gray banner frame that matches the logo's background color exactly
            logo_bg_color = '#dcdad5'  # Exact color from logo background pixels
            banner_frame = tk.Frame(header_frame, bg=logo_bg_color)
            banner_frame.pack(expand=True, fill=tk.X, pady=5)

            logo_label = tk.Label(banner_frame, image=logo_photo, bg=logo_bg_color)
            logo_label.image = logo_photo
            logo_label.pack(pady=8)
        except Exception as e:
            self.logger.warning("Could not load logo: %s", e)

    def _build_main_content(self) -> None:
        # Main 2-column layout: left column (controls), right column (devices)
        main_frame = ttk.Frame(self.root)
        main_frame.grid(row=1, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), padx=5, pady=5)
        main_frame.columnconfigure(0, weight=1)  # Left column - 1/5 weight
        main_frame.columnconfigure(1, weight=4)  # Right column - 4/5 weight
        main_frame.rowconfigure(0, weight=1)

        # Store main_frame reference for devices panel
        self._main_frame = main_frame

        # Left column container
        left_column = ttk.Frame(main_frame)
        left_column.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), padx=(0, 10))
        left_column.columnconfigure(0, weight=1)
        left_column.rowconfigure(0, weight=0)  # Session/Trial buttons (fixed)
        left_column.rowconfigure(1, weight=0)  # Trial label entry (fixed)
        left_column.rowconfigure(2, weight=1)  # Information panel (expandable)

        # Build left column contents (stacked vertically)
        self._build_session_trial_controls(left_column)
        self._build_info_panel(left_column)

    def _build_session_trial_controls(self, parent: ttk.Frame) -> None:
        # Row 0: Session and Trial buttons side by side
        buttons_frame = ttk.Frame(parent)
        buttons_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N), pady=(0, 8))
        buttons_frame.columnconfigure(1, weight=1)

        # Session section with label and button
        session_frame = ttk.Frame(buttons_frame)
        session_frame.grid(row=0, column=0, sticky=(tk.W, tk.N), padx=(0, 10))

        session_label = ttk.Label(session_frame, text="Session", font=('TkDefaultFont', 10, 'bold'))
        session_label.grid(row=0, column=0, sticky=tk.W, pady=(0, 4))

        self.session_button = RoundedButton(
            session_frame,
            text="Start",
            style='success',
            width=134,
            height=36,
            command=self.controller.on_toggle_session
        )
        self.session_button.grid(row=1, column=0)

        # Trial section with label and button
        trial_frame = ttk.Frame(buttons_frame)
        trial_frame.grid(row=0, column=1, sticky=(tk.E, tk.N), padx=(0, 0))

        trial_label = ttk.Label(trial_frame, text="Trial", font=('TkDefaultFont', 10, 'bold'))
        trial_label.grid(row=0, column=0, sticky=tk.W, pady=(0, 4))

        self.trial_button = RoundedButton(
            trial_frame,
            text="Record",
            style='inactive',
            width=134,
            height=36,
            command=self.controller.on_toggle_trial
        )
        self.trial_button.grid(row=1, column=0)

        # Row 1: Trial label entry
        trial_label_frame = ttk.Frame(parent)
        trial_label_frame.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=(0, 8))
        trial_label_frame.columnconfigure(1, weight=1)

        trial_label_text = ttk.Label(trial_label_frame, text="Trial Label", font=('TkDefaultFont', 10, 'bold'))
        trial_label_text.grid(row=0, column=0, sticky=tk.W, padx=(0, 8))

        self.trial_label_var = tk.StringVar()
        self.trial_label_entry = ttk.Entry(
            trial_label_frame,
            textvariable=self.trial_label_var,
            width=20
        )
        self.trial_label_entry.grid(row=0, column=1, sticky=(tk.W, tk.E))

    def _build_info_panel(self, parent: ttk.Frame) -> None:
        # Row 2: Information panel (below trial label)
        info_frame = ttk.LabelFrame(parent, text="Information", padding=(5, 5))
        info_frame.grid(row=2, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 0))
        info_frame.columnconfigure(0, weight=0)
        info_frame.columnconfigure(1, weight=1)

        ttk.Label(info_frame, text="Current Time:", anchor='w', style='Inframe.TLabel').grid(
            row=0, column=0, sticky='w', pady=1
        )
        self.current_time_label = ttk.Label(
            info_frame,
            text="--:--:--",
            anchor='e',
            style='Inframe.TLabel'
        )
        self.current_time_label.grid(row=0, column=1, sticky='e', pady=0)

        ttk.Label(info_frame, text="Session Time:", anchor='w', style='Inframe.TLabel').grid(
            row=1, column=0, sticky='w', pady=1
        )
        self.session_timer_label = ttk.Label(
            info_frame,
            text="--:--:--",
            anchor='e',
            style='Inframe.TLabel'
        )
        self.session_timer_label.grid(row=1, column=1, sticky='e', pady=0)

        ttk.Label(info_frame, text="Trial Time:", anchor='w', style='Inframe.TLabel').grid(
            row=2, column=0, sticky='w', pady=1
        )
        self.trial_timer_label = ttk.Label(
            info_frame,
            text="--:--:--",
            anchor='e',
            style='Inframe.TLabel'
        )
        self.trial_timer_label.grid(row=2, column=1, sticky='e', pady=0)

        ttk.Label(info_frame, text="Trial Count:", anchor='w', style='Inframe.TLabel').grid(
            row=3, column=0, sticky='w', pady=1
        )
        self.trial_counter_label = ttk.Label(
            info_frame,
            text="0",
            anchor='e',
            style='Inframe.TLabel'
        )
        self.trial_counter_label.grid(row=3, column=1, sticky='e', pady=0)

        ttk.Label(info_frame, text="Status:", anchor='w', style='Inframe.TLabel').grid(
            row=4, column=0, sticky='w', pady=1
        )
        self.session_status_label = ttk.Label(
            info_frame,
            text="Idle",
            anchor='e',
            style='Inframe.TLabel'
        )
        self.session_status_label.grid(row=4, column=1, sticky='e', pady=0)

        ttk.Label(info_frame, text="Path:", anchor='w', style='Inframe.Secondary.TLabel').grid(
            row=5, column=0, sticky='w', pady=(2, 0)
        )
        session_info = self.logger_system.get_session_info()
        self.session_path_label = ttk.Label(
            info_frame,
            text=f"{session_info['session_dir']}",
            anchor='e',
            style='Inframe.Secondary.TLabel'
        )
        self.session_path_label.grid(row=5, column=1, sticky='e', pady=(2, 0))

        ttk.Separator(info_frame, orient='horizontal').grid(
            row=6, column=0, columnspan=2, sticky='ew', pady=5
        )

        ttk.Label(info_frame, text="CPU:", anchor='w', style='Inframe.TLabel').grid(
            row=7, column=0, sticky='w', pady=1
        )
        self.cpu_label = ttk.Label(
            info_frame,
            text="--",
            anchor='e',
            style='Inframe.TLabel'
        )
        self.cpu_label.grid(row=7, column=1, sticky='e', pady=0)

        ttk.Label(info_frame, text="RAM:", anchor='w', style='Inframe.TLabel').grid(
            row=8, column=0, sticky='w', pady=1
        )
        self.ram_label = ttk.Label(
            info_frame,
            text="--",
            anchor='e',
            style='Inframe.TLabel'
        )
        self.ram_label.grid(row=8, column=1, sticky='e', pady=0)

        ttk.Label(info_frame, text="Free Disk:", anchor='w', style='Inframe.TLabel').grid(
            row=9, column=0, sticky='w', pady=1
        )
        self.disk_label = ttk.Label(
            info_frame,
            text="--",
            anchor='e',
            style='Inframe.TLabel'
        )
        self.disk_label.grid(row=9, column=1, sticky='e', pady=0)

    def _build_devices_panel(self) -> None:
        """Build the USB devices panel in the right column."""
        self.devices_panel = USBDevicesPanel(
            self._main_frame,
            on_connect_toggle=lambda device_id, connect: self._schedule_task(
                self.controller.on_device_connect_toggle(device_id, connect)
            ),
            on_toggle_window=lambda device_id, visible: self._schedule_task(
                self.controller.on_device_toggle_window(device_id, visible)
            ),
        )
        # Right column of main content area
        self.devices_panel.grid(row=0, column=1, sticky="nsew")

    def update_devices_display(self, devices: list, dongles: list) -> None:
        """Update the devices panel with current device list."""
        total_child_devices = sum(len(d.child_devices) for d in dongles)
        self.logger.info(
            "Updating devices display: %d USB devices, %d dongles, %d wireless devices",
            len(devices), len(dongles), total_child_devices
        )
        for d in dongles:
            if d.child_devices:
                self.logger.debug("  Dongle %s has children: %s", d.port, list(d.child_devices.keys()))
        if self.devices_panel:
            self.devices_panel.update_devices(devices, dongles)

    def on_window_visibility_changed(self, device_id: str, visible: bool) -> None:
        """Handle window visibility change for a device.

        This updates the Show/Hide button text in the devices panel.
        """
        if self.devices_panel:
            self.devices_panel.set_window_visible(device_id, visible)

    def _build_logger_frame(self) -> None:
        self.logger_frame = ttk.LabelFrame(self.root, text="System Log", padding="3")
        self.logger_frame.grid(row=2, column=0, sticky=(tk.W, tk.E), padx=5, pady=(0, 5))
        self.logger_frame.columnconfigure(0, weight=1)

        self.logger_text = ScrolledText(
            self.logger_frame,
            height=2,
            wrap=tk.WORD,
            state='disabled'
        )
        Theme.configure_scrolled_text(self.logger_text, readonly=True)
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
        self.logger.debug("System log visibility set to: %s", visible)

    def _setup_log_handler(self) -> None:
        if self.logger_text is None:
            return

        self.log_handler = TextHandler(self.logger_text)
        self.log_handler.setLevel(logging.INFO)

        root_logger = logging.getLogger()
        root_logger.addHandler(self.log_handler)

        self.logger.info("System log display initialized")

    def cleanup_log_handler(self) -> None:
        if self.log_handler:
            self.log_handler.close()
            root_logger = logging.getLogger()
            root_logger.removeHandler(self.log_handler)
            self.log_handler = None

    def _schedule_task(self, coro) -> None:
        task = asyncio.create_task(coro)
        self._pending_tasks.append(task)
        task.add_done_callback(lambda t: self._pending_tasks.remove(t) if t in self._pending_tasks else None)

    def save_window_geometry(self) -> None:
        if not self.root:
            return

        try:
            import re
            geometry_str = self.root.geometry()
            match = re.match(r'(\d+)x(\d+)([\+\-]\d+)([\+\-]\d+)', geometry_str)

            if match:
                width = int(match.group(1))
                height = int(match.group(2))
                x = int(match.group(3))
                y = int(match.group(4))

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

        # Start USB device scanning automatically
        self._schedule_task(self.controller.on_usb_scan_toggle(True))

        self._schedule_task(self.controller.auto_start_modules())

        try:
            await main_loop(self.root)
        except tk.TclError:
            pass
        except Exception as e:
            self.logger.error("UI loop error: %s", e)

        self.logger.info("UI stopped")
