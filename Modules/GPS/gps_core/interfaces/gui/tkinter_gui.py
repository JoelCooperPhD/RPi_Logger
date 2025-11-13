import logging
import math
from pathlib import Path
from typing import Optional

import tkinter as tk
from tkinter import ttk, scrolledtext

from Modules.base import TkinterGUIBase, TkinterMenuBase
from rpi_logger.cli.common import get_config_float, get_config_int

logger = logging.getLogger("GPS_GUI")


class GPSNMEAPanel:
    """Scrollable view that shows recent raw NMEA sentences."""

    def __init__(self, parent: tk.Misc, max_lines: int = 200):
        self.parent = parent
        self.max_lines = max_lines
        self.frame: Optional[ttk.LabelFrame] = None
        self.text_widget: Optional[scrolledtext.ScrolledText] = None
        self._last_content: str = ''
        self._last_message: str = ''
        self._mode: str = 'message'

    def build(self, row: int = 0, column: int = 0) -> ttk.LabelFrame:
        frame = ttk.LabelFrame(self.parent, text="Raw NMEA", padding="5")
        frame.grid(row=row, column=column, sticky='nsew')
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)

        text_widget = scrolledtext.ScrolledText(
            frame,
            height=4,
            wrap=tk.NONE,
            undo=False,
            font=('TkFixedFont', 9),
            bg='#f5f5f5',
            fg='#333333'
        )
        text_widget.grid(row=0, column=0, sticky='nsew')
        text_widget.config(state='disabled')

        self.frame = frame
        self.text_widget = text_widget
        return frame

    def update(self, sentences: list[str]) -> None:
        if not self.text_widget:
            return

        if self.max_lines > 0 and len(sentences) > self.max_lines:
            sentences = sentences[-self.max_lines:]

        content = '\n'.join(sentences)
        if self._mode == 'data' and content == self._last_content:
            return

        self._mode = 'data'
        self._last_message = ''
        self._set_text(content)

    def clear(self) -> None:
        self._set_text('')

    def show_message(self, message: str) -> None:
        if not self.text_widget:
            return
        if self._mode == 'message' and message == self._last_message:
            return
        self._mode = 'message'
        self._last_message = message
        self._last_content = ''
        self._set_text(message)

    def _set_text(self, text: str) -> None:
        if not self.text_widget:
            return
        self.text_widget.config(state='normal')
        self.text_widget.delete('1.0', tk.END)
        if text:
            self.text_widget.insert('1.0', text)
        self.text_widget.see(tk.END)
        self.text_widget.config(state='disabled')
        self._last_content = text


class GPSLogPanel:
    """Scrollable view that mirrors the active GPS CSV recording."""

    def __init__(self, parent: tk.Misc):
        self.parent = parent
        self.frame: Optional[ttk.LabelFrame] = None
        self.text_widget: Optional[scrolledtext.ScrolledText] = None
        self._current_file: Optional[Path] = None
        self._last_mtime: Optional[float] = None

    def build(self, row: int = 0, column: int = 0) -> ttk.LabelFrame:
        frame = ttk.LabelFrame(self.parent, text="Session Points", padding="5")
        frame.grid(row=row, column=column, sticky='nsew')
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)

        text_widget = scrolledtext.ScrolledText(
            frame,
            height=4,
            wrap=tk.NONE,
            undo=False,
            font=('TkFixedFont', 9),
            bg='#f5f5f5',
            fg='#333333'
        )
        text_widget.grid(row=0, column=0, sticky='nsew')
        text_widget.config(state='disabled')

        self.frame = frame
        self.text_widget = text_widget
        return frame

    def update_from_file(self, file_path: Optional[Path]) -> None:
        if not file_path or not file_path.exists():
            if self._current_file:
                self.clear()
            return

        try:
            mtime = file_path.stat().st_mtime
        except OSError:
            mtime = None

        if self._current_file != file_path or self._last_mtime != mtime:
            try:
                contents = file_path.read_text()
            except OSError:
                contents = ''

            self._current_file = file_path
            self._last_mtime = mtime
            self._set_text(contents)

    def clear(self) -> None:
        self._current_file = None
        self._last_mtime = None
        self._set_text('')

    def _set_text(self, text: str) -> None:
        if not self.text_widget:
            return
        self.text_widget.config(state='normal')
        self.text_widget.delete('1.0', tk.END)
        if text:
            self.text_widget.insert('1.0', text)
        self.text_widget.see(tk.END)
        self.text_widget.config(state='disabled')


