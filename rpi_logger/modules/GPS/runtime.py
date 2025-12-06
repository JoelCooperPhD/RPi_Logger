"""BerryGPS runtime that renders a live offline map preview with telemetry."""

from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import io
import logging
import math
import sqlite3
import time
from collections import deque
import csv
from dataclasses import dataclass
from pathlib import Path
from queue import Queue, Empty
import threading
from typing import Any, Deque, List, Optional, TextIO

from PIL import Image, ImageDraw
from rpi_logger.modules.base.storage_utils import ensure_module_data_dir, module_filename_prefix

try:  # pragma: no cover - optional dependency on headless hosts
    import serial  # type: ignore
    import serial_asyncio  # type: ignore
except Exception as exc:  # pragma: no cover - environment dependent
    serial = None  # type: ignore
    serial_asyncio = None  # type: ignore
    SERIAL_IMPORT_ERROR = exc
else:  # pragma: no cover - normal runtime path
    SERIAL_IMPORT_ERROR = None

try:  # pragma: no cover - tkinter only on GUI hosts
    import tkinter as tk
    from tkinter import ttk
except Exception as exc:  # pragma: no cover - GUI-less host
    tk = None  # type: ignore
    ttk = None  # type: ignore
    TK_IMPORT_ERROR = exc
else:  # pragma: no cover - GUI path
    TK_IMPORT_ERROR = None

try:
    from rpi_logger.core.ui.theme.colors import Colors
    from rpi_logger.core.ui.theme.widgets import RoundedButton
    HAS_THEME = True
except ImportError:
    Colors = None
    RoundedButton = None
    HAS_THEME = False

from rpi_logger.core.logging_utils import ensure_structured_logger
from vmc import ModuleRuntime, RuntimeContext
from vmc.runtime_helpers import BackgroundTaskManager
from rpi_logger.modules.base.preferences import ScopedPreferences

MODULE_DIR = Path(__file__).resolve().parent
DEFAULT_OFFLINE_DB = (MODULE_DIR / "offline_tiles.db").resolve()
TILE_SIZE = 256
GRID_SIZE = 3  # produces a 768x768 view
MIN_ZOOM_LEVEL = 10.0
MAX_ZOOM_LEVEL = 15.0
KMH_PER_KNOT = 1.852
MPH_PER_KNOT = 1.15077945
FIX_QUALITY_DESCRIPTIONS = {
    0: "Invalid",
    1: "GPS fix",
    2: "DGPS fix",
    3: "PPS fix",
    4: "RTK",
    5: "Float RTK",
    6: "Dead reckoning",
    7: "Manual",
    8: "Simulation",
}
FIX_MODE_MAP = {
    1: "No fix",
    2: "2D",
    3: "3D",
}


@dataclass(slots=True)
class GPSFixSnapshot:
    """Lightweight structure that mirrors the latest GPS fix."""

    timestamp: Optional[dt.datetime] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    altitude_m: Optional[float] = None
    speed_knots: Optional[float] = None
    speed_kmh: Optional[float] = None
    speed_mph: Optional[float] = None
    course_deg: Optional[float] = None
    fix_quality: Optional[int] = None
    fix_mode: Optional[str] = None
    satellites_in_use: Optional[int] = None
    satellites_in_view: Optional[int] = None
    hdop: Optional[float] = None
    vdop: Optional[float] = None
    pdop: Optional[float] = None
    fix_valid: bool = False
    last_sentence: Optional[str] = None
    raw_sentence: Optional[str] = None
    connected: bool = False
    error: Optional[str] = None
    last_update_monotonic: float = 0.0

    def age_seconds(self) -> Optional[float]:
        if not self.last_update_monotonic:
            return None
        return max(0.0, time.monotonic() - self.last_update_monotonic)


def _parse_float(value: str | None) -> Optional[float]:
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _parse_int(value: str | None) -> Optional[int]:
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _parse_latlon(value: str | None, direction: str | None, *, is_lat: bool) -> Optional[float]:
    if not value or not direction:
        return None
    try:
        deg_len = 2 if is_lat else 3
        if len(value) < deg_len:
            return None
        degrees = int(value[:deg_len])
        minutes = float(value[deg_len:])
    except ValueError:
        return None
    decimal = degrees + minutes / 60.0
    if direction.upper() in {"S", "W"}:
        decimal *= -1.0
    return decimal


def _parse_hms(value: str | None) -> Optional[dt.time]:
    if not value:
        return None
    raw = value.strip()
    if not raw:
        return None
    main, dot, frac = raw.partition(".")
    main = main.rjust(6, "0")
    try:
        hour = int(main[0:2])
        minute = int(main[2:4])
        second = int(main[4:6])
        micro = int((frac[:6] if dot else "0").ljust(6, "0"))
    except ValueError:
        return None
    try:
        return dt.time(hour, minute, second, micro, tzinfo=dt.timezone.utc)
    except ValueError:
        return None


def _parse_date(value: str | None) -> Optional[dt.date]:
    if not value or len(value) != 6:
        return None
    try:
        day = int(value[0:2])
        month = int(value[2:4])
        year = 2000 + int(value[4:6])
        return dt.date(year, month, day)
    except ValueError:
        return None


def _combine_datetime(date_obj: Optional[dt.date], time_obj: Optional[dt.time], fallback: Optional[dt.datetime]) -> Optional[dt.datetime]:
    if not time_obj:
        return fallback
    date_value = date_obj
    if not date_value and fallback:
        date_value = fallback.date()
    if not date_value:
        date_value = dt.datetime.now(dt.timezone.utc).date()
    return dt.datetime.combine(date_value, time_obj)


