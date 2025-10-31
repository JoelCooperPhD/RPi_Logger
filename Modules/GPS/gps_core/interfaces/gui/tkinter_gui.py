import logging
import tkinter as tk
from tkinter import ttk
from pathlib import Path
import math
import asyncio

logger = logging.getLogger("GPS_GUI")


class TkinterGUI:

    def __init__(self, gps2_system, args):
        logger.info("=== GPS2 GUI INIT START ===")
        self.system = gps2_system
        self.args = args

        logger.info("Creating Tkinter root window")
        self.root = tk.Tk()
        self.root.title("GPS2 Map Viewer")
        logger.info("Root window created: %s", self.root)

        self._close_handler = None
        self.map_widget = None
        self.map_initialized = False
        self.position_marker = None
        self.path_line = None
        self.path_points = []
        self.last_path_point = None
        self.show_path = False

        self._load_map_settings()

        logger.info("Calling _setup_window()")
        self._setup_window()

        logger.info("Calling _create_widgets()")
        self._create_widgets()

        logger.info("Scheduling map initialization in 100ms")
        self.root.after(100, self._initialize_map_sync)
        logger.info("=== GPS2 GUI INIT COMPLETE ===")

    def _load_map_settings(self):
        from gps_core import load_config_file
        from cli_utils import get_config_int, get_config_float

        config = load_config_file()

        self.map_zoom = get_config_int(config, 'map_zoom', 11)
        self.map_center_lat = get_config_float(config, 'map_center_lat', 40.7608)
        self.map_center_lon = get_config_float(config, 'map_center_lon', -111.8910)

        logger.info("Loaded map settings: zoom=%d, lat=%.4f, lon=%.4f",
                   self.map_zoom, self.map_center_lat, self.map_center_lon)

    def _setup_window(self):
        if hasattr(self.args, 'window_geometry') and self.args.window_geometry:
            self.root.geometry(self.args.window_geometry)
        else:
            self.root.geometry("900x700")

    def _create_widgets(self):
        main_frame = ttk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        info_frame = ttk.Frame(main_frame)
        info_frame.pack(fill=tk.X, pady=(0, 5))

        data_frame = ttk.Frame(info_frame)
        data_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.data_canvas = tk.Canvas(data_frame, width=15, height=15, bg='gray')
        self.data_canvas.pack(side=tk.LEFT, padx=5)

        self.data_label = ttk.Label(data_frame, text="No Data", font=("Courier", 10))
        self.data_label.pack(side=tk.LEFT, padx=5)

        self.fix_canvas = tk.Canvas(data_frame, width=15, height=15, bg='red')
        self.fix_canvas.pack(side=tk.LEFT, padx=5)

        self.fix_label = ttk.Label(data_frame, text="No Fix", font=("Courier", 10))
        self.fix_label.pack(side=tk.LEFT, padx=10)

        self.position_label = ttk.Label(data_frame, text="Lat: -- | Lon: -- | Alt: --", font=("Courier", 10))
        self.position_label.pack(side=tk.LEFT, padx=10)

        self.speed_label = ttk.Label(data_frame, text="Speed: 0.0 km/h", font=("Courier", 10))
        self.speed_label.pack(side=tk.LEFT, padx=10)

        self.sat_label = ttk.Label(data_frame, text="Sats: 0", font=("Courier", 10))
        self.sat_label.pack(side=tk.LEFT, padx=10)

        controls_frame = ttk.Frame(info_frame)
        controls_frame.pack(side=tk.RIGHT)

        self.path_button = ttk.Button(
            controls_frame,
            text="Show Path",
            command=self._toggle_path_display
        )
        self.path_button.pack(side=tk.LEFT, padx=5)

        self.record_button = ttk.Button(
            controls_frame,
            text="Start Recording",
            command=self._on_record_click
        )
        self.record_button.pack(side=tk.LEFT, padx=5)

        self.map_frame = ttk.LabelFrame(main_frame, text="Map", padding="5")
        self.map_frame.pack(fill=tk.BOTH, expand=True)

        self.status_label = ttk.Label(
            self.map_frame,
            text="Initializing map...",
            font=("Arial", 14),
            anchor=tk.CENTER
        )
        self.status_label.pack(fill=tk.BOTH, expand=True)

    def _initialize_map_sync(self):
        logger.info("=== MAP INITIALIZATION START ===")
        logger.info("Map frame: %s", self.map_frame)
        logger.info("Map frame exists: %s", self.map_frame.winfo_exists())

        try:
            logger.info("Importing TkinterMapView...")
            from tkintermapview import TkinterMapView
            logger.info("TkinterMapView imported successfully")

            module_dir = Path(__file__).parent.parent.parent.parent
            offline_tiles_path = module_dir / "offline_tiles.db"
            logger.info("Module dir: %s", module_dir)
            logger.info("Offline tiles path: %s", offline_tiles_path)
            logger.info("Offline tiles exists: %s", offline_tiles_path.exists())

            if offline_tiles_path.exists():
                logger.info("Found offline tiles: %s", offline_tiles_path)
                logger.info("Creating map widget in OFFLINE mode...")
                logger.info("Map frame for widget: %s", self.map_frame)
                self.map_widget = TkinterMapView(
                    self.map_frame,
                    corner_radius=0,
                    use_database_only=True,
                    database_path=str(offline_tiles_path)
                )
                logger.info("Map widget created: %s", self.map_widget)
                logger.info("Map will use offline tiles only")
            else:
                logger.info("No offline tiles found, using ONLINE mode")
                logger.info("Creating map widget...")
                self.map_widget = TkinterMapView(self.map_frame, corner_radius=0)
                logger.info("Map widget created: %s", self.map_widget)
                logger.info("Setting tile server...")
                self.map_widget.set_tile_server("https://a.tile.openstreetmap.org/{z}/{x}/{y}.png")
                logger.info("Tile server set")

            logger.info("Hiding status label...")
            self.status_label.pack_forget()
            logger.info("Status label hidden")

            logger.info("Packing map widget with fill=BOTH, expand=True...")
            self.map_widget.pack(fill=tk.BOTH, expand=True)
            logger.info("Map widget packed")

            logger.info("Setting zoom to %d...", self.map_zoom)
            try:
                self.map_widget.set_zoom(self.map_zoom)
                logger.info("Zoom set successfully")
            except Exception as e:
                logger.error("Failed to set zoom: %s", e, exc_info=True)

            logger.info("Setting position to: %.4f, %.4f", self.map_center_lat, self.map_center_lon)
            try:
                self.map_widget.set_position(self.map_center_lat, self.map_center_lon)
                logger.info("Position set successfully")
            except Exception as e:
                logger.error("Failed to set position: %s", e, exc_info=True)

            logger.info("Forcing map update...")
            try:
                self.root.update_idletasks()
                self.root.update()
                logger.info("Map update complete")
            except tk.TclError as e:
                logger.error("Tcl error during map update: %s", e, exc_info=True)
            except Exception as e:
                logger.error("Error during map update: %s", e, exc_info=True)

            self.map_initialized = True
            mode = "OFFLINE" if offline_tiles_path.exists() else "ONLINE"
            logger.info("=== MAP INITIALIZATION COMPLETE! [%s mode] ===", mode)
            logger.info("map_initialized flag: %s", self.map_initialized)
            logger.info("map_widget: %s", self.map_widget)

            logger.info("=== POST-INIT MAP DIAGNOSTICS ===")
            logger.info("Map widget running state: %s", self.map_widget.running)
            logger.info("Map widget zoom: %.2f", self.map_widget.zoom)
            logger.info("Task queue size: %d", len(self.map_widget.image_load_queue_tasks))
            logger.info("Result queue size: %d", len(self.map_widget.image_load_queue_results))
            logger.info("Tile cache size: %d", len(self.map_widget.tile_image_cache))
            logger.info("Canvas tile array: %dx%d",
                       len(self.map_widget.canvas_tile_array) if self.map_widget.canvas_tile_array else 0,
                       len(self.map_widget.canvas_tile_array[0]) if self.map_widget.canvas_tile_array and len(self.map_widget.canvas_tile_array) > 0 else 0)
            logger.info("Number of background threads: %d", len(self.map_widget.image_load_thread_pool))

            self.root.after(100, self._monitor_map_queues)

        except ImportError as e:
            logger.error("tkintermapview not available: %s", e)
            self.status_label.config(text="Error: tkintermapview not installed")
        except Exception as e:
            logger.error("Map initialization failed: %s", e, exc_info=True)
            self.status_label.config(text=f"Error: {str(e)}")

    def update_gps_display(self, data: dict):
        lat = data.get('latitude', 0.0)
        lon = data.get('longitude', 0.0)
        alt = data.get('altitude', 0.0)
        speed = data.get('speed_kmh', 0.0)
        heading = data.get('heading', 0.0)
        satellites = data.get('satellites', 0)
        fix_quality = data.get('fix_quality', 0)
        hdop = data.get('hdop', 99.9)

        if not hasattr(self, '_update_count'):
            self._update_count = 0
        self._update_count += 1

        if self._update_count % 20 == 0:
            logger.info("GPS display update #%d: fix=%d, lat=%.6f, lon=%.6f, sats=%d",
                       self._update_count, fix_quality, lat, lon, satellites)

        if fix_quality > 0:
            self.data_canvas.config(bg='green')
            self.data_label.config(text="Data OK")
        else:
            self.data_canvas.config(bg='gray')
            self.data_label.config(text="No Data")

        lat_dir = 'N' if lat >= 0 else 'S'
        lon_dir = 'E' if lon >= 0 else 'W'

        self.position_label.config(
            text=f"Lat: {abs(lat):.6f}° {lat_dir} | Lon: {abs(lon):.6f}° {lon_dir} | Alt: {alt:.1f}m"
        )

        cardinal = self._heading_to_cardinal(heading)
        self.speed_label.config(text=f"Speed: {speed:.1f} km/h ({cardinal})")

        self.sat_label.config(text=f"Sats: {satellites}")

        if fix_quality == 0:
            fix_color = 'red'
            fix_text = "No Fix"
        elif fix_quality == 1:
            fix_color = 'green'
            fix_text = "GPS Fix"
        elif fix_quality == 2:
            fix_color = 'blue'
            fix_text = "DGPS Fix"
        else:
            fix_color = 'yellow'
            fix_text = f"Fix {fix_quality}"

        self.fix_canvas.config(bg=fix_color)
        self.fix_label.config(text=fix_text)

        if self._update_count % 20 == 0:
            logger.info("Map check: map_initialized=%s, fix_quality=%s, will_update_map=%s",
                       self.map_initialized, fix_quality, (self.map_initialized and fix_quality > 0))

        if self.map_initialized and fix_quality > 0:
            if self._update_count % 20 == 0:
                logger.info("Calling _update_map_position(%.6f, %.6f)", lat, lon)
            self._update_map_position(lat, lon)
        elif not self.map_initialized:
            if self._update_count % 20 == 0:
                logger.warning("Map not initialized - cannot update position")
        elif fix_quality == 0:
            if self._update_count % 20 == 0:
                logger.warning("No GPS fix - cannot update map position")

    def _monitor_map_queues(self):
        if not self.map_initialized or not self.map_widget:
            return

        if not hasattr(self, '_queue_monitor_count'):
            self._queue_monitor_count = 0
        self._queue_monitor_count += 1

        try:
            tasks = len(self.map_widget.image_load_queue_tasks)
            results = len(self.map_widget.image_load_queue_results)
            cache = len(self.map_widget.tile_image_cache)
            running = self.map_widget.running

            logger.info("=== MAP QUEUE MONITOR #%d ===", self._queue_monitor_count)
            logger.info("Widget running: %s", running)
            logger.info("Tasks queued: %d", tasks)
            logger.info("Results pending: %d", results)
            logger.info("Tiles cached: %d", cache)

            if tasks > 0:
                logger.warning("Tasks are queued but may not be processing!")
                if results > 0:
                    logger.warning("Results are ready but not being applied to canvas!")

            if self._queue_monitor_count <= 10:
                self.root.after(1000, self._monitor_map_queues)
            else:
                logger.info("=== QUEUE MONITORING COMPLETE (stopped after 10 iterations) ===")

        except Exception as e:
            logger.error("Queue monitoring error: %s", e, exc_info=True)

    def _update_map_position(self, lat: float, lon: float):
        if not hasattr(self, '_map_update_count'):
            self._map_update_count = 0
        self._map_update_count += 1

        if self._map_update_count % 10 == 0:
            logger.info("Map update #%d: lat=%.6f, lon=%.6f", self._map_update_count, lat, lon)

        if not self._validate_coordinates(lat, lon):
            logger.warning("Invalid coordinates: lat=%.6f, lon=%.6f", lat, lon)
            return

        logger.debug("Updating map position to: %.6f, %.6f", lat, lon)
        marker_text = "⬤ RECORDING" if self.system.recording else "Current Position"

        if self.position_marker:
            logger.debug("Updating existing marker position")
            self.position_marker.set_position(lat, lon)
            self.position_marker.set_text(marker_text)
        else:
            logger.info("Creating new position marker at %.6f, %.6f", lat, lon)
            self.position_marker = self.map_widget.set_marker(lat, lon, text=marker_text)
            logger.info("Position marker created: %s", self.position_marker)

        logger.debug("Centering map on position")
        self.map_widget.set_position(lat, lon)

        if self.system.recording and self.show_path:
            self._update_path(lat, lon)

    def _update_path(self, lat: float, lon: float):
        should_add_point = False

        if self.last_path_point is None:
            should_add_point = True
        else:
            last_lat, last_lon = self.last_path_point
            distance = self._calculate_distance(last_lat, last_lon, lat, lon)
            if distance >= 5.0:
                should_add_point = True

        if should_add_point:
            self.path_points.append((lat, lon))
            self.last_path_point = (lat, lon)

            if len(self.path_points) >= 2:
                if self.path_line:
                    self.path_line.delete()

                self.path_line = self.map_widget.set_path(
                    self.path_points,
                    color='#FF0000',
                    width=3
                )

    def _toggle_path_display(self):
        self.show_path = not self.show_path

        if self.show_path:
            self.path_button.config(text="Hide Path")
        else:
            self.path_button.config(text="Show Path")
            if self.path_line:
                self.path_line.delete()
                self.path_line = None

    def _clear_path(self):
        self.path_points = []
        self.last_path_point = None
        if self.path_line:
            self.path_line.delete()
            self.path_line = None

    def _validate_coordinates(self, lat: float, lon: float) -> bool:
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return False
        if lat == 0.0 and lon == 0.0:
            return False
        return True

    def _calculate_distance(self, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        R = 6371000
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        delta_phi = math.radians(lat2 - lat1)
        delta_lambda = math.radians(lon2 - lon1)

        a = math.sin(delta_phi/2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda/2)**2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

        return R * c

    def _heading_to_cardinal(self, heading: float) -> str:
        directions = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW']
        index = int((heading + 22.5) / 45.0) % 8
        return directions[index]

    def sync_recording_state(self):
        if self.system.recording:
            self.record_button.config(text="Stop Recording", state=tk.NORMAL)
            self.root.title("GPS2 - ⬤ RECORDING")
            self._clear_path()
        else:
            self.record_button.config(text="Start Recording", state=tk.NORMAL)
            self.root.title("GPS2 Map Viewer")

        if self.position_marker:
            marker_text = "⬤ RECORDING" if self.system.recording else "Current Position"
            self.position_marker.set_text(marker_text)

    def _on_record_click(self):
        """Handle record button click - schedules async operation"""
        loop = asyncio.get_event_loop()
        if self.system.recording:
            loop.create_task(self._stop_recording_async())
        else:
            loop.create_task(self._start_recording_async())

    async def _start_recording_async(self):
        await self.system.start_recording()
        self.root.after(0, self.sync_recording_state)

    async def _stop_recording_async(self):
        await self.system.stop_recording()
        self.root.after(0, self.sync_recording_state)

    def handle_window_close(self):
        logger.info("GPS2 cleanup for window close")

        current_geometry = self.root.geometry()
        logger.info("Current window geometry: %s", current_geometry)

        try:
            self.save_window_geometry_to_config()
            logger.info("Saved window geometry to config")
        except Exception as e:
            logger.error("Failed to save window geometry: %s", e, exc_info=True)

        if self.map_widget and self.map_initialized:
            try:
                self.save_map_settings_to_config()
                logger.info("Saved map settings to config")
            except Exception as e:
                logger.error("Failed to save map settings: %s", e, exc_info=True)

    def save_window_geometry_to_config(self):
        from pathlib import Path
        from Modules.base import gui_utils
        config_path = gui_utils.get_module_config_path(Path(__file__))
        gui_utils.save_window_geometry(self.root, config_path)

    def save_map_settings_to_config(self):
        from pathlib import Path
        from Modules.base import gui_utils, ConfigLoader

        current_zoom = int(self.map_widget.zoom)
        current_lat, current_lon = self.map_widget.get_position()

        logger.info("Current map state: zoom=%d, lat=%.4f, lon=%.4f",
                   current_zoom, current_lat, current_lon)

        config_path = gui_utils.get_module_config_path(Path(__file__))

        updates = {
            'map_zoom': current_zoom,
            'map_center_lat': current_lat,
            'map_center_lon': current_lon,
        }

        ConfigLoader.update_config_values(config_path, updates)
        logger.info("Updated map settings in config")