class TkinterGUI(TkinterGUIBase, TkinterMenuBase):

    MAP_INIT_DELAY_MS = 100
    LOG_REFRESH_INTERVAL_MS = 2000
    NMEA_REFRESH_INTERVAL_MS = 500
    NMEA_HISTORY_LIMIT = 200

    def __init__(self, gps_system, args):
        self.system = gps_system
        self.args = args

        self.map_widget = None
        self.position_marker = None
        self._last_marker_coords: Optional[tuple[float, float]] = None
        self.path_line = None
        self.path_points: list[tuple[float, float]] = []
        self.last_path_point: Optional[tuple[float, float]] = None

        self.map_zoom = self._get_config_int('map_zoom', 11)
        self.map_center_lat = self._get_config_float('map_center_lat', 40.7608)
        self.map_center_lon = self._get_config_float('map_center_lon', -111.8910)

        self.data_status_var: Optional[tk.StringVar] = None
        self.fix_status_var: Optional[tk.StringVar] = None
        self.position_var: Optional[tk.StringVar] = None
        self.speed_var: Optional[tk.StringVar] = None
        self.satellite_var: Optional[tk.StringVar] = None
        self.hdop_var: Optional[tk.StringVar] = None

        self.show_path_var: Optional[tk.BooleanVar] = None
        self.log_panel: Optional[GPSLogPanel] = None
        self.nmea_panel: Optional[GPSNMEAPanel] = None
        self._latest_log_path: Optional[Path] = None
        self._nmea_snapshot: list[str] = []

        self.initialize_gui_framework(
            title="GPS Monitor",
            default_width=960,
            default_height=720,
            menu_bar_kwargs={'include_sources': False}
        )

        self.root.after(self.MAP_INIT_DELAY_MS, self._initialize_map)
        self.root.after(self.LOG_REFRESH_INTERVAL_MS, self._refresh_log_view)
        self.root.after(self.NMEA_REFRESH_INTERVAL_MS, self._refresh_nmea_view)

    # ------------------------------------------------------------------
    # Base GUI construction
    # ------------------------------------------------------------------
    def _create_widgets(self):
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=0)
        self.root.rowconfigure(2, weight=2)
        self.root.rowconfigure(3, weight=1)
        self.root.rowconfigure(4, weight=1)

        self.nmea_panel = GPSNMEAPanel(self.root, max_lines=self.NMEA_HISTORY_LIMIT)
        nmea_frame = self.nmea_panel.build(row=0, column=0)
        nmea_frame.grid_configure(padx=5, pady=(5, 5), sticky='nsew')
        if self.nmea_panel:
            self.nmea_panel.show_message("Waiting for NMEA sentences...")

        data_frame = self._build_data_panel(self.root)
        data_frame.grid(row=1, column=0, sticky='ew', padx=5, pady=(0, 5))

        self.map_frame = ttk.LabelFrame(self.root, text="Map", padding="5")
        self.map_frame.grid(row=2, column=0, sticky='nsew', padx=5, pady=(0, 5))
        self.map_frame.columnconfigure(0, weight=1)
        self.map_frame.rowconfigure(0, weight=1)

        self.map_status_label = ttk.Label(
            self.map_frame,
            text="Loading map...",
            anchor='center'
        )
        self.map_status_label.grid(row=0, column=0, sticky='nsew')

        self.log_panel = GPSLogPanel(self.root)
        session_frame = self.log_panel.build(row=3, column=0)
        session_frame.grid_configure(padx=5, pady=(0, 5), sticky='nsew')

        self.log_frame = self.create_logger_display(self.root, height=4)
        self.log_frame.configure(text="System Log", padding="5")
        self.log_frame.grid(row=4, column=0, sticky='nsew', padx=5, pady=(0, 5))

        self.nmea_visible_var = self._insert_view_toggle(
            label="Show Raw NMEA",
            widget=nmea_frame,
            config_key="gui_show_gps_nmea_stream",
            menu_index=0,
            default_visible=True,
        )

        self.session_points_visible_var = self._insert_view_toggle(
            label="Show Session Points",
            widget=session_frame,
            config_key="gui_show_gps_session_log",
            menu_index=1,
            default_visible=True,
        )

        self._apply_logger_visibility()

    def set_close_handler(self, handler):
        self.root.protocol("WM_DELETE_WINDOW", handler)

    def update_from_gps(self, data: dict, sentences: list[str]) -> None:
        self.update_gps_display(data)
        self.set_nmea_sentences(sentences)

    def set_nmea_sentences(self, sentences: list[str]) -> None:
        self._nmea_snapshot = list(sentences)
        if not self.nmea_panel:
            return

        if sentences:
            self.nmea_panel.update(sentences)
        else:
            handler = getattr(self.system, 'gps_handler', None)
            if handler and getattr(handler, 'running', False):
                self.nmea_panel.show_message("Waiting for NMEA sentences...")
            elif handler:
                self.nmea_panel.show_message("GPS receiver is idle.")
            else:
                self.nmea_panel.show_message("GPS receiver not connected.")

    def _insert_view_toggle(
        self,
        label: str,
        widget: tk.Widget,
        config_key: str,
        menu_index: int,
        default_visible: bool = True,
    ) -> Optional[tk.BooleanVar]:
        if not hasattr(self, 'view_menu') or not hasattr(self, '_load_view_state'):
            return None

        initial_state = self._load_view_state(config_key, default_visible)
        var = tk.BooleanVar(value=initial_state)

        grid_options = widget.grid_info()
        if grid_options:
            grid_options = grid_options.copy()
            grid_options.pop('in', None)
        else:
            grid_options = {}

        def toggle() -> None:
            visible = var.get()
            if visible:
                widget.grid()
                if grid_options:
                    regrid_kwargs = {}
                    for key, value in grid_options.items():
                        if isinstance(value, str) and value.isdigit():
                            try:
                                regrid_kwargs[key] = int(value)
                                continue
                            except ValueError:
                                pass
                        regrid_kwargs[key] = value
                    widget.grid_configure(**regrid_kwargs)
            else:
                widget.grid_remove()

            if hasattr(self, '_save_view_state'):
                self._save_view_state(config_key, visible)

            try:
                widget.winfo_toplevel().update_idletasks()
            except Exception:
                pass

        try:
            self.view_menu.insert_checkbutton(
                menu_index,
                label=label,
                variable=var,
                command=toggle,
            )
        except Exception as exc:
            logger.debug("Failed to insert view toggle '%s': %s", label, exc)
            return None

        if not initial_state:
            widget.grid_remove()

        return var

    # ------------------------------------------------------------------
    # Panels
    # ------------------------------------------------------------------
    def _build_data_panel(self, parent: ttk.Frame) -> ttk.LabelFrame:
        frame = ttk.LabelFrame(parent, text="Current Fix", padding="5")
        for col in range(4):
            frame.columnconfigure(col, weight=1)

        if self.data_status_var is None:
            self.data_status_var = tk.StringVar(value="No Data")
        if self.fix_status_var is None:
            self.fix_status_var = tk.StringVar(value="No Fix")
        if self.position_var is None:
            self.position_var = tk.StringVar(value="Lat: -- | Lon: -- | Alt: --")
        if self.speed_var is None:
            self.speed_var = tk.StringVar(value="Speed: -- km/h (N)")
        if self.satellite_var is None:
            self.satellite_var = tk.StringVar(value="Satellites: --")
        if self.hdop_var is None:
            self.hdop_var = tk.StringVar(value="HDOP: --")

        ttk.Label(frame, text="Signal:").grid(row=0, column=0, sticky='w')
        self.data_indicator = tk.Label(frame, width=2, height=1, bg='#9e9e9e')
        self.data_indicator.grid(row=0, column=1, sticky='w', padx=(4, 8))
        ttk.Label(frame, textvariable=self.data_status_var).grid(row=0, column=2, columnspan=2, sticky='w')

        ttk.Label(frame, text="Fix:").grid(row=1, column=0, sticky='w')
        self.fix_indicator = tk.Label(frame, width=2, height=1, bg='#b71c1c')
        self.fix_indicator.grid(row=1, column=1, sticky='w', padx=(4, 8))
        ttk.Label(frame, textvariable=self.fix_status_var).grid(row=1, column=2, columnspan=2, sticky='w')

        ttk.Separator(frame, orient='horizontal').grid(row=2, column=0, columnspan=4, sticky='ew', pady=4)

        ttk.Label(frame, text="Coordinates:").grid(row=3, column=0, sticky='w')
        ttk.Label(frame, textvariable=self.position_var).grid(row=3, column=1, columnspan=3, sticky='w')

        ttk.Label(frame, text="Speed & Heading:").grid(row=4, column=0, sticky='w')
        ttk.Label(frame, textvariable=self.speed_var).grid(row=4, column=1, columnspan=3, sticky='w')

        ttk.Label(frame, text="Satellites:").grid(row=5, column=0, sticky='w')
        ttk.Label(frame, textvariable=self.satellite_var).grid(row=5, column=1, sticky='w')

        ttk.Label(frame, text="HDOP:").grid(row=5, column=2, sticky='w')
        ttk.Label(frame, textvariable=self.hdop_var).grid(row=5, column=3, sticky='w')

        return frame

    # ------------------------------------------------------------------
    # Map handling
    # ------------------------------------------------------------------
    def _initialize_map(self) -> None:
        try:
            from tkintermapview import TkinterMapView
        except ImportError:
            self.map_status_label.config(text="tkintermapview not installed")
            logger.error("tkintermapview is required for GPS map rendering")
            return

        offline_tiles = Path(__file__).parent.parent.parent.parent / "offline_tiles.db"
        use_offline = offline_tiles.exists()

        kwargs = {
            'corner_radius': 0,
        }
        if use_offline:
            kwargs.update({
                'use_database_only': True,
                'database_path': str(offline_tiles)
            })

        self.map_widget = TkinterMapView(self.map_frame, **kwargs)

        if not use_offline:
            self.map_widget.set_tile_server("https://a.tile.openstreetmap.org/{z}/{x}/{y}.png")

        self.map_status_label.grid_remove()
        self.map_widget.grid(row=0, column=0, sticky='nsew')

        try:
            self.map_widget.set_zoom(int(self.map_zoom))
            self.map_widget.set_position(self.map_center_lat, self.map_center_lon)
        except Exception as exc:
            logger.error("Failed to set initial map state: %s", exc, exc_info=True)

    def _center_map(self):
        if self.map_widget and self._last_marker_coords:
            lat, lon = self._last_marker_coords
            self.map_widget.set_position(lat, lon)

    # ------------------------------------------------------------------
    # Recording log management
    # ------------------------------------------------------------------
    def _refresh_log_view(self):
        try:
            file_path = self._get_active_log_file()
            if self.log_panel:
                self.log_panel.update_from_file(file_path)
        finally:
            if self.root and self.root.winfo_exists():
                self.root.after(self.LOG_REFRESH_INTERVAL_MS, self._refresh_log_view)

    def _refresh_nmea_view(self) -> None:
        try:
            panel = self.nmea_panel
            if not panel:
                return

            if self._nmea_snapshot:
                panel.update(self._nmea_snapshot)
            else:
                handler = getattr(self.system, 'gps_handler', None)
                sentences: list[str] = []
                if handler and hasattr(handler, 'get_recent_sentences'):
                    try:
                        sentences = handler.get_recent_sentences(self.NMEA_HISTORY_LIMIT)
                    except Exception as exc:
                        logger.debug("Fallback NMEA refresh failed: %s", exc)
                elif handler and hasattr(handler, 'recent_sentences'):
                    sentences = list(handler.recent_sentences)

                if sentences:
                    self._nmea_snapshot = sentences
                    panel.update(sentences)
                else:
                    if handler and getattr(handler, 'running', False):
                        panel.show_message("Waiting for NMEA sentences...")
                    elif handler:
                        panel.show_message("GPS receiver is idle.")
                    else:
                        panel.show_message("GPS receiver not connected.")
        finally:
            if self.root and self.root.winfo_exists():
                self.root.after(self.NMEA_REFRESH_INTERVAL_MS, self._refresh_nmea_view)

    def _get_active_log_file(self) -> Optional[Path]:
        manager = getattr(self.system, 'recording_manager', None)
        if manager and manager.csv_file:
            self._latest_log_path = Path(manager.csv_file)
        return self._latest_log_path

    # ------------------------------------------------------------------
    # GPS data updates
    # ------------------------------------------------------------------
    def update_gps_display(self, data: dict):
        fix_quality = data.get('fix_quality', 0)
        satellites = data.get('satellites', 0)
        lat = data.get('latitude', 0.0)
        lon = data.get('longitude', 0.0)
        alt = data.get('altitude', 0.0)
        speed = data.get('speed_kmh', 0.0)
        heading = data.get('heading', 0.0)
        hdop = data.get('hdop', 0.0)

        has_fix = fix_quality > 0
        self.data_indicator.config(bg='#2e7d32' if has_fix else '#9e9e9e')
        self.data_status_var.set("Receiving Data" if has_fix else "No Data")

        fix_colors = {
            0: ('#b71c1c', "No Fix"),
            1: ('#2e7d32', "GPS Fix"),
            2: ('#1565c0', "DGPS Fix"),
        }
        color, label = fix_colors.get(fix_quality, ('#f9a825', f"Fix {fix_quality}"))
        self.fix_indicator.config(bg=color)
        self.fix_status_var.set(label)

        lat_dir = 'N' if lat >= 0 else 'S'
        lon_dir = 'E' if lon >= 0 else 'W'
        self.position_var.set(
            f"Lat: {abs(lat):.6f}° {lat_dir} | Lon: {abs(lon):.6f}° {lon_dir} | Alt: {alt:.1f} m"
        )

        cardinal = self._heading_to_cardinal(heading)
        self.speed_var.set(f"Speed: {speed:.1f} km/h ({cardinal})")
        self.satellite_var.set(f"Satellites: {satellites}")
        self.hdop_var.set(f"HDOP: {hdop:.2f}")

        if has_fix and self.map_widget:
            self._update_map_position(lat, lon)

    def _update_map_position(self, lat: float, lon: float):
        if not self._valid_coordinates(lat, lon):
            return

        marker_text = "⬤ RECORDING" if self.system.recording else "Current Position"

        if self.position_marker:
            self.position_marker.set_position(lat, lon)
            self.position_marker.set_text(marker_text)
        else:
            self.position_marker = self.map_widget.set_marker(lat, lon, text=marker_text)

        self.map_widget.set_position(lat, lon)
        self._last_marker_coords = (lat, lon)

        if self.system.recording and self.show_path_var and self.show_path_var.get():
            self._update_path(lat, lon)

    def _update_path(self, lat: float, lon: float):
        should_append = False

        if self.last_path_point is None:
            should_append = True
        else:
            previous_lat, previous_lon = self.last_path_point
            distance = self._distance_meters(previous_lat, previous_lon, lat, lon)
            if distance >= 5.0:
                should_append = True

        if not should_append:
            return

        self.path_points.append((lat, lon))
        self.last_path_point = (lat, lon)

        if len(self.path_points) >= 2:
            if self.path_line:
                self.path_line.delete()
            self.path_line = self.map_widget.set_path(self.path_points, color='#FF0000', width=3)

    # ------------------------------------------------------------------
    # Controls
    # ------------------------------------------------------------------
    def _on_path_toggle(self):
        if not self.show_path_var:
            return
        if not self.show_path_var.get():
            self._clear_path()

    def sync_recording_state(self):
        if self.system.recording:
            self.root.title("GPS Monitor - ⬤ RECORDING")
            self._clear_path()
        else:
            self.root.title("GPS Monitor")

        self._update_session_log_path()

        if self.position_marker:
            marker_text = "⬤ RECORDING" if self.system.recording else "Current Position"
            self.position_marker.set_text(marker_text)

    def _update_session_log_path(self):
        manager = getattr(self.system, 'recording_manager', None)
        if manager and manager.csv_file:
            self._latest_log_path = Path(manager.csv_file)

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------
    def _clear_path(self):
        self.path_points.clear()
        self.last_path_point = None
        if self.path_line:
            self.path_line.delete()
            self.path_line = None

    @staticmethod
    def _heading_to_cardinal(heading: float) -> str:
        directions = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW']
        index = int((heading + 22.5) / 45.0) % 8
        return directions[index]

    @staticmethod
    def _valid_coordinates(lat: float, lon: float) -> bool:
        if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
            return False
        if abs(lat) < 1e-6 and abs(lon) < 1e-6:
            return False
        return True

    @staticmethod
    def _distance_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        radius = 6371000
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        delta_phi = math.radians(lat2 - lat1)
        delta_lambda = math.radians(lon2 - lon1)

        a = math.sin(delta_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return radius * c

    def _get_config_int(self, key: str, default: int) -> int:
        config = getattr(self.system, 'config', {}) or {}
        return get_config_int(config, key, default)

    def _get_config_float(self, key: str, default: float) -> float:
        config = getattr(self.system, 'config', {}) or {}
        return get_config_float(config, key, default)

    # ------------------------------------------------------------------
    # View menu population
    # ------------------------------------------------------------------
    def populate_module_menus(self):
        if not hasattr(self, 'view_menu'):
            return

        self.view_menu.add_separator()

        self.show_path_var = tk.BooleanVar(value=False)
        self.view_menu.add_checkbutton(
            label="Show Path",
            variable=self.show_path_var,
            command=self._on_path_toggle
        )

        self.view_menu.add_command(
            label="Clear Path",
            command=self._clear_path
        )

        self.view_menu.add_command(
            label="Center Map",
            command=self._center_map
        )

    # ------------------------------------------------------------------
    # Shutdown and persistence
    # ------------------------------------------------------------------
    def handle_window_close(self):
        try:
            self.save_window_geometry_to_config()
        except Exception as exc:
            logger.error("Failed to save window geometry: %s", exc, exc_info=True)

        if self.map_widget:
            try:
                self._save_map_state()
            except Exception as exc:
                logger.error("Failed to save map state: %s", exc, exc_info=True)

    def save_window_geometry_to_config(self):
        from Modules.base import gui_utils
        config_path = gui_utils.get_module_config_path(Path(__file__))
        gui_utils.save_window_geometry(self.root, config_path)

    def _save_map_state(self):
        if not self.map_widget:
            return

        from Modules.base import ConfigLoader, gui_utils

        current_zoom = int(self.map_widget.zoom)
        lat, lon = self.map_widget.get_position()
        config_path = gui_utils.get_module_config_path(Path(__file__))

        ConfigLoader.update_config_values(
            config_path,
            {
                'map_zoom': current_zoom,
                'map_center_lat': lat,
                'map_center_lon': lon,
            }
        )