class GPSPreviewRuntime(ModuleRuntime):
    """Connect to BerryGPS, parse NMEA data, and render the preview UI."""

    def __init__(self, context: RuntimeContext) -> None:
        self.args = context.args
        scope_fn = getattr(context.model, "preferences_scope", None)
        self.preferences = scope_fn("gps") if callable(scope_fn) else None
        base_logger = ensure_structured_logger(getattr(context, "logger", None), fallback_name="GPSRuntime")
        self.logger = base_logger.getChild("Runtime")
        self.model = context.model
        self.controller = context.controller
        self.view = context.view
        self.display_name = context.display_name
        self.module_dir = context.module_dir
        self._module_subdir = "GPS"
        self._data_dir: Optional[Path] = None
        self._active_trial_number: int = 1

        # Device assignment state - serial params come from assign_device command
        self._device_id: Optional[str] = None
        self._device_assigned = False
        self.serial_port: Optional[str] = None
        self.baud_rate: int = 9600
        self.reconnect_delay = max(1.0, float(getattr(self.args, "reconnect_delay", 3.0)))
        history_limit = max(1, int(getattr(self.args, "nmea_history", 30)))

        self._task_manager = BackgroundTaskManager("GPSRuntimeTasks", self.logger)
        self._shutdown = asyncio.Event()
        self._serial_task: Optional[asyncio.Task] = None
        self._serial_writer = None
        self._serial_error: Optional[str] = None
        self._connection_state = False
        self._recent_sentences: Deque[str] = deque(maxlen=history_limit)
        self._fix = GPSFixSnapshot()
        self._last_known_date: Optional[dt.date] = None
        self._logged_first_fix = False

        self._map_widget: Optional[tk.Widget] = None  # type: ignore[type-var]
        self._map_container: Optional[tk.Widget] = None  # type: ignore[type-var]
        self._controls_overlay: Optional[ttk.Frame] = None
        initial_zoom = float(getattr(self.args, "zoom", 13.0))
        self._current_zoom = self._clamp_zoom(initial_zoom)
        initial_lat = self._get_pref_float("center_lat", float(getattr(self.args, "center_lat", 40.7608)))
        initial_lon = self._get_pref_float("center_lon", float(getattr(self.args, "center_lon", -111.8910)))
        self._current_center = (initial_lat, initial_lon)
        self._current_db: Optional[Path] = None
        self._telemetry_var: Optional[tk.StringVar] = None

        # Telemetry UI state (initialized in _build_telemetry_panel)
        self._status_vars: dict[str, tk.StringVar] = {}
        self._signal_canvas: Optional[tk.Canvas] = None
        self._zoom_label_var: Optional[tk.StringVar] = None

        pref_db = self.preferences.get("offline_db") if self.preferences else None
        self._offline_db = getattr(self.args, "offline_db", pref_db or DEFAULT_OFFLINE_DB)
        self._session_dir: Optional[Path] = None
        self._recording = False
        self._record_path: Optional[Path] = None
        self._record_file: Optional[TextIO] = None
        self._record_writer: Optional[csv.writer] = None
        # Buffered writing with queue
        self._write_queue: Queue[Optional[List[Any]]] = Queue()
        self._writer_thread: Optional[threading.Thread] = None
        self._flush_threshold = 32  # Flush every N rows
        self._pending_rows: List[List[Any]] = []
        self._dropped_records = 0

    # ------------------------------------------------------------------
    # ModuleRuntime interface

    async def start(self) -> None:
        # Bind runtime to view for bidirectional communication
        if self.view:
            bind_runtime = getattr(self.view, "bind_runtime", None)
            if callable(bind_runtime):
                bind_runtime(self)

            if tk is None or ttk is None:
                raise RuntimeError(f"tkinter unavailable: {TK_IMPORT_ERROR}")

        self._log_event(
            "runtime_start",
            mode="gui" if self.view else "headless",
            waiting_for_device=True,
        )

        # Don't start serial connection yet - wait for assign_device command
        # The device will be assigned by the main logger when the UART scanner
        # finds the GPS device at /dev/serial0

    async def shutdown(self) -> None:
        if self._shutdown.is_set():
            return
        self._shutdown.set()

        if self._serial_task and not self._serial_task.done():
            self._serial_task.cancel()
            try:
                await asyncio.wait_for(self._serial_task, timeout=3.0)
            except asyncio.TimeoutError:
                self._log_event("serial_cancel_timeout", level=logging.WARNING)
            except asyncio.CancelledError:
                pass
        self._serial_task = None

        await self._close_serial_writer()

        await self._task_manager.shutdown()

        self._close_recording_file()
        self._recording = False

        if self._map_widget is not None:
            try:
                self._map_widget.destroy()
            except Exception:
                self._log_event("map_widget_destroy_failed", level=logging.DEBUG)
            finally:
                self._map_widget = None

    async def handle_command(self, command: dict[str, Any]) -> bool:
        action = (command.get("command") or "").lower()

        if action == "assign_device":
            return await self._handle_assign_device(command)

        if action == "unassign_device":
            return await self._handle_unassign_device(command)

        if action == "show_window":
            self._handle_show_window()
            return True

        if action == "hide_window":
            self._handle_hide_window()
            return True

        if action == "start_recording":
            await self._start_recording()
            return True

        if action == "stop_recording":
            await self._stop_recording()
            return True

        return False

    async def _handle_assign_device(self, command: dict[str, Any]) -> bool:
        """Handle device assignment from main logger."""
        device_id = command.get("device_id")
        port = command.get("port")
        baudrate = command.get("baudrate", 9600)

        if self._device_assigned:
            self.logger.warning(
                "Device already assigned: %s, rejecting %s",
                self._device_id, device_id
            )
            return False

        self._device_id = device_id
        self.serial_port = port
        self.baud_rate = int(baudrate)
        self._device_assigned = True

        self._log_event(
            "device_assigned",
            device_id=device_id,
            port=port,
            baudrate=baudrate,
        )

        # Build the UI now that device is assigned
        if self.view:
            self.view.set_preview_title(f"{self.display_name} Preview")
            self.view.build_stub_content(self._build_preview_layout)
            telemetry_builder = getattr(self.view, "build_telemetry_content", None)
            if callable(telemetry_builder):
                telemetry_builder(self._build_telemetry_panel)
                configure_sidecar = getattr(self.view, "set_preview_sidecar_minsize", None)
                if callable(configure_sidecar):
                    min_width = int(GRID_SIZE * TILE_SIZE / 2)
                    configure_sidecar(min_width)

            # Notify view of device connection
            on_connected = getattr(self.view, "on_device_connected", None)
            if callable(on_connected):
                on_connected(device_id, port)

        # Now start the serial connection
        if SERIAL_IMPORT_ERROR:
            self._log_event("serial_module_missing", level=logging.ERROR, error=str(SERIAL_IMPORT_ERROR))
            self._set_connection_state(False, error=str(SERIAL_IMPORT_ERROR))
            return True

        self._serial_task = self._task_manager.create(self._serial_worker(), name="GPSSerialWorker")
        return True

    async def _handle_unassign_device(self, command: dict[str, Any]) -> bool:
        """Handle device unassignment."""
        device_id = command.get("device_id")

        if not self._device_assigned or self._device_id != device_id:
            self.logger.debug("Ignoring unassign for non-matching device: %s", device_id)
            return True

        self._log_event("device_unassigned", device_id=device_id)

        # Stop serial task
        if self._serial_task and not self._serial_task.done():
            self._serial_task.cancel()
            try:
                await asyncio.wait_for(self._serial_task, timeout=3.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass
            self._serial_task = None

        await self._close_serial_writer()

        # Notify view
        if self.view:
            on_disconnected = getattr(self.view, "on_device_disconnected", None)
            if callable(on_disconnected):
                on_disconnected(device_id)

        # Reset state
        self._device_id = None
        self._device_assigned = False
        self.serial_port = None
        self._set_connection_state(False)

        return True

    def _handle_show_window(self) -> None:
        """Show the module window."""
        if self.view:
            show_window = getattr(self.view, "show_window", None)
            if callable(show_window):
                show_window()

    def _handle_hide_window(self) -> None:
        """Hide the module window."""
        if self.view:
            hide_window = getattr(self.view, "hide_window", None)
            if callable(hide_window):
                hide_window()

    async def on_session_dir_available(self, path: Path) -> None:
        if self._recording:
            await self._stop_recording()
        self._session_dir = path
        try:
            module_dir = await asyncio.to_thread(ensure_module_data_dir, path, self._module_subdir)
        except Exception:
            module_dir = path / self._module_subdir
            self._log_event(
                "session_dir_prepare_failed",
                level=logging.WARNING,
                path=module_dir,
            )
        self._data_dir = module_dir

    async def _start_recording(self) -> None:
        if self._recording:
            self._log_event("recording_already_active", level=logging.DEBUG, path=self._record_path)
            return
        self._active_trial_number = self._resolve_trial_number()
        record_path = await asyncio.to_thread(self._open_recording_file)
        if record_path:
            self._recording = True
            self._log_event("recording_started", path=record_path)
        else:
            self._log_event("recording_failed", level=logging.ERROR, reason="open_failed")

    async def _stop_recording(self) -> None:
        if not self._recording:
            return
        record_path = self._record_path
        await asyncio.to_thread(self._close_recording_file)
        self._recording = False
        if record_path:
            self._log_event("recording_stopped", path=record_path)

    def _active_session_dir(self) -> Optional[Path]:
        session_dir = self._session_dir or getattr(self.model, "session_dir", None)
        if session_dir:
            return Path(session_dir)
        return None

    def _resolve_record_dir(self) -> Optional[Path]:
        if self._data_dir is not None:
            return self._data_dir
        session_dir = self._active_session_dir()
        if session_dir is None:
            return None
        module_dir = session_dir / self._module_subdir
        module_dir.mkdir(parents=True, exist_ok=True)
        self._data_dir = module_dir
        return module_dir

    def _resolve_trial_number(self) -> int:
        try:
            value = int(getattr(self.model, "trial_number", 0) or 0)
        except (TypeError, ValueError):
            value = 0
        if value <= 0:
            value = 1
        return value

    def _open_recording_file(self) -> Optional[Path]:
        record_dir = self._resolve_record_dir()
        if record_dir is None:
            self._log_event("recording_start_blocked", level=logging.WARNING, reason="missing_session")
            return None
        try:
            record_dir.mkdir(parents=True, exist_ok=True)
            prefix = module_filename_prefix(
                record_dir,
                self._module_subdir,
                self._active_trial_number,
                code="GPS",
            )
            path = record_dir / f"{prefix}.csv"
            handle = path.open("w", encoding="utf-8", newline="")
            writer = csv.writer(handle)
            writer.writerow(
                [
                    "trial",
                    "recorded_at_unix",
                    "gps_timestamp_iso",
                    "latitude_deg",
                    "longitude_deg",
                    "altitude_m",
                    "speed_mps",
                    "speed_kmh",
                    "speed_knots",
                    "speed_mph",
                    "course_deg",
                    "fix_quality",
                    "fix_mode",
                    "fix_valid",
                    "satellites_in_use",
                    "satellites_in_view",
                    "hdop",
                    "pdop",
                    "vdop",
                    "sentence_type",
                    "raw_sentence",
                ]
            )
        except Exception as exc:
            self._log_event("recording_open_error", level=logging.ERROR, error=str(exc), directory=record_dir)
            self._record_writer = None
            self._record_file = None
            return None

        self._record_file = handle
        self._record_writer = writer
        self._record_path = path
        self._dropped_records = 0
        self._pending_rows.clear()
        # Clear queue and start writer thread
        while not self._write_queue.empty():
            try:
                self._write_queue.get_nowait()
            except Empty:
                break
        self._writer_thread = threading.Thread(
            target=self._writer_loop,
            name="GPSWriterThread",
            daemon=True,
        )
        self._writer_thread.start()
        return path

    def _close_recording_file(self) -> None:
        # Signal writer thread to stop
        if self._writer_thread and self._writer_thread.is_alive():
            self._write_queue.put(None)  # Sentinel to stop
            self._writer_thread.join(timeout=5.0)
            if self._writer_thread.is_alive():
                self._log_event("writer_thread_timeout", level=logging.WARNING)
        self._writer_thread = None

        handle = self._record_file
        if handle:
            try:
                handle.close()
            except Exception:
                self._log_event("recording_close_error", level=logging.DEBUG)

        if self._dropped_records > 0:
            self._log_event(
                "recording_dropped_records",
                level=logging.WARNING,
                dropped=self._dropped_records,
            )

        self._record_file = None
        self._record_writer = None
        self._record_path = None
        self._pending_rows.clear()

    def _emit_record(self, update: dict[str, Any]) -> None:
        if not self._recording or not self._record_writer:
            return
        fix = self._fix
        recorded_at_unix = time.time()
        fix_timestamp = fix.timestamp.isoformat() if fix.timestamp else ""
        trial_number = self._active_trial_number
        lat = fix.latitude
        lon = fix.longitude
        altitude = fix.altitude_m
        speed_mps = None
        if fix.speed_knots is not None:
            speed_mps = fix.speed_knots * MPS_PER_KNOT
        elif fix.speed_kmh is not None:
            speed_mps = fix.speed_kmh / 3.6

        row = [
            trial_number,
            recorded_at_unix,
            fix_timestamp,
            lat,
            lon,
            altitude,
            speed_mps,
            fix.speed_kmh,
            fix.speed_knots,
            fix.speed_mph,
            fix.course_deg,
            fix.fix_quality,
            fix.fix_mode or "",
            1 if fix.fix_valid else 0,
            fix.satellites_in_use,
            fix.satellites_in_view,
            fix.hdop,
            fix.pdop,
            fix.vdop,
            update.get("sentence_type"),
            update.get("raw_sentence", ""),
        ]

        # Queue the row for async writing
        try:
            self._write_queue.put_nowait(row)
        except Exception:
            self._dropped_records += 1
            if self._dropped_records % 50 == 1:
                self._log_event(
                    "record_queue_full",
                    level=logging.WARNING,
                    dropped=self._dropped_records,
                )

    def _writer_loop(self) -> None:
        """Background thread that writes queued records to disk."""
        writer = self._record_writer
        handle = self._record_file
        if not writer or not handle:
            return

        buffer: List[List[Any]] = []
        while True:
            try:
                row = self._write_queue.get(timeout=0.5)
            except Empty:
                # Flush pending buffer on timeout
                if buffer:
                    self._flush_buffer(writer, handle, buffer)
                    buffer.clear()
                continue

            if row is None:
                # Sentinel - flush and exit
                if buffer:
                    self._flush_buffer(writer, handle, buffer)
                break

            buffer.append(row)
            if len(buffer) >= self._flush_threshold:
                self._flush_buffer(writer, handle, buffer)
                buffer.clear()

    def _flush_buffer(
        self,
        writer: csv.writer,
        handle: TextIO,
        buffer: List[List[Any]],
    ) -> None:
        """Write buffered rows to disk."""
        try:
            for row in buffer:
                writer.writerow(row)
            handle.flush()
        except Exception:
            self._log_event(
                "buffer_flush_failed",
                level=logging.ERROR,
                rows=len(buffer),
            )
            self.logger.exception("buffer_flush_failed")


    # ------------------------------------------------------------------
    # Serial ingestion

    async def _serial_worker(self) -> None:
        assert serial_asyncio is not None
        while not self._shutdown.is_set():
            try:
                reader, writer = await serial_asyncio.open_serial_connection(
                    url=self.serial_port,
                    baudrate=self.baud_rate,
                )
            except asyncio.CancelledError:
                break
            except Exception as exc:
                event = "serial_error"
                if serial is not None and isinstance(exc, serial.SerialException):
                    event = "serial_exception"
                self._log_event(
                    event,
                    level=logging.WARNING,
                    port=self.serial_port,
                    baud=self.baud_rate,
                    error=str(exc),
                    retry_s=self.reconnect_delay,
                )
                self._set_connection_state(False, error=str(exc))
                await asyncio.sleep(self.reconnect_delay)
                continue

            self._serial_writer = writer
            self._set_connection_state(True, error=None)
            self._log_event("serial_connected", port=self.serial_port, baud=self.baud_rate)

            try:
                while not self._shutdown.is_set():
                    try:
                        line = await asyncio.wait_for(reader.readline(), timeout=1.0)
                    except asyncio.TimeoutError:
                        continue
                    except asyncio.CancelledError:
                        raise

                    if not line:
                        self._log_event("serial_stream_ended", port=self.serial_port, reason="eof")
                        break

                    decoded = line.decode("ascii", errors="ignore").strip()
                    if not decoded or not decoded.startswith("$"):
                        continue
                    self._handle_sentence(decoded)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self._log_event("serial_loop_error", level=logging.WARNING, error=str(exc))
                self._set_connection_state(False, error=str(exc))
            finally:
                await self._close_serial_writer()

            if not self._shutdown.is_set():
                await asyncio.sleep(self.reconnect_delay)

    async def _close_serial_writer(self) -> None:
        writer = self._serial_writer
        if writer is None:
            return
        self._serial_writer = None
        with contextlib.suppress(Exception):
            writer.close()
        if not hasattr(writer, "wait_closed"):
            return
        try:
            await asyncio.wait_for(writer.wait_closed(), timeout=1.0)
        except asyncio.TimeoutError:
            self._log_event("serial_close_timeout", level=logging.DEBUG)
        except Exception:
            self._log_event("serial_close_failed", level=logging.DEBUG)

    def _set_connection_state(self, connected: bool, *, error: Optional[str]) -> None:
        changed = connected != self._connection_state or error != self._serial_error
        self._connection_state = connected
        self._serial_error = error
        self._fix.connected = connected
        self._fix.error = error
        if changed:
            self._log_event("connection_state", connected=connected, error=error)
            self._publish_state(location_changed=False)
            if self.preferences:
                self.preferences.write_sync(
                    {
                        "serial_connected": connected,
                        "serial_last_error": error or "",
                    }
                )

    # ------------------------------------------------------------------
    # NMEA parsing

    def _handle_sentence(self, sentence: str) -> None:
        if not self._validate_checksum(sentence):
            self._log_event("nmea_checksum_invalid", level=logging.DEBUG, sentence=sentence)
            return

        timestamp = dt.datetime.now(dt.timezone.utc).strftime("%H:%M:%S")
        self._recent_sentences.append(f"[{timestamp}] {sentence}")

        parsed = self._parse_sentence(sentence)
        if not parsed:
            return

        self._apply_fix_update(parsed)

    def _validate_checksum(self, sentence: str) -> bool:
        if "*" not in sentence:
            return True
        body, checksum = sentence[1:].split("*", 1)
        calc = 0
        for char in body:
            calc ^= ord(char)
        try:
            expected = int(checksum[:2], 16)
        except ValueError:
            return False
        return calc == expected

    def _parse_sentence(self, sentence: str) -> Optional[dict[str, Any]]:
        payload = sentence[1:]
        if "*" in payload:
            payload = payload.split("*", 1)[0]
        parts = payload.split(",")
        if not parts:
            return None
        header = parts[0]
        message_type = header[-3:].upper()
        handler = getattr(self, f"_parse_{message_type.lower()}", None)
        if not handler:
            return None
        data = handler(parts[1:])
        if data is None:
            return None
        data["sentence_type"] = message_type
        data["raw_sentence"] = sentence
        return data

    def _parse_rmc(self, fields: list[str]) -> Optional[dict[str, Any]]:
        if len(fields) < 9:
            return None
        time_str = fields[0]
        status = (fields[1] or "").upper()
        lat = _parse_latlon(fields[2], fields[3], is_lat=True)
        lon = _parse_latlon(fields[4], fields[5], is_lat=False)
        speed_knots = _parse_float(fields[6])
        course_deg = _parse_float(fields[7])
        date_str = fields[8]
        mode = fields[11] if len(fields) > 11 else None

        date_obj = _parse_date(date_str)
        if date_obj:
            self._last_known_date = date_obj
        time_obj = _parse_hms(time_str)
        timestamp = _combine_datetime(self._last_known_date, time_obj, self._fix.timestamp)

        return {
            "latitude": lat,
            "longitude": lon,
            "speed_knots": speed_knots,
            "course_deg": course_deg,
            "timestamp": timestamp,
            "fix_valid": status == "A",
            "fix_mode": mode or None,
        }

    def _parse_gga(self, fields: list[str]) -> Optional[dict[str, Any]]:
        if len(fields) < 9:
            return None
        time_str = fields[0]
        lat = _parse_latlon(fields[1], fields[2], is_lat=True)
        lon = _parse_latlon(fields[3], fields[4], is_lat=False)
        fix_quality = _parse_int(fields[5])
        satellites = _parse_int(fields[6])
        hdop = _parse_float(fields[7])
        altitude = _parse_float(fields[8])

        time_obj = _parse_hms(time_str)
        timestamp = _combine_datetime(self._last_known_date, time_obj, self._fix.timestamp)

        return {
            "latitude": lat,
            "longitude": lon,
            "fix_quality": fix_quality,
            "satellites_in_use": satellites,
            "hdop": hdop,
            "altitude_m": altitude,
            "timestamp": timestamp,
            "fix_valid": (fix_quality or 0) > 0,
        }

    def _parse_vtg(self, fields: list[str]) -> Optional[dict[str, Any]]:
        if len(fields) < 7:
            return None
        course_deg = _parse_float(fields[0])
        speed_knots = _parse_float(fields[4])
        speed_kmh = _parse_float(fields[6])
        return {
            "course_deg": course_deg,
            "speed_knots": speed_knots,
            "speed_kmh": speed_kmh,
        }

    def _parse_gll(self, fields: list[str]) -> Optional[dict[str, Any]]:
        if len(fields) < 5:
            return None
        lat = _parse_latlon(fields[0], fields[1], is_lat=True)
        lon = _parse_latlon(fields[2], fields[3], is_lat=False)
        time_obj = _parse_hms(fields[4])
        status = (fields[5] or "").upper() if len(fields) > 5 else ""
        timestamp = _combine_datetime(self._last_known_date, time_obj, self._fix.timestamp)
        return {
            "latitude": lat,
            "longitude": lon,
            "timestamp": timestamp,
            "fix_valid": status == "A",
        }

    def _parse_gsa(self, fields: list[str]) -> Optional[dict[str, Any]]:
        if len(fields) < 17:
            return None
        fix_type = _parse_int(fields[1])
        pdop = _parse_float(fields[15]) if len(fields) > 15 else None
        hdop = _parse_float(fields[16]) if len(fields) > 16 else None
        vdop = _parse_float(fields[17]) if len(fields) > 17 else None

        fix_mode = FIX_MODE_MAP.get(fix_type or 0)
        return {
            "fix_mode": fix_mode,
            "pdop": pdop,
            "hdop": hdop,
            "vdop": vdop,
        }

    def _parse_gsv(self, fields: list[str]) -> Optional[dict[str, Any]]:
        if len(fields) < 3:
            return None
        satellites_in_view = _parse_int(fields[2])
        return {"satellites_in_view": satellites_in_view}

    def _apply_fix_update(self, update: dict[str, Any]) -> None:
        fix = self._fix
        location_changed = False

        lat = update.get("latitude")
        lon = update.get("longitude")
        if lat is not None and lon is not None:
            fix.latitude = lat
            fix.longitude = lon
            self._current_center = (lat, lon)
            location_changed = True

        timestamp = update.get("timestamp")
        if timestamp:
            fix.timestamp = timestamp

        fix_quality = update.get("fix_quality")
        if fix_quality is not None:
            fix.fix_quality = fix_quality

        if "fix_mode" in update and update["fix_mode"]:
            fix.fix_mode = update["fix_mode"]

        if "fix_valid" in update:
            fix.fix_valid = bool(update["fix_valid"])

        if "satellites_in_use" in update and update["satellites_in_use"] is not None:
            fix.satellites_in_use = int(update["satellites_in_use"])

        if "satellites_in_view" in update and update["satellites_in_view"] is not None:
            fix.satellites_in_view = int(update["satellites_in_view"])

        if "altitude_m" in update and update["altitude_m"] is not None:
            fix.altitude_m = float(update["altitude_m"])

        if "hdop" in update and update["hdop"] is not None:
            fix.hdop = float(update["hdop"])

        if "pdop" in update and update["pdop"] is not None:
            fix.pdop = float(update["pdop"])

        if "vdop" in update and update["vdop"] is not None:
            fix.vdop = float(update["vdop"])

        if "course_deg" in update and update["course_deg"] is not None:
            fix.course_deg = float(update["course_deg"])

        speed_knots = update.get("speed_knots")
        if speed_knots is not None:
            fix.speed_knots = float(speed_knots)
            fix.speed_kmh = fix.speed_knots * KMH_PER_KNOT
            fix.speed_mph = fix.speed_knots * MPH_PER_KNOT
        elif update.get("speed_kmh") is not None:
            fix.speed_kmh = float(update["speed_kmh"])
            fix.speed_mph = fix.speed_kmh / 1.609344
            fix.speed_knots = fix.speed_kmh / KMH_PER_KNOT

        fix.last_sentence = update.get("sentence_type") or fix.last_sentence
        fix.raw_sentence = update.get("raw_sentence") or fix.raw_sentence
        fix.last_update_monotonic = time.monotonic()

        if fix.fix_valid and not self._logged_first_fix:
            self._logged_first_fix = True
            self._log_event(
                "fix_acquired",
                lat=fix.latitude,
                lon=fix.longitude,
                satellites=fix.satellites_in_use,
                hdop=fix.hdop,
            )

        self._emit_record(update)
        self._publish_state(location_changed=location_changed)

    # ------------------------------------------------------------------
    # UI helpers

    def _build_preview_layout(self, container) -> None:
        assert tk is not None and ttk is not None

        container.columnconfigure(0, weight=1)
        container.rowconfigure(0, weight=1)

        map_frame = ttk.Frame(container)
        map_frame.grid(row=0, column=0, sticky="nsew")
        map_frame.columnconfigure(0, weight=1)
        map_frame.rowconfigure(0, weight=1)

        self._map_container = map_frame

        def delayed_init() -> None:
            self._populate_static_map(map_frame, record_primary=True)

        try:
            container.after(120, delayed_init)
        except Exception:
            delayed_init()

    def _build_telemetry_panel(self, container) -> None:
        assert tk is not None and ttk is not None

        container.columnconfigure(0, weight=1)
        container.rowconfigure(0, weight=1)

        # Create themed outer frame
        if HAS_THEME and Colors is not None:
            outer = tk.Frame(
                container,
                bg=Colors.BG_FRAME,
                highlightbackground=Colors.BORDER,
                highlightcolor=Colors.BORDER,
                highlightthickness=1
            )
        else:
            outer = ttk.Frame(container)
        outer.grid(row=0, column=0, sticky="nsew", padx=2, pady=2)
        outer.columnconfigure(0, weight=1)

        # GPS Status section
        status_lf = ttk.LabelFrame(outer, text="GPS Status")
        status_lf.grid(row=0, column=0, sticky="new", padx=4, pady=(4, 2))
        status_lf.columnconfigure(1, weight=1)

        # Status variables
        self._status_vars = {}

        status_fields = [
            ("Connection", "conn"),
            ("Fix Type", "fix"),
            ("Satellites", "sats"),
        ]
        for i, (label, key) in enumerate(status_fields):
            ttk.Label(status_lf, text=f"{label}:", style='Inframe.TLabel').grid(
                row=i, column=0, sticky="w", padx=5, pady=1
            )
            var = tk.StringVar(value="—")
            self._status_vars[key] = var
            ttk.Label(status_lf, textvariable=var, style='Inframe.TLabel').grid(
                row=i, column=1, sticky="e", padx=5, pady=1
            )

        # Position section
        pos_lf = ttk.LabelFrame(outer, text="Position")
        pos_lf.grid(row=1, column=0, sticky="new", padx=4, pady=2)
        pos_lf.columnconfigure(1, weight=1)

        pos_fields = [
            ("Latitude", "lat"),
            ("Longitude", "lon"),
            ("Altitude", "alt"),
        ]
        for i, (label, key) in enumerate(pos_fields):
            ttk.Label(pos_lf, text=f"{label}:", style='Inframe.TLabel').grid(
                row=i, column=0, sticky="w", padx=5, pady=1
            )
            var = tk.StringVar(value="—")
            self._status_vars[key] = var
            ttk.Label(pos_lf, textvariable=var, style='Inframe.TLabel').grid(
                row=i, column=1, sticky="e", padx=5, pady=1
            )

        # Movement section
        move_lf = ttk.LabelFrame(outer, text="Movement")
        move_lf.grid(row=2, column=0, sticky="new", padx=4, pady=2)
        move_lf.columnconfigure(1, weight=1)

        move_fields = [
            ("Speed", "speed"),
            ("Heading", "heading"),
        ]
        for i, (label, key) in enumerate(move_fields):
            ttk.Label(move_lf, text=f"{label}:", style='Inframe.TLabel').grid(
                row=i, column=0, sticky="w", padx=5, pady=1
            )
            var = tk.StringVar(value="—")
            self._status_vars[key] = var
            ttk.Label(move_lf, textvariable=var, style='Inframe.TLabel').grid(
                row=i, column=1, sticky="e", padx=5, pady=1
            )

        # Quality section
        qual_lf = ttk.LabelFrame(outer, text="Signal Quality")
        qual_lf.grid(row=3, column=0, sticky="new", padx=4, pady=2)
        qual_lf.columnconfigure(1, weight=1)

        qual_fields = [
            ("HDOP", "hdop"),
            ("PDOP", "pdop"),
            ("UTC Time", "utc"),
        ]
        for i, (label, key) in enumerate(qual_fields):
            ttk.Label(qual_lf, text=f"{label}:", style='Inframe.TLabel').grid(
                row=i, column=0, sticky="w", padx=5, pady=1
            )
            var = tk.StringVar(value="—")
            self._status_vars[key] = var
            ttk.Label(qual_lf, textvariable=var, style='Inframe.TLabel').grid(
                row=i, column=1, sticky="e", padx=5, pady=1
            )

        # Signal strength indicator (visual bar)
        sig_lf = ttk.LabelFrame(outer, text="Signal Strength")
        sig_lf.grid(row=4, column=0, sticky="new", padx=4, pady=(2, 4))
        sig_lf.columnconfigure(0, weight=1)

        # Create a canvas for signal strength visualization
        canvas_bg = Colors.BG_DARKER if HAS_THEME and Colors else "#1e1e1e"
        self._signal_canvas = tk.Canvas(
            sig_lf, height=24, bg=canvas_bg, highlightthickness=0
        )
        self._signal_canvas.grid(row=0, column=0, sticky="ew", padx=4, pady=4)

        # Keep legacy telemetry var for compatibility
        self._telemetry_var = tk.StringVar(value="")
        self._update_info_panel()

    def _update_info_panel(self) -> None:
        # Update structured telemetry display
        if hasattr(self, '_status_vars') and self._status_vars:
            self._update_structured_telemetry()

        # Update signal strength visualization
        if hasattr(self, '_signal_canvas') and self._signal_canvas:
            self._update_signal_strength_display()

        # Keep legacy telemetry var updated for compatibility
        if self._telemetry_var:
            self._telemetry_var.set(self._format_telemetry_text())

    def _update_structured_telemetry(self) -> None:
        """Update the structured telemetry display fields."""
        fix = self._fix
        vars_ = self._status_vars

        # Connection status
        if "conn" in vars_:
            if self._connection_state:
                port_short = self.serial_port.split('/')[-1] if self.serial_port else "?"
                vars_["conn"].set(f"Connected ({port_short})")
            else:
                error = self._serial_error or "Disconnected"
                vars_["conn"].set(error[:20])

        # Fix type
        if "fix" in vars_:
            if fix.fix_valid:
                quality = FIX_QUALITY_DESCRIPTIONS.get(fix.fix_quality or 0, "Unknown")
                mode = fix.fix_mode or ""
                if mode:
                    vars_["fix"].set(f"{mode} - {quality}")
                else:
                    vars_["fix"].set(quality)
            else:
                vars_["fix"].set("Searching...")

        # Satellites
        if "sats" in vars_:
            sats_use = fix.satellites_in_use if fix.satellites_in_use is not None else 0
            sats_view = fix.satellites_in_view if fix.satellites_in_view is not None else "?"
            vars_["sats"].set(f"{sats_use} / {sats_view}")

        # Position
        if "lat" in vars_:
            vars_["lat"].set(self._format_coordinate(fix.latitude, "N", "S"))
        if "lon" in vars_:
            vars_["lon"].set(self._format_coordinate(fix.longitude, "E", "W"))
        if "alt" in vars_:
            if fix.altitude_m is not None:
                vars_["alt"].set(f"{fix.altitude_m:.1f} m")
            else:
                vars_["alt"].set("—")

        # Movement
        if "speed" in vars_:
            if fix.speed_kmh is not None:
                vars_["speed"].set(f"{fix.speed_kmh:.1f} km/h")
            else:
                vars_["speed"].set("—")
        if "heading" in vars_:
            if fix.course_deg is not None:
                # Add compass direction
                direction = self._bearing_to_compass(fix.course_deg)
                vars_["heading"].set(f"{fix.course_deg:.0f}° {direction}")
            else:
                vars_["heading"].set("—")

        # Quality
        if "hdop" in vars_:
            if fix.hdop is not None:
                vars_["hdop"].set(f"{fix.hdop:.1f}")
            else:
                vars_["hdop"].set("—")
        if "pdop" in vars_:
            if fix.pdop is not None:
                vars_["pdop"].set(f"{fix.pdop:.1f}")
            else:
                vars_["pdop"].set("—")
        if "utc" in vars_:
            if fix.timestamp:
                vars_["utc"].set(f"{fix.timestamp:%H:%M:%S} UTC")
            else:
                vars_["utc"].set("—")

    def _bearing_to_compass(self, bearing: float) -> str:
        """Convert bearing in degrees to compass direction."""
        directions = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
        index = round(bearing / 45) % 8
        return directions[index]

    def _update_signal_strength_display(self) -> None:
        """Update the signal strength visualization canvas."""
        canvas = self._signal_canvas
        if not canvas or not tk:
            return

        canvas.delete("all")
        fix = self._fix

        # Calculate signal strength based on satellites and HDOP
        sats = fix.satellites_in_use or 0
        hdop = fix.hdop

        # Normalize to 0-100 score
        # Good: 8+ sats, HDOP < 2
        # Fair: 5-7 sats, HDOP 2-5
        # Poor: <5 sats, HDOP > 5
        if not fix.fix_valid or sats == 0:
            strength = 0
        else:
            # Satellite contribution (0-60 points)
            sat_score = min(60, sats * 7.5)
            # HDOP contribution (0-40 points, lower is better)
            if hdop is not None:
                hdop_score = max(0, 40 - (hdop - 1) * 10)
            else:
                hdop_score = 20  # Unknown HDOP gets medium score
            strength = int(sat_score + hdop_score)

        # Draw background
        try:
            width = canvas.winfo_width()
            if width < 10:
                width = 200  # Default width before widget is sized
        except Exception:
            width = 200

        height = 20
        padding = 2

        # Background bar
        bg_color = Colors.BG_INPUT if HAS_THEME and Colors else "#3d3d3d"
        canvas.create_rectangle(padding, padding, width - padding, height, fill=bg_color, outline="")

        # Strength bar with color gradient
        if strength > 0:
            bar_width = int((width - 2 * padding) * strength / 100)
            if strength >= 70:
                color = Colors.SUCCESS if HAS_THEME and Colors else "#2ecc71"
            elif strength >= 40:
                color = Colors.WARNING if HAS_THEME and Colors else "#f39c12"
            else:
                color = Colors.ERROR if HAS_THEME and Colors else "#e74c3c"

            canvas.create_rectangle(
                padding, padding, padding + bar_width, height,
                fill=color, outline=""
            )

        # Draw satellite icons (small rectangles representing satellite bars)
        num_bars = 5
        bar_spacing = (width - 20) // num_bars
        active_bars = min(num_bars, sats // 2) if sats else 0

        for i in range(num_bars):
            bar_x = 10 + i * bar_spacing
            bar_height = 6 + i * 3  # Increasing heights
            bar_y = height - bar_height

            if i < active_bars:
                bar_color = Colors.SUCCESS if HAS_THEME and Colors else "#2ecc71"
            else:
                bar_color = Colors.FG_MUTED if HAS_THEME and Colors else "#6c7a89"

            canvas.create_rectangle(
                bar_x, bar_y, bar_x + 8, height - 2,
                fill=bar_color, outline=""
            )

    def _format_telemetry_text(self) -> str:
        conn_label = "DOWN"
        if self._connection_state:
            conn_label = "OK"
        conn_text = f"CONN:{conn_label}"
        if self._serial_error and not self._connection_state:
            conn_text += f"({self._serial_error})"

        fix = self._fix
        fix_label = "Searching for satellites"
        if fix.fix_valid:
            quality = FIX_QUALITY_DESCRIPTIONS.get(fix.fix_quality or 0, f"Q={fix.fix_quality or 0}")
            mode = fix.fix_mode or ""
            if mode and quality.lower() not in mode.lower():
                fix_label = f"{mode} ({quality})"
            else:
                fix_label = quality
        elif fix.fix_quality is not None:
            fix_label = FIX_QUALITY_DESCRIPTIONS.get(fix.fix_quality, f"Q={fix.fix_quality}")

        lat_text = self._format_coordinate(fix.latitude, "N", "S")
        lon_text = self._format_coordinate(fix.longitude, "E", "W")
        alt_text = f"{fix.altitude_m:.1f}m" if fix.altitude_m is not None else "—"

        speed_text = "—"
        if fix.speed_kmh is not None:
            speed_text = f"{fix.speed_kmh:.1f}km/h"
            if fix.course_deg is not None:
                speed_text += f"@{fix.course_deg:.0f}°"
        sats_use = fix.satellites_in_use if fix.satellites_in_use is not None else 0
        sats_view = fix.satellites_in_view if fix.satellites_in_view is not None else "?"
        sats_text = f"{sats_use}/{sats_view}"

        dop_parts = []
        if fix.hdop is not None:
            dop_parts.append(f"H{fix.hdop:.1f}")
        if fix.pdop is not None:
            dop_parts.append(f"P{fix.pdop:.1f}")
        if fix.vdop is not None:
            dop_parts.append(f"V{fix.vdop:.1f}")
        dop_text = ",".join(dop_parts) if dop_parts else "—"

        if fix.timestamp:
            age = fix.age_seconds()
            age_str = f"{age:.1f}s" if age is not None else ""
            time_text = f"{fix.timestamp:%H:%M:%S}Z {age_str}".strip()
        else:
            time_text = "—"

        sentence = fix.last_sentence or "—"

        parts = [
            conn_text,
            f"PORT:{self.serial_port}",
            f"FIX:{fix_label}",
            f"LAT:{lat_text}",
            f"LON:{lon_text}",
            f"ALT:{alt_text}",
            f"SPD:{speed_text}",
            f"SAT:{sats_text}",
            f"DOP:{dop_text}",
            f"UTC:{time_text}",
            f"SENT:{sentence}",
        ]
        return "\n".join(parts)

    def _format_coordinate(self, value: Optional[float], positive: str, negative: str) -> str:
        if value is None:
            return "—"
        hemisphere = positive if value >= 0 else negative
        return f"{abs(value):.5f}° {hemisphere}"

    def _publish_state(self, *, location_changed: bool) -> None:
        if self.view:
            self._update_info_panel()
            if location_changed:
                self._refresh_preview()

    # ------------------------------------------------------------------
    # Offline map helpers

    def _populate_static_map(self, parent, *, record_primary: bool) -> None:
        center_lat, center_lon = self._current_center
        zoom = self._current_zoom
        offline_db_path, source_label = self._resolve_offline_db()
        if not offline_db_path.exists():
            self._log_event(
                "offline_tiles_missing",
                level=logging.ERROR,
                label=source_label,
                path=offline_db_path,
            )
            if parent.winfo_children():
                for child in parent.winfo_children():
                    child.destroy()
            label = ttk.Label(parent, text="Offline map unavailable")
            label.pack(fill="both", expand=True)
            self._map_widget = label
            return

        label = ttk.Label(parent)
        label.pack(fill="both", expand=True)
        if record_primary:
            self._map_widget = label

        tile_info = self._render_preview_image(label, offline_db_path, center_lat, center_lon, zoom)
        self._current_db = offline_db_path
        self._log_event(
            "offline_tiles_loaded",
            label=source_label,
            path=offline_db_path,
            info=tile_info,
        )
        if self.preferences:
            asyncio.create_task(
                self.preferences.write_async(
                    {
                        "center_lat": center_lat,
                        "center_lon": center_lon,
                        "zoom": zoom,
                        "offline_db": str(self._offline_db),
                    }
                )
            )
        self._place_controls_overlay(parent)

    def _render_preview_image(
        self,
        label: tk.Widget,
        db_path: Path,
        lat: float,
        lon: float,
        zoom: float,
    ) -> str:
        try:
            mosaic_image, tile_info = self._render_tile_mosaic(db_path, lat, lon, zoom)
        except Exception as exc:
            label.configure(text=str(exc))
            label.image = None
            return "mosaic unavailable"

        # Use native Tk PhotoImage with PPM to avoid PIL ImageTk issues on Python 3.13
        ppm_data = io.BytesIO()
        mosaic_image.save(ppm_data, format="PPM")
        tk_image = tk.PhotoImage(data=ppm_data.getvalue())
        label.configure(image=tk_image, text="")
        label.image = tk_image
        return tile_info

    def _render_tile_mosaic(
        self,
        db_path: Path,
        lat: float,
        lon: float,
        zoom: float,
    ) -> tuple[Image.Image, str]:
        zoom_int = max(0, int(round(zoom)))
        display_grid = GRID_SIZE
        load_grid = display_grid + 2
        display_size = display_grid * TILE_SIZE
        load_size = load_grid * TILE_SIZE
        image = Image.new("RGB", (load_size, load_size), "#dcdcdc")

        xtile, ytile = self._latlon_to_tile(lat, lon, zoom_int)
        base_x = int(math.floor(xtile)) - load_grid // 2
        base_y = int(math.floor(ytile)) - load_grid // 2

        total_loaded = 0
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        n = 2 ** zoom_int

        try:
            for gx in range(load_grid):
                for gy in range(load_grid):
                    tx = (base_x + gx) % max(1, n)
                    ty = min(max(base_y + gy, 0), max(n - 1, 0))
                    tile = self._load_tile_image(cur, zoom_int, tx, ty)
                    if tile is None:
                        tile = Image.new("RGB", (TILE_SIZE, TILE_SIZE), "#b9c1c9")
                    else:
                        total_loaded += 1
                    image.paste(tile, (gx * TILE_SIZE, gy * TILE_SIZE))
        finally:
            conn.close()

        tile_center_x = (xtile - base_x) * TILE_SIZE
        tile_center_y = (ytile - base_y) * TILE_SIZE
        crop_left = tile_center_x - (display_size / 2)
        crop_top = tile_center_y - (display_size / 2)
        max_offset = load_size - display_size
        crop_left = int(round(max(0.0, min(max_offset, crop_left))))
        crop_top = int(round(max(0.0, min(max_offset, crop_top))))
        image = image.crop((crop_left, crop_top, crop_left + display_size, crop_top + display_size))

        center_x = tile_center_x - crop_left
        center_y = tile_center_y - crop_top
        self._draw_center_marker(image, center_x, center_y)
        info = f"{total_loaded}/{load_grid * load_grid} tiles (zoom={zoom_int})"
        return image, info

    def _load_tile_image(self, cursor, zoom: int, x: int, y: int) -> Optional[Image.Image]:
        cursor.execute(
            "SELECT tile_image FROM tiles WHERE zoom=? AND x=? AND y=? LIMIT 1",
            (zoom, x, y),
        )
        row = cursor.fetchone()
        if not row:
            return None
        try:
            return Image.open(io.BytesIO(row[0])).convert("RGB")
        except Exception:
            return None

    def _latlon_to_tile(self, lat: float, lon: float, zoom: int) -> tuple[float, float]:
        lat_rad = math.radians(lat)
        n = 2 ** zoom
        xtile = (lon + 180.0) / 360.0 * n
        ytile = (1.0 - math.log(math.tan(lat_rad) + (1 / math.cos(lat_rad))) / math.pi) / 2.0 * n
        return xtile, ytile

    def _draw_center_marker(self, image: Image.Image, x: float, y: float) -> None:
        draw = ImageDraw.Draw(image)
        fix = self._fix

        # Draw crosshair/marker at GPS position
        radius = 8
        marker_color = "#2ecc71" if fix.fix_valid else "#ff4d4f"  # Green if valid, red if searching

        # Outer ring
        draw.ellipse(
            (x - radius, y - radius, x + radius, y + radius),
            outline=marker_color,
            width=3,
        )

        # Inner dot
        inner_radius = 3
        draw.ellipse(
            (x - inner_radius, y - inner_radius, x + inner_radius, y + inner_radius),
            fill=marker_color,
        )

        # Direction arrow (if we have heading data)
        if fix.course_deg is not None and fix.speed_kmh and fix.speed_kmh > 1.0:
            import math
            angle_rad = math.radians(fix.course_deg - 90)  # Convert to math angle
            arrow_len = 20
            end_x = x + arrow_len * math.cos(angle_rad)
            end_y = y + arrow_len * math.sin(angle_rad)

            # Draw direction line
            draw.line((x, y, end_x, end_y), fill=marker_color, width=2)

            # Draw arrowhead
            arrow_size = 6
            left_angle = angle_rad + math.pi * 0.8
            right_angle = angle_rad - math.pi * 0.8
            left_x = end_x + arrow_size * math.cos(left_angle)
            left_y = end_y + arrow_size * math.sin(left_angle)
            right_x = end_x + arrow_size * math.cos(right_angle)
            right_y = end_y + arrow_size * math.sin(right_angle)
            draw.polygon([(end_x, end_y), (left_x, left_y), (right_x, right_y)], fill=marker_color)

        # Draw compass rose in corner
        self._draw_compass_rose(draw, image.width - 40, 40)

        # Draw scale bar
        self._draw_scale_bar(draw, image.width, image.height, int(round(self._current_zoom)))

    def _draw_compass_rose(self, draw: ImageDraw.Draw, cx: float, cy: float) -> None:
        """Draw a compass rose at the given center position."""
        # Colors
        bg_color = "#2b2b2b"
        border_color = "#404055"
        north_color = "#e74c3c"  # Red for North
        text_color = "#ecf0f1"

        radius = 28

        # Background circle
        draw.ellipse(
            (cx - radius, cy - radius, cx + radius, cy + radius),
            fill=bg_color,
            outline=border_color,
            width=2,
        )

        # Cardinal direction markers
        directions = [
            ("N", 0, north_color),
            ("E", 90, text_color),
            ("S", 180, text_color),
            ("W", 270, text_color),
        ]

        for label, angle, color in directions:
            angle_rad = math.radians(angle - 90)  # 0 is up
            # Line from center
            inner_r = 10
            outer_r = radius - 4
            x1 = cx + inner_r * math.cos(angle_rad)
            y1 = cy + inner_r * math.sin(angle_rad)
            x2 = cx + outer_r * math.cos(angle_rad)
            y2 = cy + outer_r * math.sin(angle_rad)
            draw.line((x1, y1, x2, y2), fill=color, width=2 if label == "N" else 1)

        # North indicator arrow
        arrow_len = radius - 6
        arrow_end_y = cy - arrow_len
        draw.polygon(
            [(cx, arrow_end_y), (cx - 5, cy - arrow_len + 10), (cx + 5, cy - arrow_len + 10)],
            fill=north_color,
        )

    def _draw_scale_bar(self, draw: ImageDraw.Draw, image_width: int, image_height: int, zoom: int) -> None:
        """Draw a scale bar in the bottom-left corner of the map."""
        # Calculate meters per pixel at current zoom level
        # At zoom 0, the whole world (40075 km) fits in 256 pixels
        # Each zoom level doubles the resolution
        lat = self._current_center[0]
        meters_per_pixel = 40075016.686 * math.cos(math.radians(lat)) / (256 * (2 ** zoom))

        # Choose a nice round distance for the scale bar
        target_pixels = 100  # Target scale bar width
        target_meters = meters_per_pixel * target_pixels

        # Find the nearest nice round number
        nice_distances = [10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000, 50000]
        scale_meters = min(nice_distances, key=lambda d: abs(d - target_meters))
        scale_pixels = int(scale_meters / meters_per_pixel)

        # Position in bottom-left
        x = 10
        y = image_height - 20

        # Colors
        bg_color = "#2b2b2b"
        bar_color = "#ecf0f1"

        # Background
        draw.rectangle(
            (x - 4, y - 16, x + scale_pixels + 10, y + 6),
            fill=bg_color,
        )

        # Scale bar
        draw.rectangle((x, y - 4, x + scale_pixels, y), fill=bar_color)

        # End caps
        draw.rectangle((x, y - 8, x + 2, y), fill=bar_color)
        draw.rectangle((x + scale_pixels - 2, y - 8, x + scale_pixels, y), fill=bar_color)

        # Label
        if scale_meters >= 1000:
            label = f"{scale_meters // 1000} km"
        else:
            label = f"{scale_meters} m"

        # Draw text (simple, no font loading needed)
        draw.text((x + scale_pixels // 2, y - 12), label, fill=bar_color, anchor="mm")

    def _offline_db_candidates(self, raw_value: Optional[str]) -> list[tuple[str, Path]]:
        candidates: list[tuple[str, Path]] = []
        if raw_value:
            raw_path = Path(raw_value).expanduser()
            if raw_path.is_absolute():
                candidates.append(("cli_abs", raw_path))
            else:
                candidates.append(("cli_cwd", (Path.cwd() / raw_path).resolve()))
                candidates.append(("cli_module", (MODULE_DIR / raw_path).resolve()))
        candidates.append(("module_default", DEFAULT_OFFLINE_DB))
        return candidates

    def _resolve_offline_db(self) -> tuple[Path, str]:
        raw = getattr(self.args, "offline_db", None) or self._offline_db
        candidates = self._offline_db_candidates(str(raw) if raw else None)
        if not candidates:
            return DEFAULT_OFFLINE_DB, "module_default"

        default_label, default_path = candidates[0]
        for label, path in candidates:
            if path.exists():
                return path, label
        return default_path, default_label

    def _clamp_zoom(self, value: float) -> float:
        return max(MIN_ZOOM_LEVEL, min(MAX_ZOOM_LEVEL, float(value)))

    def _adjust_zoom(self, delta: float) -> None:
        new_zoom = self._clamp_zoom(self._current_zoom + float(delta))
        if new_zoom == self._current_zoom:
            return
        self._current_zoom = new_zoom
        # Update zoom level indicator
        if hasattr(self, '_zoom_label_var') and self._zoom_label_var:
            self._zoom_label_var.set(f"z{int(new_zoom)}")
        self._refresh_preview()

    def _refresh_preview(self) -> None:
        if not self._map_widget or not self._current_db:
            return
        lat, lon = self._current_center
        tile_info = self._render_preview_image(
            self._map_widget,
            self._current_db,
            lat,
            lon,
            self._current_zoom,
        )
        self._log_event(
            "preview_updated",
            lat=lat,
            lon=lon,
            zoom=self._current_zoom,
            info=tile_info,
        )

    def _place_controls_overlay(self, parent):
        if tk is None or ttk is None:
            return
        if self._controls_overlay:
            self._controls_overlay.destroy()

        # Create themed overlay frame
        if HAS_THEME and Colors is not None:
            overlay = tk.Frame(
                parent,
                bg=Colors.BG_FRAME,
                highlightbackground=Colors.BORDER,
                highlightcolor=Colors.BORDER,
                highlightthickness=1
            )
        else:
            overlay = ttk.Frame(parent)
        overlay.place(x=8, y=8)

        # Use RoundedButton if available for consistent styling
        if RoundedButton is not None:
            btn_bg = Colors.BG_FRAME if Colors is not None else None
            zoom_out = RoundedButton(
                overlay, text="−", command=lambda: self._adjust_zoom(-1),
                width=36, height=36, style='default', bg=btn_bg
            )
            zoom_out.pack(side="left", padx=2, pady=2)

            zoom_in = RoundedButton(
                overlay, text="+", command=lambda: self._adjust_zoom(1),
                width=36, height=36, style='default', bg=btn_bg
            )
            zoom_in.pack(side="left", padx=(0, 2), pady=2)

            # Add separator
            if HAS_THEME and Colors is not None:
                sep = tk.Frame(overlay, width=1, height=24, bg=Colors.BORDER)
                sep.pack(side="left", padx=4, pady=4)

            # Configure button
            config_btn = RoundedButton(
                overlay, text="⚙", command=self._on_configure_clicked,
                width=36, height=36, style='default', bg=btn_bg
            )
            config_btn.pack(side="left", padx=(0, 2), pady=2)
        else:
            # Fallback to ttk.Button
            ttk.Button(overlay, text="−", width=3, command=lambda: self._adjust_zoom(-1)).pack(side="left", padx=2, pady=2)
            ttk.Button(overlay, text="+", width=3, command=lambda: self._adjust_zoom(1)).pack(side="left", padx=(0, 2), pady=2)
            ttk.Button(overlay, text="⚙", width=3, command=self._on_configure_clicked).pack(side="left", padx=(4, 2), pady=2)

        # Add zoom level indicator
        self._zoom_label_var = tk.StringVar(value=f"z{int(self._current_zoom)}")
        if HAS_THEME and Colors is not None:
            zoom_label = tk.Label(
                overlay,
                textvariable=self._zoom_label_var,
                bg=Colors.BG_FRAME,
                fg=Colors.FG_SECONDARY,
                font=("TkDefaultFont", 9),
                padx=4
            )
        else:
            zoom_label = ttk.Label(overlay, textvariable=self._zoom_label_var, font=("TkDefaultFont", 9))
        zoom_label.pack(side="left", padx=(4, 2))

        self._controls_overlay = overlay

    def _on_configure_clicked(self) -> None:
        """Handle configure button click - delegate to view."""
        if self.view and hasattr(self.view, 'gui') and self.view.gui:
            gui = self.view.gui
            if hasattr(gui, '_on_configure_clicked'):
                gui._on_configure_clicked()

    # ------------------------------------------------------------------
    # Logging helpers

    def _log_event(self, event: str, *, level: int = logging.INFO, **fields: Any) -> None:
        message = f"[{event}]"
        field_parts = []
        for key, value in fields.items():
            if value is None:
                continue
            field_parts.append(f"{key}={self._format_log_value(value)}")
        if field_parts:
            message = f"{message} " + " ".join(field_parts)
        self.logger.log(level, message)

    def _format_log_value(self, value: Any) -> str:
        if isinstance(value, float):
            return f"{value:.4f}".rstrip("0").rstrip(".") or "0"
        if isinstance(value, Path):
            return str(value)
        if isinstance(value, bool):
            return "1" if value else "0"
        return str(value)

    def _get_pref_float(self, key: str, default: float) -> float:
        if self.preferences:
            raw = self.preferences.get(key)
            if raw is not None:
                try:
                    return float(raw)
                except (TypeError, ValueError):
                    self.logger.debug("Invalid stored value for %s: %s", key, raw)
        return float(default)
MPS_PER_KNOT = 0.514444
