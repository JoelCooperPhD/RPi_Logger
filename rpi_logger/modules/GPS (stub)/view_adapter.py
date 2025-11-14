"""Tkinter helpers that render the GPS UI inside the stub view."""

from __future__ import annotations

import io
import logging
import math
import sqlite3
from pathlib import Path
from typing import Iterable, Optional, Sequence

from rpi_logger.core.config_manager import get_config_manager

try:
    import tkinter as tk
    from tkinter import ttk, scrolledtext
except Exception:  # pragma: no cover - defensive import guard
    tk = None  # type: ignore
    ttk = None  # type: ignore
    scrolledtext = None  # type: ignore

try:
    from tkintermapview import TkinterMapView
    from PIL import Image, ImageTk
except Exception as exc:  # pragma: no cover - optional dependency
    TkinterMapView = None  # type: ignore
    Image = None  # type: ignore
    ImageTk = None  # type: ignore
    TKINTERMAPVIEW_ERROR = exc
else:  # pragma: no cover - import success path typically exercised interactively
    TKINTERMAPVIEW_ERROR = None


if TkinterMapView is not None:

    class OfflineFriendlyMapView(TkinterMapView):
        """TkinterMapView variant that tolerates server mismatches when using offline tiles."""

        def request_image(self, zoom: int, x: int, y: int, db_cursor=None):
            if db_cursor is not None and Image is not None and ImageTk is not None:
                try:
                    db_cursor.execute(
                        "SELECT t.tile_image FROM tiles t WHERE t.zoom=? AND t.x=? AND t.y=? AND t.server=?;",
                        (zoom, x, y, self.tile_server),
                    )
                    result = db_cursor.fetchone()

                    if result is None and self.use_database_only:
                        db_cursor.execute(
                            "SELECT t.tile_image FROM tiles t WHERE t.zoom=? AND t.x=? AND t.y=? LIMIT 1;",
                            (zoom, x, y),
                        )
                        result = db_cursor.fetchone()

                    if result is not None:
                        logging.getLogger(__name__).debug(
                            "Offline tile hit (zoom=%s x=%s y=%s server=%s)", zoom, x, y, self.tile_server
                        )
                        image = Image.open(io.BytesIO(result[0]))
                        image_tk = ImageTk.PhotoImage(image)
                        self.tile_image_cache[f"{zoom}{x}{y}"] = image_tk
                        return image_tk
                    elif self.use_database_only:
                        logging.getLogger(__name__).debug(
                            "Offline tile miss (zoom=%s x=%s y=%s)", zoom, x, y
                        )
                        return self.empty_tile_image
                except sqlite3.OperationalError:
                    if self.use_database_only:
                        logging.getLogger(__name__).debug(
                            "Offline tile lookup failed (OperationalError) for zoom=%s x=%s y=%s", zoom, x, y
                        )
                        return self.empty_tile_image
                except Exception as exc:
                    logging.getLogger(__name__).debug(
                        "Offline tile lookup failed (%s) for zoom=%s x=%s y=%s",
                        exc,
                        zoom,
                        x,
                        y,
                    )
                    return self.empty_tile_image

            return super().request_image(zoom, x, y, db_cursor=db_cursor)

else:  # pragma: no cover - fallback definition when tkintermapview is unavailable

    class OfflineFriendlyMapView:  # type: ignore
        pass


