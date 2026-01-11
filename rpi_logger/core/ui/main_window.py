
import asyncio
import logging
from collections import deque
from concurrent.futures import Future
from rpi_logger.core.logging_config import LOG_FORMAT, LOG_DATEFMT
from rpi_logger.core.logging_utils import get_module_logger
import tkinter as tk
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText
from pathlib import Path
from typing import Optional
from PIL import Image
import io

from ..logger_system import LoggerSystem
from ..config_manager import get_config_manager
from ..paths import CONFIG_PATH, LOGO_PATH, ICON_PATH
from ..update_checker import check_for_updates
from ..async_bridge import AsyncBridge
from .. import __version__
from .main_controller import MainController
from .timer_manager import TimerManager
from .device_controller import DeviceUIController
from .devices_panel import DevicesPanel
from .theme.styles import Theme
from .theme.widgets import RoundedButton, MetricBar, RecordingBar


class TextHandler(logging.Handler):

    def __init__(self, text_widget: ScrolledText):
        super().__init__()
        self.text_widget = text_widget
        self.max_lines = 500
        self._closed = False
        # Use bounded deque to prevent unbounded memory growth during active logging
        self._pending_after_ids: deque[str] = deque(maxlen=100)
        self.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=LOG_DATEFMT))

    def emit(self, record: logging.LogRecord) -> None:
        if self._closed:
            return
        try:
            msg = self.format(record) + '\n'
            after_id = self.text_widget.after(0, self._append_log, msg)
            self._pending_after_ids.append(after_id)
        except Exception:
            pass  # Silent: logging should never crash the app

    def _append_log(self, msg: str) -> None:
        if self._closed:
            return
        try:
            # Check if widget still exists
            if not self.text_widget.winfo_exists():
                self._closed = True
                return
            self.text_widget.config(state='normal')
            self.text_widget.insert(tk.END, msg)
            self.text_widget.see(tk.END)

            num_lines = int(self.text_widget.index('end-1c').split('.')[0])
            if num_lines > self.max_lines:
                self.text_widget.delete('1.0', f'{num_lines - self.max_lines}.0')

            self.text_widget.config(state='disabled')
        except tk.TclError:
            # Widget was destroyed
            self._closed = True
        except Exception:
            pass  # Silent: logging should never crash the app

    def close(self) -> None:
        self._closed = True
        # Cancel any pending after callbacks
        for after_id in self._pending_after_ids:
            try:
                self.text_widget.after_cancel(after_id)
            except Exception:
                pass  # Widget may already be destroyed
        self._pending_after_ids.clear()
        super().close()


