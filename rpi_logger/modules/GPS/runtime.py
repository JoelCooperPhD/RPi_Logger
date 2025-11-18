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
from typing import Any, Deque, Optional, TextIO

from PIL import Image, ImageDraw, ImageTk

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

from vmc import ModuleRuntime, RuntimeContext
from vmc.runtime_helpers import BackgroundTaskManager

MODULE_DIR = Path(__file__).resolve().parent
DEFAULT_OFFLINE_DB = (MODULE_DIR / "offline_tiles.db").resolve()
TILE_SIZE = 256
GRID_SIZE = 3  # produces a 768x768 view
MIN_ZOOM_LEVEL = 10.0
MAX_ZOOM_LEVEL = 16.0
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
        base_logger = context.logger or logging.getLogger("GPSRuntime")
        self.logger = base_logger.getChild("Runtime")
        self.model = context.model
        self.controller = context.controller
        self.view = context.view
        self.display_name = context.display_name
        self.module_dir = context.module_dir

        self.serial_port = str(getattr(self.args, "serial_port", "/dev/serial0"))
        self.baud_rate = int(getattr(self.args, "baud_rate", 9600))
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
        self._current_center = (
            float(getattr(self.args, "center_lat", 40.7608)),
            float(getattr(self.args, "center_lon", -111.8910)),
        )
        self._current_db: Optional[Path] = None
        self._telemetry_var: Optional[tk.StringVar] = None

        self._offline_db = getattr(self.args, "offline_db", DEFAULT_OFFLINE_DB)
        self._session_dir: Optional[Path] = None
        self._recording = False
        self._record_path: Optional[Path] = None
        self._record_file: Optional[TextIO] = None
        self._record_writer: Optional[csv.writer] = None

    # ------------------------------------------------------------------
    # ModuleRuntime interface

    async def start(self) -> None:
        if self.view:
            if tk is None or ttk is None:
                raise RuntimeError(f"tkinter unavailable: {TK_IMPORT_ERROR}")
            self.view.set_preview_title(f"{self.display_name} Preview")
            self.view.build_stub_content(self._build_preview_layout)
            self.view.set_io_stub_title(f"{self.display_name} Telemetry")
            self.view.build_io_stub_content(self._build_io_panel)
            self.view.show_io_stub()

        self._log_event(
            "runtime_start",
            mode="gui" if self.view else "headless",
            port=self.serial_port,
            baud=self.baud_rate,
            reconnect_s=self.reconnect_delay,
            offline_db=self._offline_db,
        )

        if SERIAL_IMPORT_ERROR:
            self._log_event("serial_module_missing", level=logging.ERROR, error=str(SERIAL_IMPORT_ERROR))
            self._set_connection_state(False, error=str(SERIAL_IMPORT_ERROR))
            return

        self._serial_task = self._task_manager.create(self._serial_worker(), name="GPSSerialWorker")

    async def shutdown(self) -> None:
        if self._shutdown.is_set():
            return
        self._shutdown.set()

        if self._serial_task and not self._serial_task.done():
            self._serial_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._serial_task
        self._serial_task = None

        writer = self._serial_writer
        if writer:
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()
            self._serial_writer = None

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
        if action == "start_recording":
            await self._start_recording()
            return True
        if action == "stop_recording":
            await self._stop_recording()
            return True
        return False

    async def on_session_dir_available(self, path: Path) -> None:
        if self._recording:
            await self._stop_recording()
        self._session_dir = path
        try:
            await asyncio.to_thread((path / "GPS").mkdir, parents=True, exist_ok=True)
        except Exception:
            self._log_event("session_dir_prepare_failed", level=logging.WARNING, path=path / "GPS")

    async def _start_recording(self) -> None:
        if self._recording:
            self._log_event("recording_already_active", level=logging.DEBUG, path=self._record_path)
            return
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

    def _extract_session_token(self, session_dir: Path) -> str:
        name = session_dir.name
        if "_" in name:
            return name.split("_", 1)[1]
        return dt.datetime.utcnow().strftime("%Y%m%d_%H%M%S")

    def _resolve_record_dir(self) -> tuple[Optional[Path], Optional[str]]:
        session_dir = self._active_session_dir()
        if session_dir is None:
            return None, None
        token = self._extract_session_token(session_dir)
        return session_dir / "GPS", token

    def _open_recording_file(self) -> Optional[Path]:
        record_dir, token = self._resolve_record_dir()
        if record_dir is None or not token:
            self._log_event("recording_start_blocked", level=logging.WARNING, reason="missing_session")
            return None
        try:
            record_dir.mkdir(parents=True, exist_ok=True)
            path = record_dir / f"{token}_GPS.csv"
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
        return path

    def _close_recording_file(self) -> None:
        handle = self._record_file
        if handle:
            try:
                handle.close()
            except Exception:
                self._log_event("recording_close_error", level=logging.DEBUG)
        self._record_file = None
        self._record_writer = None
        self._record_path = None

    def _emit_record(self, update: dict[str, Any]) -> None:
        writer = self._record_writer
        if not writer:
            return
        fix = self._fix
        recorded_at_unix = time.time()
        fix_timestamp = fix.timestamp.isoformat() if fix.timestamp else ""
        trial_number = int(getattr(self.model, "trial_number", 0) or 0)
        lat = fix.latitude
        lon = fix.longitude
        altitude = fix.altitude_m
        speed_mps = None
        if fix.speed_knots is not None:
            speed_mps = fix.speed_knots * MPS_PER_KNOT
        elif fix.speed_kmh is not None:
            speed_mps = fix.speed_kmh / 3.6
        try:
            writer.writerow(
                [
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
            )
            if self._record_file:
                self._record_file.flush()
        except Exception:
            self._log_event(
                "record_row_failed",
                level=logging.ERROR,
                sentence=update.get("sentence_type"),
                error="write_failed",
            )
            self.logger.exception("record_row_failed")


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
                writer.close()
                with contextlib.suppress(Exception):
                    await writer.wait_closed()
                self._serial_writer = None

            if not self._shutdown.is_set():
                await asyncio.sleep(self.reconnect_delay)

    def _set_connection_state(self, connected: bool, *, error: Optional[str]) -> None:
        changed = connected != self._connection_state or error != self._serial_error
        self._connection_state = connected
        self._serial_error = error
        self._fix.connected = connected
        self._fix.error = error
        if changed:
            self._log_event("connection_state", connected=connected, error=error)
            self._publish_state(location_changed=False)

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

    def _build_io_panel(self, container) -> None:
        assert tk is not None and ttk is not None

        container.columnconfigure(0, weight=1)
        container.rowconfigure(0, weight=1)

        telemetry = ttk.Frame(container, padding="6")
        telemetry.grid(row=0, column=0, sticky="nsew")
        telemetry.columnconfigure(0, weight=1)

        font = ("TkFixedFont", 10)
        self._telemetry_var = tk.StringVar(value=self._format_telemetry_text())
        ttk.Label(
            telemetry,
            textvariable=self._telemetry_var,
            font=font,
            justify="left",
            anchor="w",
        ).grid(row=0, column=0, sticky="nsew")
        self._update_info_panel()

    def _update_info_panel(self) -> None:
        if not self._telemetry_var:
            return
        self._telemetry_var.set(self._format_telemetry_text())

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
        return " | ".join(parts)

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

        tk_image = ImageTk.PhotoImage(mosaic_image)
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
        grid = GRID_SIZE
        size = grid * TILE_SIZE
        image = Image.new("RGB", (size, size), "#dcdcdc")

        xtile, ytile = self._latlon_to_tile(lat, lon, zoom_int)
        base_x = int(math.floor(xtile)) - grid // 2
        base_y = int(math.floor(ytile)) - grid // 2

        total_loaded = 0
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        n = 2 ** zoom_int

        try:
            for gx in range(grid):
                for gy in range(grid):
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

        self._draw_center_marker(image, xtile - base_x, ytile - base_y)
        info = f"{total_loaded}/{grid * grid} tiles (zoom={zoom_int})"
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

    def _draw_center_marker(self, image: Image.Image, tile_x_offset: float, tile_y_offset: float) -> None:
        draw = ImageDraw.Draw(image)
        x = tile_x_offset * TILE_SIZE
        y = tile_y_offset * TILE_SIZE
        radius = 8
        draw.ellipse(
            (x - radius, y - radius, x + radius, y + radius),
            outline="#ff4d4f",
            width=3,
        )
        draw.line((x - 12, y, x + 12, y), fill="#ff4d4f", width=2)
        draw.line((x, y - 12, x, y + 12), fill="#ff4d4f", width=2)

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
        overlay = ttk.Frame(parent)
        overlay.place(x=8, y=8)
        ttk.Button(overlay, text="-", width=3, command=lambda: self._adjust_zoom(-1)).pack(side="left")
        ttk.Button(overlay, text="+", width=3, command=lambda: self._adjust_zoom(1)).pack(side="left", padx=(4, 0))
        self._controls_overlay = overlay

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
MPS_PER_KNOT = 0.514444