class GPSViewAdapter:
    """Populate the stub frame with GPS-specific widgets."""

    def __init__(
        self,
        view,
        *,
        model,
        logger: logging.Logger,
        map_center: tuple[float, float],
        map_zoom: float,
        offline_tiles: Optional[Path],
        disabled_message: Optional[str] = None,
    ) -> None:
        self.view = view
        self.model = model
        self.logger = logger
        self.map_center = map_center
        self.map_zoom = map_zoom
        self.offline_tiles = offline_tiles
        self.disabled_message = disabled_message

        self.root = getattr(view, "root", None)
        self.map_widget: Optional[TkinterMapView] = None  # type: ignore[assignment]
        self.map_status_label: Optional[tk.Widget] = None
        self.map_frame: Optional[ttk.LabelFrame] = None
        self.position_marker = None
        self.path_points: list[tuple[float, float]] = []
        self.path_line = None
        self.show_path_var: Optional[tk.BooleanVar] = None  # type: ignore[assignment]
        self._last_marker_coords: Optional[tuple[float, float]] = None
        self._status_var: Optional[tk.StringVar] = None  # type: ignore[assignment]
        self._fix_var: Optional[tk.StringVar] = None  # type: ignore[assignment]
        self._position_var: Optional[tk.StringVar] = None  # type: ignore[assignment]
        self._speed_var: Optional[tk.StringVar] = None  # type: ignore[assignment]
        self._satellite_var: Optional[tk.StringVar] = None  # type: ignore[assignment]
        self._hdop_var: Optional[tk.StringVar] = None  # type: ignore[assignment]
        self._recording_var: Optional[tk.StringVar] = None  # type: ignore[assignment]
        self._session_var: Optional[tk.StringVar] = None  # type: ignore[assignment]
        self._nmea_widget: Optional[scrolledtext.ScrolledText] = None  # type: ignore[assignment]
        self._nmea_limit = 200
        self._fallback_canvas: Optional[tk.Canvas] = None  # type: ignore[assignment]
        self._fallback_image = None
        self._zoom_var: Optional[tk.StringVar] = None  # type: ignore[assignment]
        self._zoom_controls: Optional[ttk.Frame] = None  # type: ignore[assignment]
        self._zoom_controls_target: Optional[tk.Widget] = None

        self.logger.info(
            "Initializing GPS view adapter (center=%s, zoom=%s, offline_tiles=%s)",
            self.map_center,
            self.map_zoom,
            self.offline_tiles,
        )
        self._build_stub_content()
        self._build_io_content()

        if self.root:
            try:
                self.root.after(150, self._initialize_map_widget)
                self.logger.debug("Scheduled deferred map initialization via root.after")
            except Exception as exc:
                self.logger.warning("Failed to schedule map initialization: %s", exc)

    # ------------------------------------------------------------------
    # Construction helpers

    def _build_stub_content(self) -> None:
        if not self.view or tk is None or ttk is None:
            self.logger.debug("Tkinter unavailable; skipping GPS UI build")
            return

        def builder(parent: tk.Widget) -> None:
            parent.columnconfigure(0, weight=1)
            parent.rowconfigure(0, weight=1)

            map_frame = ttk.LabelFrame(parent, text="Map", padding="6")
            map_frame.grid(row=0, column=0, sticky="nsew")
            map_frame.columnconfigure(0, weight=1)
            map_frame.rowconfigure(0, weight=1)
            self.map_frame = map_frame

            status = ttk.Label(map_frame, text="Initializing map...", anchor="center")
            status.grid(row=0, column=0, sticky="nsew")
            self.map_status_label = status

        self.view.build_stub_content(builder)
        if hasattr(self.view, "set_preview_title"):
            try:
                self.view.set_preview_title("GPS Preview")
            except Exception:
                pass

    def _initialize_map_widget(self) -> None:
        if tk is None or ttk is None or not self.view:
            return
        container = self.map_frame
        if container is None:
            self.logger.warning("No map frame available; cannot initialize map widget")
            return
        if TkinterMapView is None:
            if self.map_status_label:
                text = "tkintermapview not installed"
                if TKINTERMAPVIEW_ERROR:
                    text += f"\n({TKINTERMAPVIEW_ERROR})"
                self.map_status_label.config(text=text)
            self.logger.warning("Cannot build map: tkintermapview missing (%s)", TKINTERMAPVIEW_ERROR)
            return

        kwargs = {"corner_radius": 0}
        if self.offline_tiles:
            try:
                tile_path = Path(self.offline_tiles).expanduser()
                if tile_path.is_file():
                    kwargs.update({"use_database_only": True, "database_path": str(tile_path)})
                    self.logger.info("Using offline tile database %s", tile_path)
                else:
                    self.logger.warning("Offline tiles DB %s not found; falling back to online tiles", tile_path)
            except Exception as exc:
                self.logger.warning("Offline tiles check failed (%s); falling back to online tiles", exc)

        MapCls = OfflineFriendlyMapView if TkinterMapView is not None else None
        if MapCls is None:
            self.logger.error("TkinterMapView unavailable; cannot construct map widget")
            return

        widget = MapCls(container, **kwargs)
        widget.grid(row=0, column=0, sticky="nsew")
        self.map_widget = widget
        try:
            widget.set_tile_server("https://a.tile.openstreetmap.org/{z}/{x}/{y}.png")
        except Exception as exc:
            self.logger.debug("Failed to set tile server (will rely on default): %s", exc)
        try:
            widget.set_zoom(int(self.map_zoom))
            widget.set_position(self.map_center[0], self.map_center[1])
        except Exception as exc:
            self.logger.debug("Failed to set initial map state: %s", exc)

        mode = "offline" if "database_path" in kwargs else "online"
        self.logger.info(
            "Map widget initialized (%s tiles, zoom=%s, impl=%s)",
            mode,
            self.map_zoom,
            type(widget).__name__,
        )
        try:
            widget.update_idletasks()
            self.logger.info(
                "Map widget geometry after init: %sx%s (container %sx%s)",
                widget.winfo_width(),
                widget.winfo_height(),
                container.winfo_width(),
                container.winfo_height(),
            )
        except Exception as exc:
            self.logger.debug("Unable to query map widget geometry: %s", exc)

        try:
            widget.after(750, self._log_map_widget_state)
            widget.after(1500, self._log_tile_cache_state)
        except Exception as exc:
            self.logger.debug("Unable to schedule map state logging: %s", exc)

        self._ensure_zoom_controls(widget)

        if self.map_status_label:
            self.map_status_label.grid_remove()

    def _build_io_content(self) -> None:
        if not self.view or tk is None or ttk is None:
            return

        self._status_var = tk.StringVar(value=self.disabled_message or "Device: searching...")
        self._fix_var = tk.StringVar(value="Fix: no fix")
        self._position_var = tk.StringVar(value="Lat: ---, Lon: --- (Alt --- m)")
        self._speed_var = tk.StringVar(value="Speed: -- km/h | Heading: --°")
        self._satellite_var = tk.StringVar(value="Satellites: --")
        self._hdop_var = tk.StringVar(value="HDOP: --")
        self._recording_var = tk.StringVar(value="Recording: idle")
        self._session_var = tk.StringVar(value="Session log: --")

        def builder(parent: tk.Widget) -> None:
            parent.columnconfigure(0, weight=1)

            status_frame = ttk.LabelFrame(parent, text="Status", padding="6")
            status_frame.grid(row=0, column=0, sticky="ew")
            status_frame.columnconfigure(0, weight=1)

            ttk.Label(status_frame, textvariable=self._status_var, anchor="w").grid(row=0, column=0, sticky="ew")
            ttk.Label(status_frame, textvariable=self._fix_var, anchor="w").grid(row=1, column=0, sticky="ew", pady=(2, 0))
            ttk.Label(status_frame, textvariable=self._position_var, anchor="w").grid(row=2, column=0, sticky="ew", pady=(2, 0))
            ttk.Label(status_frame, textvariable=self._speed_var, anchor="w").grid(row=3, column=0, sticky="ew", pady=(2, 0))

            stats_frame = ttk.Frame(status_frame)
            stats_frame.grid(row=4, column=0, sticky="ew", pady=(4, 0))
            ttk.Label(stats_frame, textvariable=self._satellite_var).grid(row=0, column=0, sticky="w")
            ttk.Label(stats_frame, textvariable=self._hdop_var).grid(row=0, column=1, sticky="w", padx=(12, 0))

            ttk.Label(status_frame, textvariable=self._recording_var, anchor="w").grid(row=5, column=0, sticky="ew", pady=(4, 0))
            ttk.Label(status_frame, textvariable=self._session_var, anchor="w").grid(row=6, column=0, sticky="ew")

            if hasattr(self.view, "add_view_submenu"):
                submenu = self.view.add_view_submenu("GPS Options")
            else:
                submenu = None
            self.show_path_var = tk.BooleanVar(value=True)
            if submenu:
                submenu.add_checkbutton(label="Show Path", variable=self.show_path_var, command=self._apply_path_visibility)
                submenu.add_command(label="Clear Path", command=self._clear_path)

            nmea_frame = ttk.LabelFrame(parent, text="Raw NMEA", padding="4")
            nmea_frame.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
            nmea_frame.columnconfigure(0, weight=1)
            nmea_frame.rowconfigure(0, weight=1)

            text_cls = scrolledtext.ScrolledText if scrolledtext is not None else tk.Text  # type: ignore[assignment]
            text_widget = text_cls(nmea_frame, height=6, wrap=tk.NONE, font=("TkFixedFont", 9))
            text_widget.grid(row=0, column=0, sticky="nsew")
            text_widget.configure(state="disabled")
            self._nmea_widget = text_widget

        self.view.build_io_stub_content(builder)
        self.view.show_io_stub()
        self.logger.info("IO/status panels initialized")

    # ------------------------------------------------------------------
    # Update helpers

    def set_device_status(self, text: str, *, connected: bool, has_fix: bool) -> None:
        if self._status_var is None or self._fix_var is None:
            return
        prefix = "Device: "
        self._status_var.set(f"{prefix}{text}")
        fix_text = "Fix: 3D lock" if has_fix else "Fix: scanning"
        self._fix_var.set(fix_text)
        self.logger.debug("Device status updated (connected=%s, has_fix=%s)", connected, has_fix)

    def set_recording_state(self, recording: bool) -> None:
        if self._recording_var is None:
            return
        self._recording_var.set("Recording: active" if recording else "Recording: idle")
        if recording:
            self._clear_path()
        self.logger.debug("Recording state updated => %s", "active" if recording else "idle")

    def set_session_log_path(self, file_path: Optional[Path]) -> None:
        if self._session_var is None:
            return
        if file_path:
            self._session_var.set(f"Session log: {file_path.name}")
        else:
            self._session_var.set("Session log: --")
        self.logger.debug("Session log indicator updated: %s", file_path)

    def update_gps_data(self, data: dict[str, float], sentences: Sequence[str]) -> None:
        if tk is None:
            return

        lat = float(data.get("latitude", 0.0))
        lon = float(data.get("longitude", 0.0))
        altitude = float(data.get("altitude", 0.0))
        speed = float(data.get("speed_kmh", 0.0))
        heading = float(data.get("heading", 0.0))
        satellites = int(data.get("satellites", 0))
        hdop = float(data.get("hdop", 0.0))
        fix_quality = int(data.get("fix_quality", 0))

        if self._position_var:
            self._position_var.set(f"Lat: {lat:.5f}, Lon: {lon:.5f} (Alt {altitude:.1f} m)")
        if self._speed_var:
            cardinal = self._heading_to_cardinal(heading)
            self._speed_var.set(f"Speed: {speed:.1f} km/h | Heading: {heading:.0f}° ({cardinal})")
        if self._satellite_var:
            self._satellite_var.set(f"Satellites: {satellites}")
        if self._hdop_var:
            self._hdop_var.set(f"HDOP: {hdop:.2f}")

        has_fix = fix_quality > 0
        self.set_device_status("connected" if has_fix else "waiting for fix", connected=bool(fix_quality >= 0), has_fix=has_fix)

        if has_fix:
            self._update_map(lat, lon, recording=self.model.recording)

        self._update_nmea(sentences)
        self.logger.debug(
            "GPS data updated (lat=%.5f, lon=%.5f, fix=%s, satellites=%d)",
            lat,
            lon,
            has_fix,
            satellites,
        )

    def show_error(self, message: str) -> None:
        if self._status_var:
            self._status_var.set(f"Device: {message}")
        if self.map_status_label:
            self.map_status_label.config(text=message)
        self.logger.error("View error: %s", message)

    # ------------------------------------------------------------------
    # Map helpers

    def _update_map(self, lat: float, lon: float, *, recording: bool) -> None:
        if not self.map_widget or not self._valid_coordinates(lat, lon):
            return

        marker_text = "⬤ RECORDING" if recording else "Current Position"
        if self.position_marker:
            try:
                self.position_marker.set_position(lat, lon)
                self.position_marker.set_text(marker_text)
            except Exception:
                self.position_marker = None
        if not self.position_marker:
            try:
                self.position_marker = self.map_widget.set_marker(lat, lon, text=marker_text)
            except Exception as exc:
                self.logger.debug("Failed to create map marker: %s", exc)
                return

        try:
            self.map_widget.set_position(lat, lon)
        except Exception:
            pass
        self._last_marker_coords = (lat, lon)

        if self.show_path_var and self.show_path_var.get() and recording:
            self._append_path_point(lat, lon)
        self.logger.debug("Map updated to %.5f, %.5f (recording=%s)", lat, lon, recording)

    def _append_path_point(self, lat: float, lon: float) -> None:
        if not self._valid_coordinates(lat, lon):
            return

        should_append = False
        if not self.path_points:
            should_append = True
        else:
            last_lat, last_lon = self.path_points[-1]
            if self._distance_meters(last_lat, last_lon, lat, lon) >= 5.0:
                should_append = True

        if not should_append:
            return

        self.path_points.append((lat, lon))
        if len(self.path_points) >= 2 and self.map_widget:
            if self.path_line:
                try:
                    self.path_line.delete()
                except Exception:
                    self.path_line = None
            try:
                self.path_line = self.map_widget.set_path(self.path_points, color="#FF0000", width=3)
            except Exception as exc:
                self.logger.debug("Failed to update path: %s", exc)
            else:
                self.logger.debug("Appended path point (total=%d)", len(self.path_points))

    def _apply_path_visibility(self) -> None:
        if not self.show_path_var or self.show_path_var.get():
            return
        self._clear_path()
        self.logger.debug("Path visibility toggled off; path cleared")

    def _clear_path(self) -> None:
        self.path_points.clear()
        if self.path_line:
            try:
                self.path_line.delete()
            except Exception:
                pass
            self.path_line = None
        self.logger.debug("Path data cleared")

    # ------------------------------------------------------------------
    # Text helpers

    def _update_nmea(self, sentences: Sequence[str]) -> None:
        if not self._nmea_widget:
            return
        display: Iterable[str]
        if sentences:
            display = sentences[-self._nmea_limit :]
        else:
            display = ("Waiting for NMEA sentences...",)
        text = "\n".join(display)
        widget = self._nmea_widget
        try:
            widget.configure(state="normal")
        except Exception:
            pass
        widget.delete("1.0", tk.END)
        if text:
            widget.insert("1.0", text)
        try:
            widget.configure(state="disabled")
        except Exception:
            pass
        widget.see(tk.END)
        self.logger.debug("NMEA panel updated (%d lines)", len(list(display)))

    # ------------------------------------------------------------------
    # Helpers

    @staticmethod
    def _heading_to_cardinal(heading: float) -> str:
        directions = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")
        index = int((heading + 22.5) / 45.0) % len(directions)
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
        radius = 6371000.0
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        d_phi = math.radians(lat2 - lat1)
        d_lambda = math.radians(lon2 - lon1)
        a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return radius * c

    def close(self) -> None:
        self._clear_path()
        if self._fallback_canvas is not None:
            try:
                self._fallback_canvas.destroy()
            except Exception:
                pass
            self._fallback_canvas = None
        self._fallback_image = None
        if self._zoom_controls is not None:
            try:
                self._zoom_controls.destroy()
            except Exception:
                pass
            self._zoom_controls = None
            self._zoom_var = None
        self._zoom_controls_target = None

    def _log_map_widget_state(self) -> None:
        widget = self.map_widget
        if not widget:
            self.logger.warning("Deferred map-state check ran before widget creation")
            return
        container = self.map_frame
        try:
            width = widget.winfo_width()
            height = widget.winfo_height()
            self.logger.info(
                "Map widget state: size=%sx%s, visible=%s, container=%sx%s",
                width,
                height,
                bool(widget.winfo_ismapped()),
                container.winfo_width() if container else "n/a",
                container.winfo_height() if container else "n/a",
            )
        except Exception as exc:
                self.logger.debug("Map state logging failed: %s", exc)

    def _log_tile_cache_state(self) -> None:
        widget = self.map_widget
        if not widget:
            return
        try:
            cache_size = len(getattr(widget, "tile_image_cache", {}))
            self.logger.info(
                "Map tile cache size: %d (use_database_only=%s, server=%s, db=%s)",
                cache_size,
                getattr(widget, "use_database_only", None),
                getattr(widget, "tile_server", None),
                getattr(widget, "database_path", None),
            )
            if cache_size == 0 and self.offline_tiles:
                self.logger.warning("Map widget cache empty; rendering static fallback preview")
                self._render_static_preview()
        except Exception as exc:
            self.logger.debug("Tile cache inspection failed: %s", exc)

    def _render_static_preview(self) -> None:
        if not self.map_frame or tk is None or Image is None or ImageTk is None:
            return
        try:
            if self.map_widget:
                try:
                    self.map_widget.grid_remove()
                except Exception:
                    pass
            if self.map_status_label:
                self.map_status_label.grid_remove()
            tile_size = 256
            grid = 3
            canvas_size = tile_size * grid
            if self._fallback_canvas is None:
                canvas = tk.Canvas(self.map_frame, width=canvas_size, height=canvas_size, bg="#cccccc")
                canvas.grid(row=0, column=0, sticky="nsew")
                self._fallback_canvas = canvas
            else:
                canvas = self._fallback_canvas
                canvas.delete("all")
            self._ensure_zoom_controls(self._fallback_canvas)

            lat, lon = self.map_center
            zoom = int(round(self.map_zoom))

            def _tile_coords(lat_deg: float, lon_deg: float, zoom_level: int) -> tuple[int, int]:
                lat_rad = math.radians(lat_deg)
                n = 2.0 ** zoom_level
                xtile = int((lon_deg + 180.0) / 360.0 * n)
                ytile = int((1.0 - math.log(math.tan(lat_rad) + (1 / math.cos(lat_rad))) / math.pi) / 2.0 * n)
                return xtile, ytile

            cx, cy = _tile_coords(lat, lon, zoom)
            image = Image.new("RGB", (canvas_size, canvas_size), (210, 210, 210))

            conn = sqlite3.connect(str(self.offline_tiles))
            cur = conn.cursor()
            span = grid // 2
            for dx in range(-span, span + 1):
                for dy in range(-span, span + 1):
                    tx, ty = cx + dx, cy + dy
                    cur.execute(
                        "SELECT tile_image FROM tiles WHERE zoom=? AND x=? AND y=? LIMIT 1",
                        (zoom, tx, ty),
                    )
                    row = cur.fetchone()
                    if row:
                        try:
                            tile_img = Image.open(io.BytesIO(row[0])).convert("RGB")
                        except Exception:
                            tile_img = Image.new("RGB", (tile_size, tile_size), (245, 245, 245))
                    else:
                        tile_img = Image.new("RGB", (tile_size, tile_size), (245, 245, 245))
                    px = (dx + span) * tile_size
                    py = (dy + span) * tile_size
                    image.paste(tile_img, (px, py))
            conn.close()

            photo = ImageTk.PhotoImage(image)
            canvas.create_image(canvas_size // 2, canvas_size // 2, image=photo)
            self._fallback_image = photo
            self.logger.info(
                "Static offline preview rendered (zoom=%s, center tiles=%s,%s)",
                zoom,
                cx,
                cy,
            )
        except Exception as exc:
            self.logger.error("Static preview rendering failed: %s", exc, exc_info=True)

    def _ensure_zoom_controls(self, container: tk.Widget) -> None:
        if not tk or not ttk or container is None:
            return
        if self._zoom_controls and self._zoom_controls_target is not container:
            try:
                self._zoom_controls.destroy()
            except Exception:
                pass
            self._zoom_controls = None
            self._zoom_var = None

        if self._zoom_controls:
            try:
                self._zoom_controls.lift()
            except Exception:
                pass
            self._zoom_controls_target = container
            return

        frame = ttk.Frame(container)
        frame.place(relx=1.0, rely=0.0, anchor="ne", x=-12, y=12)
        self._zoom_controls = frame
        self._zoom_controls_target = container
        ttk.Button(frame, text="+", width=3, command=lambda: self._change_zoom(1)).grid(row=0, column=0, pady=1)
        ttk.Button(frame, text="-", width=3, command=lambda: self._change_zoom(-1)).grid(row=1, column=0, pady=1)
        self._zoom_var = tk.StringVar(value=f"Zoom {int(round(self.map_zoom))}")
        ttk.Label(frame, textvariable=self._zoom_var).grid(row=2, column=0, pady=(4, 0))
        try:
            frame.lift()
        except Exception:
            pass

    def _change_zoom(self, delta: float) -> None:
        new_zoom = max(1.0, min(19.0, float(self.map_zoom) + delta))
        if abs(new_zoom - self.map_zoom) < 1e-3:
            return
        self.map_zoom = new_zoom
        self.logger.info("Zoom updated to %.1f", self.map_zoom)
        if self.map_widget:
            try:
                self.map_widget.set_zoom(new_zoom)
            except Exception as exc:
                self.logger.debug("Failed to update map widget zoom: %s", exc)
        else:
            self._render_static_preview()
        if self._zoom_var:
            self._zoom_var.set(f"Zoom {int(round(self.map_zoom))}")
        self._persist_map_zoom()

    def _persist_map_zoom(self) -> None:
        config_path = getattr(self.model, "config_path", None)
        if not config_path:
            return
        try:
            value = int(round(self.map_zoom))
            get_config_manager().write_config(Path(config_path), {"map_zoom": value})
            self.logger.debug("Persisted map_zoom=%s to %s", value, config_path)
        except Exception as exc:
            self.logger.debug("Failed to persist map zoom: %s", exc)