class MainWindow:

    def __init__(self, logger_system: LoggerSystem):
        self.logger = get_module_logger("MainWindow")
        self.logger_system = logger_system

        self.timer_manager = TimerManager()
        self.controller = MainController(logger_system, self.timer_manager)

        # Use device system from logger_system
        self.device_system = logger_system.device_system

        self.root: Optional[tk.Tk] = None
        self.module_vars: dict[str, tk.BooleanVar] = {}

        self.session_button: Optional[RoundedButton] = None
        self.trial_button: Optional[RoundedButton] = None

        self.session_timer_label: Optional[ttk.Label] = None
        self.trial_timer_label: Optional[ttk.Label] = None
        self.trial_counter_label: Optional[ttk.Label] = None
        self.cpu_label: Optional[ttk.Label] = None
        self.ram_label: Optional[ttk.Label] = None
        self.disk_label: Optional[ttk.Label] = None

        # MetricBar widgets for system metrics
        self.cpu_bar: Optional[MetricBar] = None
        self.ram_bar: Optional[MetricBar] = None
        self.disk_bar: Optional[MetricBar] = None

        self.trial_label_var: Optional[tk.StringVar] = None
        self.trial_label_entry: Optional[ttk.Entry] = None

        self.logger_frame: Optional[ttk.LabelFrame] = None
        self.logger_text: Optional[ScrolledText] = None
        self.logger_visible_var: Optional[tk.BooleanVar] = None
        self.log_handler: Optional[logging.Handler] = None

        # Device UI components
        self.devices_panel: Optional[DevicesPanel] = None
        self._main_frame: Optional[ttk.Frame] = None

        # Recording bar (visible during trials)
        self.recording_bar: Optional[RecordingBar] = None

        # Use set for O(1) removal and avoid race condition issues
        self._pending_tasks: set[Future] = set()

        # AsyncBridge for running asyncio in background thread
        self.bridge: Optional[AsyncBridge] = None

        # Geometry tracking for continuous persistence
        self._last_geometry: Optional[str] = None
        self._geometry_save_pending: bool = False
        self._geometry_save_delay_ms: int = 250  # milliseconds

    def build_ui(self) -> None:
        self.root = tk.Tk()
        self.root.title("Logger")

        # Apply theme styles immediately after creating root window
        # This must happen before any ttk widgets are created
        Theme.apply(self.root)

        # Set window icon for taskbar (use 64x64 version for X11 compatibility)
        try:
            icon_64_path = ICON_PATH.parent / "icon_64.png"
            if icon_64_path.exists():
                icon_photo = tk.PhotoImage(file=str(icon_64_path))
                self.root.iconphoto(True, icon_photo)
                self.logger.debug("Set window icon from %s", icon_64_path)
            elif ICON_PATH.exists():
                icon_photo = tk.PhotoImage(file=str(ICON_PATH))
                self.root.iconphoto(True, icon_photo)
                self.logger.debug("Set window icon from %s", ICON_PATH)
        except Exception as e:
            self.logger.warning("Could not set window icon: %s", e)

        # Load main window geometry from instance geometry store
        from rpi_logger.core.instance_geometry_store import get_instance_geometry_store
        geometry_store = get_instance_geometry_store()
        geometry = geometry_store.get("main_window")

        if geometry:
            # Enforce minimum window size to prevent invisible windows
            MIN_WIDTH, MIN_HEIGHT = 400, 300
            width = max(geometry.width, MIN_WIDTH)
            height = max(geometry.height, MIN_HEIGHT)
            if width != geometry.width or height != geometry.height:
                self.logger.warning(
                    "Window size %dx%d below minimum, using %dx%d",
                    geometry.width, geometry.height, width, height
                )
            self.root.geometry(f"{width}x{height}+{geometry.x}+{geometry.y}")
            self.logger.info("Applied saved window geometry: %dx%d+%d+%d", width, height, geometry.x, geometry.y)
        else:
            self.root.geometry("800x600")


        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=0)  # Header
        self.root.rowconfigure(1, weight=1)  # Main content (2-column: left controls, right devices)
        self.root.rowconfigure(2, weight=0)  # Logger frame
        self.root.rowconfigure(3, weight=0)  # Recording bar (hidden by default, at bottom)

        self._build_menubar()
        self._build_header()
        self._build_main_content()
        self._build_devices_panel()
        self._build_logger_frame()
        self._build_recording_bar()

        self.root.protocol("WM_DELETE_WINDOW", self.controller.on_shutdown)

        # Track geometry changes for continuous persistence
        self._last_geometry = self.root.geometry()
        self.root.bind("<Configure>", self._on_configure)

        # Restore window visibility after system sleep/wake
        self.root.bind("<Map>", self._on_window_restore)
        self.root.bind("<FocusIn>", self._on_window_restore)

        self.controller.set_widgets(
            self.root,
            self.module_vars,
            self.session_button,
            self.trial_button,
            self.trial_counter_label,
            self.trial_label_var
        )

        # Wire recording bar to trial lifecycle
        self.controller.set_recording_bar_callbacks(
            on_trial_start=self.show_recording_bar,
            on_trial_stop=self.hide_recording_bar
        )

        # Wire device system to logger_system callbacks
        self._wire_device_system()

        # Set UI root for thread-safe state updates
        self.logger_system.set_ui_root(self.root)

        self.timer_manager.set_labels(
            self.session_timer_label,
            self.trial_timer_label,
            cpu_label=self.cpu_label,
            cpu_bar=self.cpu_bar,
            ram_label=self.ram_label,
            ram_bar=self.ram_bar,
            disk_label=self.disk_label,
            disk_bar=self.disk_bar,
        )

    def _build_menubar(self) -> None:
        menubar = tk.Menu(self.root)
        Theme.configure_menu(menubar)
        self.root.config(menu=menubar)

        # Build File menu (first, leftmost)
        self._build_file_menu(menubar)

        # Build Modules menu for enabling/disabling data logging modules
        self._build_modules_menu(menubar)

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

        help_menu.add_command(
            label="Report Issue",
            command=self.controller.report_issue
        )

        help_menu.add_command(
            label="About",
            command=self.controller.show_about
        )

    def _build_file_menu(self, menubar: tk.Menu) -> None:
        """Build the File menu with session location shortcuts."""
        file_menu = tk.Menu(menubar, tearoff=0)
        Theme.configure_menu(file_menu)
        menubar.add_cascade(label="File", menu=file_menu)

        file_menu.add_command(
            label="Open Last Session Location",
            command=self.controller.open_last_session_location
        )
        file_menu.add_command(
            label="Open Log File",
            command=self.controller.open_log_file
        )
        file_menu.add_separator()
        file_menu.add_command(
            label="Quit",
            command=self.controller.on_shutdown
        )

    def _build_modules_menu(self, menubar: tk.Menu) -> None:
        """Build the Modules menu for enabling/disabling data logging modules."""
        modules_menu = tk.Menu(menubar, tearoff=0)
        Theme.configure_menu(modules_menu)
        menubar.add_cascade(label="Modules", menu=modules_menu)

        for module_info in self.logger_system.get_available_modules():
            is_enabled = self.logger_system.is_module_enabled(module_info.name)
            var = tk.BooleanVar(value=is_enabled)
            self.module_vars[module_info.name] = var

            # Register checkbox with UIStateObserver for state synchronization
            self.logger_system.register_ui_checkbox(module_info.name, var)

            modules_menu.add_checkbutton(
                label=module_info.display_name,
                variable=var,
                command=lambda name=module_info.name: self._schedule_task(
                    self.controller.on_module_menu_toggle(name)
                )
            )

    def _wire_device_system(self) -> None:
        """Wire the device system to application callbacks.

        These callbacks are invoked from UI thread clicks, so they need
        to schedule async work via the bridge.
        """
        # Device connect callback - schedules async work via bridge
        def on_connect_device(device_id: str):
            self.logger.info("Connect request for device: %s", device_id)
            self._schedule_task(self.logger_system.connect_and_start_device(device_id))

        self.device_system.set_on_connect_device(on_connect_device)

        # Device disconnect callback - schedules async work via bridge
        def on_disconnect_device(device_id: str):
            self.logger.info("Disconnect request for device: %s", device_id)
            self._schedule_task(self.logger_system.stop_and_disconnect_device(device_id))

        self.device_system.set_on_disconnect_device(on_disconnect_device)

    def _build_recording_bar(self) -> None:
        self.recording_bar = RecordingBar(self.root)
        # Initially hidden - shown when trial starts
        # grid_remove() keeps the widget but removes from layout

    def show_recording_bar(self) -> None:
        if self.recording_bar:
            self.recording_bar.grid(row=3, column=0, sticky=(tk.W, tk.E))
            self.recording_bar.start()

    def hide_recording_bar(self) -> None:
        if self.recording_bar:
            self.recording_bar.stop()
            self.recording_bar.grid_remove()

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

            # Create a banner frame that matches the logo's background color exactly
            logo_bg_color = '#fcfdf8'  # Exact color from logo background pixels
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
        left_column.rowconfigure(2, weight=1)  # Information cards (expandable)

        # Build left column contents (stacked vertically)
        self._build_session_trial_controls(left_column)
        self._build_info_panel(left_column)

    def _build_session_trial_controls(self, parent: ttk.Frame) -> None:
        # Row 0: Session and Trial buttons side by side, equally weighted
        buttons_frame = ttk.Frame(parent)
        buttons_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N), pady=(0, 8))
        buttons_frame.columnconfigure(0, weight=1)
        buttons_frame.columnconfigure(1, weight=1)

        # Session section with label and button
        session_frame = ttk.Frame(buttons_frame)
        session_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N), padx=(0, 4))
        session_frame.columnconfigure(0, weight=1)

        session_label = ttk.Label(session_frame, text="Session", font=('TkDefaultFont', 10, 'bold'))
        session_label.grid(row=0, column=0, sticky=tk.W, pady=(0, 4))

        self.session_button = RoundedButton(
            session_frame,
            text="Start",
            style='success',
            height=36,
            command=self.controller.on_toggle_session
        )
        self.session_button.grid(row=1, column=0, sticky=(tk.W, tk.E))

        # Trial section with label and button
        trial_frame = ttk.Frame(buttons_frame)
        trial_frame.grid(row=0, column=1, sticky=(tk.W, tk.E, tk.N), padx=(4, 0))
        trial_frame.columnconfigure(0, weight=1)

        trial_label = ttk.Label(trial_frame, text="Trial", font=('TkDefaultFont', 10, 'bold'))
        trial_label.grid(row=0, column=0, sticky=tk.W, pady=(0, 4))

        self.trial_button = RoundedButton(
            trial_frame,
            text="Record",
            style='inactive',
            height=36,
            command=self.controller.on_toggle_trial
        )
        self.trial_button.grid(row=1, column=0, sticky=(tk.W, tk.E))

        # Row 1: Trial label entry
        trial_label_frame = ttk.Frame(parent)
        trial_label_frame.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=(0, 8))
        trial_label_frame.columnconfigure(1, weight=1)

        trial_label_text = ttk.Label(trial_label_frame, text="Trial Label", font=('TkDefaultFont', 10, 'bold'))
        trial_label_text.grid(row=0, column=0, sticky=tk.W, padx=(0, 8))

        config_manager = get_config_manager()
        config = config_manager.read_config(CONFIG_PATH)
        saved_label = config_manager.get_str(config, 'last_trial_label', default='')

        self.trial_label_var = tk.StringVar(value=saved_label)
        self.trial_label_entry = ttk.Entry(
            trial_label_frame,
            textvariable=self.trial_label_var,
            width=20
        )
        self.trial_label_entry.grid(row=0, column=1, sticky=(tk.W, tk.E))

    def _build_info_panel(self, parent: ttk.Frame) -> None:
        # Container for all cards
        cards_frame = ttk.Frame(parent)
        cards_frame.grid(row=2, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        cards_frame.columnconfigure(0, weight=1)

        # === Session Card ===
        session_card = ttk.LabelFrame(cards_frame, text="Session", style='Card.TLabelframe', padding=(8, 4))
        session_card.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 4))
        session_card.columnconfigure(1, weight=1)

        # Trial count (most relevant during recording)
        ttk.Label(session_card, text="Trial", style='Card.TLabel').grid(row=0, column=0, sticky='w', pady=2)
        self.trial_counter_label = ttk.Label(session_card, text="0", style='Card.TLabel')
        self.trial_counter_label.grid(row=0, column=1, sticky='e', pady=2)

        # Recording time (current trial)
        ttk.Label(session_card, text="Recording", style='Card.TLabel').grid(row=1, column=0, sticky='w', pady=2)
        self.trial_timer_label = ttk.Label(session_card, text="--:--:--", style='Card.TLabel')
        self.trial_timer_label.grid(row=1, column=1, sticky='e', pady=2)

        # Session elapsed time
        ttk.Label(session_card, text="Elapsed", style='Card.TLabel').grid(row=2, column=0, sticky='w', pady=2)
        self.session_timer_label = ttk.Label(session_card, text="--:--:--", style='Card.TLabel')
        self.session_timer_label.grid(row=2, column=1, sticky='e', pady=2)

        # === System Card ===
        system_card = ttk.LabelFrame(cards_frame, text="System", style='Card.TLabelframe', padding=(8, 4))
        system_card.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=(0, 0))
        system_card.columnconfigure(1, weight=1)

        # CPU with MetricBar (label left, bar right)
        ttk.Label(system_card, text="CPU", style='Card.TLabel').grid(row=0, column=0, sticky='w', pady=2)
        cpu_frame = ttk.Frame(system_card, style='Card.TFrame')
        cpu_frame.grid(row=0, column=1, sticky='e', pady=2)
        self.cpu_label = ttk.Label(cpu_frame, text="--%", style='Card.TLabel', width=5, anchor='e')
        self.cpu_label.pack(side=tk.LEFT, padx=(0, 6))
        self.cpu_bar = MetricBar(cpu_frame, width=80, height=10, warning_threshold=80, critical_threshold=95)
        self.cpu_bar.pack(side=tk.LEFT)

        # RAM with MetricBar (label left, bar right)
        ttk.Label(system_card, text="RAM", style='Card.TLabel').grid(row=1, column=0, sticky='w', pady=2)
        ram_frame = ttk.Frame(system_card, style='Card.TFrame')
        ram_frame.grid(row=1, column=1, sticky='e', pady=2)
        self.ram_label = ttk.Label(ram_frame, text="--%", style='Card.TLabel', width=5, anchor='e')
        self.ram_label.pack(side=tk.LEFT, padx=(0, 6))
        self.ram_bar = MetricBar(ram_frame, width=80, height=10, warning_threshold=80, critical_threshold=95)
        self.ram_bar.pack(side=tk.LEFT)

        # Disk with MetricBar (label left, bar right, inverted - low is bad)
        ttk.Label(system_card, text="Disk", style='Card.TLabel').grid(row=2, column=0, sticky='w', pady=2)
        disk_frame = ttk.Frame(system_card, style='Card.TFrame')
        disk_frame.grid(row=2, column=1, sticky='e', pady=2)
        self.disk_label = ttk.Label(disk_frame, text="-- GB", style='Card.TLabel', width=9, anchor='e')
        self.disk_label.pack(side=tk.LEFT, padx=(0, 6))
        self.disk_bar = MetricBar(disk_frame, width=80, height=10, max_value=100, warning_threshold=20, critical_threshold=5, invert=True)
        self.disk_bar.pack(side=tk.LEFT)

    def _build_devices_panel(self) -> None:
        """Build the devices panel in the right column using the new architecture."""
        if self.device_system.ui_controller:
            self.devices_panel = DevicesPanel(self._main_frame, self.device_system.ui_controller)
            # Right column of main content area
            self.devices_panel.grid(row=0, column=1, sticky="nsew")
        else:
            self.logger.warning("DeviceUIController not available, devices panel disabled")

    def _build_logger_frame(self) -> None:
        self.logger_frame = ttk.LabelFrame(self.root, text="System Log", padding="3")
        self.logger_frame.grid(row=2, column=0, sticky=(tk.W, tk.E), padx=5, pady=(0, 5))
        self.logger_frame.columnconfigure(0, weight=1)

        self.logger_text = ScrolledText(
            self.logger_frame,
            height=4,
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
        if self.bridge:
            future = self.bridge.run_coroutine(coro)
            self._pending_tasks.add(future)
            future.add_done_callback(lambda f: self._pending_tasks.discard(f))
        else:
            self.logger.warning("Cannot schedule task - bridge not initialized")

    async def _check_for_updates(self) -> None:
        """Check for available updates and show dialog if found."""
        try:
            update_info = await check_for_updates(__version__)
            if update_info and self.root:
                from .dialogs import UpdateAvailableDialog
                UpdateAvailableDialog(self.root, update_info)
        except Exception as e:
            self.logger.debug("Update check failed: %s", e)

    def _on_window_restore(self, event) -> None:
        """Restore window visibility after system sleep/wake."""
        if event.widget != self.root:
            return
        try:
            self.root.deiconify()
            self.root.lift()
        except tk.TclError:
            pass

    def _on_configure(self, event) -> None:
        """Handle window configure events (move/resize) for geometry persistence."""
        # Only respond to root window events, not child widgets
        if event.widget != self.root:
            return

        try:
            from rpi_logger.modules.base.gui_utils import get_frame_position

            # Get current geometry using frame position compensation
            try:
                width, height, x, y = get_frame_position(self.root)
            except ValueError:
                return  # Can't get valid geometry

            current_geometry = f"{width}x{height}+{x}+{y}"

            # Only persist if geometry actually changed
            if current_geometry != self._last_geometry:
                self._last_geometry = current_geometry
                self._schedule_geometry_persist()
        except Exception:
            pass  # Silently ignore errors during geometry tracking

    def _schedule_geometry_persist(self) -> None:
        """Schedule debounced geometry save to avoid excessive writes during drag."""
        if self._geometry_save_pending:
            return  # Already scheduled
        self._geometry_save_pending = True
        if self.root:
            self.root.after(self._geometry_save_delay_ms, self._do_geometry_save)

    def _do_geometry_save(self) -> None:
        """Execute the debounced geometry save."""
        self._geometry_save_pending = False
        self.save_window_geometry()

    def _cancel_geometry_save_handle(self, flush: bool = False) -> None:
        """Cancel any pending geometry save.

        Args:
            flush: If True, save geometry immediately before cancelling
        """
        if flush:
            self.save_window_geometry()
        self._geometry_save_pending = False

    def save_window_geometry(self) -> None:
        """Save main window geometry to instance geometry store."""
        if not self.root:
            return

        try:
            from rpi_logger.core.instance_geometry_store import get_instance_geometry_store
            from rpi_logger.core.window_manager import WindowGeometry
            from rpi_logger.modules.base.gui_utils import get_frame_position

            # Get frame position (compensates for X11 geometry asymmetry)
            # On X11, geometry() may return content position after user moves window,
            # causing windows to drift down on each save/restore cycle.
            try:
                width, height, x, y = get_frame_position(self.root)
            except ValueError as e:
                self.logger.warning("Failed to get frame position: %s", e)
                return

            # Save geometry to instance store
            geometry = WindowGeometry(x=x, y=y, width=width, height=height)
            geometry_store = get_instance_geometry_store()
            geometry_store.set("main_window", geometry)
            self.logger.info("Saved main window geometry: %dx%d+%d+%d", width, height, x, y)

            # Save trial label separately to main config
            if self.trial_label_var:
                trial_label = self.trial_label_var.get()
                config_manager = get_config_manager()
                config_manager.write_config(CONFIG_PATH, {'last_trial_label': trial_label})
        except Exception as e:
            self.logger.error("Error saving window geometry: %s", e, exc_info=True)

    def run(self) -> None:
        """Run the main window with AsyncBridge for background async tasks.

        This runs Tkinter's native mainloop on the main thread while
        asyncio tasks run in a background thread via AsyncBridge.
        This provides true parallelism and keeps the UI responsive.
        """
        self.build_ui()

        # Create and start the AsyncBridge for background async work
        self.bridge = AsyncBridge(self.root)
        self.bridge.start()
        self.logger.info("AsyncBridge started - asyncio running in background thread")

        # Pass bridge to timer manager and controller for thread-safe operations
        self.timer_manager.set_bridge(self.bridge)
        self.controller.set_bridge(self.bridge)

        # Schedule initial async startup tasks
        self._schedule_task(self._async_startup())

        try:
            # Run Tkinter's native mainloop (blocks until window closes)
            self.root.mainloop()
        except tk.TclError:
            pass
        except Exception as e:
            self.logger.error("UI mainloop error: %s", e)
        finally:
            # Stop the AsyncBridge when window closes
            if self.bridge:
                self.bridge.stop()
                self.bridge = None

        self.logger.info("UI stopped")

    async def _async_startup(self) -> None:
        """Perform async initialization after bridge is ready."""
        await self.timer_manager.start_clock()

        # Check for updates (non-blocking, silent on error)
        self._schedule_task(self._check_for_updates())

        # Start USB device scanning automatically
        # IMPORTANT: Must complete before auto_start_modules to ensure
        # instance_manager is ready to track connections
        await self.controller.on_usb_scan_toggle(True)

        # Now start modules - instance manager is ready
        self._schedule_task(self.controller.auto_start_modules())
