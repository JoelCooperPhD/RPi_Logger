from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
from rpi_logger.core.logging_utils import get_module_logger
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable, List, Optional, Sequence, TextIO

try:
    import tkinter as tk
    from tkinter import ttk, scrolledtext, messagebox
except Exception:
    tk = ttk = scrolledtext = messagebox = None  # type: ignore

try:
    from rpi_logger.core.ui.theme.styles import Theme
    from rpi_logger.core.ui.theme.colors import Colors
    from rpi_logger.core.ui.theme.widgets import RoundedButton
    HAS_THEME = True
except ImportError:
    HAS_THEME = False
    Theme = Colors = RoundedButton = None

from rpi_logger.core.commands import StatusMessage, StatusType
from rpi_logger.modules.base.storage_utils import ensure_module_data_dir, module_filename_prefix
from vmc import ModuleRuntime, RuntimeContext
from vmc.runtime_helpers import BackgroundTaskManager, ShutdownGuard
try:
    from .config import NotesConfig, NotesPreferences  # type: ignore
except ImportError:
    from config import NotesConfig, NotesPreferences


@dataclass(slots=True)
class NoteRecord:
    """Individual note container."""
    index: int
    trial_number: int
    text: str
    timestamp: float
    record_time_mono: float
    timestamp_iso: str
    elapsed: str
    modules: str
    file_line: str


class NotesArchive:
    """CSV persistence for notes."""
    HEADER = ["trial", "module", "device_id", "label", "record_time_unix", "record_time_mono", "device_time_unix", "content"]

    def __init__(self, base_dir: Path, logger: logging.Logger, *, encoding: str = "utf-8") -> None:
        self.base_dir = base_dir
        self.logger = logger
        self.encoding = encoding
        self.recording = False
        self.note_count = 0
        self._start_timestamp: Optional[float] = None
        self.file_path: Optional[Path] = None
        self._current_trial_number: Optional[int] = None
        self._file_handle: Optional[TextIO] = None
        self._csv_writer: Optional[csv.writer] = None

    async def start(self, trial_number: int) -> Path:
        try:
            normalized_trial = max(1, int(trial_number))
        except (TypeError, ValueError):
            normalized_trial = 1

        if self.recording and self.file_path:
            return self.file_path

        await asyncio.to_thread(self.base_dir.mkdir, parents=True, exist_ok=True)
        target = self._resolve_file_path(normalized_trial)
        self.file_path = target
        self._current_trial_number = normalized_trial
        self._start_timestamp = None

        if await asyncio.to_thread(target.exists):
            self.note_count = await asyncio.to_thread(self._count_existing_notes, target)
            await asyncio.to_thread(self._open_for_append, target)
            self.logger.info("Appending to note file: %s (%d notes)", target, self.note_count)
        else:
            await asyncio.to_thread(self._write_header, target)
            self.note_count = 0
            self.logger.info("Created new note file: %s", target)

        self._start_timestamp = time.time()
        self.recording = True
        return target

    async def stop(self) -> None:
        if not self.recording:
            return
        self.recording = False
        await asyncio.to_thread(self._close_file)
        self.logger.info("Archive closed: %d note(s) -> %s", self.note_count, self.file_path)

    def _close_file(self) -> None:
        if self._file_handle:
            try:
                self._file_handle.close()
            except Exception:
                self.logger.debug("Error closing file handle")
        self._file_handle = self._csv_writer = None

    async def add_note(self, text: str, modules: Sequence[str], *, posted_at: Optional[float] = None, trial_number: int) -> NoteRecord:
        if not self.recording:
            raise RuntimeError("Notes archive is not active")
        cleaned = text.strip()
        if not cleaned:
            raise ValueError("Cannot add empty note")

        timestamp = float(posted_at) if posted_at is not None else time.time()
        record_time_mono = time.perf_counter()
        if self._start_timestamp is None:
            self._start_timestamp = timestamp

        await asyncio.to_thread(self._append_row, cleaned, timestamp, record_time_mono, trial_number)
        self.note_count += 1

        modules_str = ";".join(sorted(modules)) if modules else ""
        file_line = self._format_csv_line([trial_number, "Notes", "notes", "", f"{timestamp:.6f}", f"{record_time_mono:.9f}", "", cleaned])
        return NoteRecord(
            index=self.note_count,
            trial_number=trial_number,
            text=cleaned,
            timestamp=timestamp,
            record_time_mono=record_time_mono,
            timestamp_iso=datetime.fromtimestamp(timestamp).isoformat(timespec="seconds"),
            elapsed=self.format_elapsed(timestamp - self._start_timestamp),
            modules=modules_str,
            file_line=file_line,
        )

    @staticmethod
    def _format_csv_line(row: List[Any]) -> str:
        output = io.StringIO()
        csv.writer(output).writerow(row)
        return output.getvalue().rstrip('\r\n')

    async def load_recent(self, limit: int) -> List[NoteRecord]:
        if not self.file_path or not await asyncio.to_thread(self.file_path.exists):
            return []
        return await asyncio.to_thread(self._read_records, limit, self.file_path)

    def current_elapsed(self) -> str:
        if not self.recording or self._start_timestamp is None:
            return "00:00:00"
        return self.format_elapsed(time.time() - self._start_timestamp)

    def _resolve_file_path(self, trial_number: int) -> Path:
        return self.base_dir / f"{module_filename_prefix(self.base_dir, 'Notes', trial_number, code='NTS')}_notes.csv"

    def _write_header(self, path: Path) -> None:
        self._file_handle = path.open("w", encoding=self.encoding, newline="")
        self._csv_writer = csv.writer(self._file_handle)
        self._csv_writer.writerow(self.HEADER)

    def _open_for_append(self, path: Path) -> None:
        self._file_handle = path.open("a", encoding=self.encoding, newline="")
        self._csv_writer = csv.writer(self._file_handle)

    @staticmethod
    def _resolve_header_indices(header: List[str]) -> dict[str, int]:
        normalized = [value.strip().lower() for value in header]

        def _first_index(names: Sequence[str], fallback: int) -> int:
            for name in names:
                try:
                    return normalized.index(name)
                except ValueError:
                    continue
            return fallback

        return {
            "trial": _first_index(("trial",), 0),
            "record_time_unix": _first_index(("record_time_unix", "timestamp"), 4),
            "record_time_mono": _first_index(("record_time_mono",), 5),
            "content": _first_index(("content",), 7),
        }

    def _count_existing_notes(self, path: Path) -> int:
        try:
            with path.open("r", encoding=self.encoding, newline="") as handle:
                reader = csv.reader(handle)
                rows = list(reader)
        except FileNotFoundError:
            return 0

        if len(rows) <= 1:  # Only header or empty
            return 0

        indices = self._resolve_header_indices(rows[0])
        first_timestamp: Optional[float] = None
        count = 0
        for row in rows[1:]:  # Skip header
            if len(row) <= indices["content"]:
                continue
            count += 1
            if first_timestamp is None:
                try:
                    ts_candidate = float(row[indices["record_time_unix"]])
                except (ValueError, IndexError):
                    ts_candidate = None
                if ts_candidate is not None:
                    first_timestamp = ts_candidate

        if first_timestamp is not None:
            self._start_timestamp = first_timestamp
        return count

    def _append_row(self, text: str, record_time_unix: float, record_time_mono: float, trial_number: int) -> None:
        if not self.file_path:
            raise RuntimeError("Archive file path not set")
        row = [trial_number, "Notes", "notes", "", f"{record_time_unix:.6f}", f"{record_time_mono:.9f}", "", text]
        if self._csv_writer and self._file_handle:
            self._csv_writer.writerow(row)
            self._file_handle.flush()
        else:
            with self.file_path.open("a", encoding=self.encoding, newline="") as handle:
                csv.writer(handle).writerow(row)

    def _read_records(self, limit: int, path: Path) -> List[NoteRecord]:
        try:
            with path.open("r", encoding=self.encoding, newline="") as handle:
                rows = list(csv.reader(handle))
        except FileNotFoundError:
            return []

        if len(rows) <= 1:
            return []

        indices = self._resolve_header_indices(rows[0])
        note_rows = [row for row in rows[1:] if len(row) > indices["content"]]
        total_notes = len(note_rows)
        start_index = max(0, total_notes - max(1, limit))
        records: List[NoteRecord] = []

        for idx, row in enumerate(note_rows[start_index:], start=start_index + 1):
            trial_number = int(row[indices["trial"]]) if len(row) > indices["trial"] else 0
            note_text = row[indices["content"]] if len(row) > indices["content"] else ""
            timestamp = float(row[indices["record_time_unix"]]) if len(row) > indices["record_time_unix"] else 0.0
            record_time_mono = float(row[indices["record_time_mono"]]) if len(row) > indices["record_time_mono"] else 0.0

            try:
                trial_number = int(trial_number)
                timestamp = float(timestamp)
                record_time_mono = float(record_time_mono)
            except (ValueError, TypeError):
                pass

            if self._start_timestamp is None and timestamp:
                self._start_timestamp = timestamp

            records.append(NoteRecord(
                index=idx,
                trial_number=trial_number,
                text=note_text,
                timestamp=timestamp,
                record_time_mono=record_time_mono,
                timestamp_iso=datetime.fromtimestamp(timestamp).isoformat(timespec="seconds") if timestamp else "",
                elapsed=self.format_elapsed(timestamp - (self._start_timestamp or timestamp)),
                modules="",
                file_line=self._format_csv_line(row),
            ))

        self.note_count = max(self.note_count, total_notes)
        return records

    @staticmethod
    def format_elapsed(seconds: float) -> str:
        seconds = max(0.0, float(seconds))
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"


class NotesRuntime(ModuleRuntime):
    """Note-taking runtime."""
    MODULE_SUBDIR = "Notes"

    def __init__(self, context: RuntimeContext) -> None:
        self.args = context.args
        fn = getattr(context.model, "preferences_scope", None)
        pref_scope = fn("notes") if callable(fn) else None
        self.preferences = NotesPreferences(pref_scope)
        self.typed_config = NotesConfig.from_preferences(pref_scope, self.args) if pref_scope else NotesConfig()

        self.model = context.model
        self.controller = context.controller
        self.supervisor = context.supervisor
        self.view = context.view
        self.logger = (context.logger.getChild("NotesRuntime") if context.logger else get_module_logger("NotesRuntime"))
        self.display_name = context.display_name

        self.task_manager = BackgroundTaskManager("NotesTasks", self.logger)
        self.shutdown_guard = ShutdownGuard(self.logger, timeout=getattr(self.args, "shutdown_timeout", 15.0))
        self._stop_event = asyncio.Event()
        self.project_root = context.module_dir.parent.parent

        self.history_limit = max(1, self.typed_config.history_limit)
        if self.preferences.prefs:
            self.history_limit = max(1, self.preferences.history_limit(self.history_limit))
        self.auto_start = self.typed_config.auto_start
        if self.preferences.prefs:
            self.auto_start = self.preferences.auto_start(self.auto_start)
        self._module_dir: Optional[Path] = None

        self.archive: Optional[NotesArchive] = None
        self._history: List[NoteRecord] = []
        self._missing_session_notice_shown = False
        self._history_widget: Optional[scrolledtext.ScrolledText] = None
        self._note_entry: Optional[ttk.Entry] = None
        self._post_button: Optional[ttk.Button] = None

    async def start(self) -> None:
        if self.view:
            self._build_ui()
            if hasattr(self.view, 'set_data_subdir'):
                self.view.set_data_subdir(self.MODULE_SUBDIR)

        if self.auto_start:
            self._run_async(self._start_recording())
        StatusMessage.send("ready")

    async def shutdown(self) -> None:
        await self.shutdown_guard.start()
        self._stop_event.set()
        if self.archive and self.archive.recording:
            try:
                await self.archive.stop()
            except Exception:
                self.logger.exception("Error stopping archive during shutdown")
        self.archive = None
        self.model.recording = False
        await self.task_manager.shutdown()
        await self.shutdown_guard.cancel()

    async def cleanup(self) -> None:
        self._history.clear()
        if self._history_widget and tk:
            self._history_widget.configure(state=tk.NORMAL)
            self._history_widget.delete("1.0", tk.END)
            self._history_widget.configure(state=tk.DISABLED)
        if self._note_entry:
            self._note_entry.delete(0, tk.END)

    async def handle_command(self, command: dict[str, Any]) -> bool:
        return await self._dispatch_action(
            (command.get("command") or "").lower(),
            note_text=(command.get("note") or command.get("note_text") or "").strip() or None,
            posted_at=self._extract_note_timestamp(command),
            on_empty_note=lambda: self.logger.warning("add_note command without text"),
        )

    async def handle_user_action(self, action: str, **kwargs: Any) -> bool:
        return await self._dispatch_action(
            (action or "").lower(),
            note_text=(kwargs.get("note") or kwargs.get("note_text") or "").strip() or None,
            posted_at=time.time(),
            on_empty_note=lambda: self.logger.debug("add_note action with empty text"),
        )

    @staticmethod
    def _extract_note_timestamp(payload: dict[str, Any]) -> Optional[float]:
        raw = payload.get("note_timestamp") or payload.get("timestamp")
        if raw is None:
            return None
        if isinstance(raw, (int, float)):
            try:
                return float(raw)
            except (TypeError, ValueError):
                return None
        if isinstance(raw, str):
            try:
                return datetime.fromisoformat(raw).timestamp()
            except ValueError:
                return None
        return None

    async def _dispatch_action(self, action: str, *, note_text: Optional[str], posted_at: Optional[float] = None, on_empty_note: Optional[Callable[[], None]] = None) -> bool:
        if action == "start_recording":
            await self._start_recording()
            return True
        if action == "stop_recording":
            await self._stop_recording()
            return True
        if action == "add_note":
            if note_text:
                await self._add_note(note_text, posted_at=posted_at if posted_at is not None else time.time())
            elif on_empty_note:
                on_empty_note()
            return True
        return False

    async def healthcheck(self) -> bool:
        return (self.archive and self.archive.recording) or not self._stop_event.is_set()

    def _build_ui(self) -> None:
        if not self.view or not tk or not ttk or not scrolledtext:
            return

        if HAS_THEME and Theme and (root := getattr(self.view, 'root', None)):
            Theme.configure_toplevel(root)

        def builder(parent: tk.Widget) -> None:
            if isinstance(parent, ttk.LabelFrame):
                parent.configure(text="Notes", padding="10")

            parent.grid_columnconfigure(0, weight=1)
            parent.grid_rowconfigure(0, weight=1)

            # Main container with border
            if HAS_THEME and Colors is not None:
                container = tk.Frame(
                    parent,
                    bg=Colors.BG_FRAME,
                    highlightbackground=Colors.BORDER,
                    highlightcolor=Colors.BORDER,
                    highlightthickness=1,
                )
            else:
                container = ttk.Frame(parent)
            container.grid(row=0, column=0, sticky="nsew", padx=2, pady=2)
            container.grid_columnconfigure(0, weight=1)
            container.grid_rowconfigure(0, weight=1)

            # History section
            history_lf = ttk.LabelFrame(container, text="History")
            history_lf.grid(row=0, column=0, sticky="nsew", padx=4, pady=(4, 2))
            history_lf.grid_columnconfigure(0, weight=1)
            history_lf.grid_rowconfigure(0, weight=1)

            # History widget
            self._history_widget = scrolledtext.ScrolledText(
                history_lf,
                height=12,
                wrap=tk.WORD,
                state=tk.DISABLED,
            )
            self._history_widget.grid(row=0, column=0, sticky="nsew", padx=2, pady=2)

            # Theme colors
            if HAS_THEME and Colors is not None:
                timestamp_color, elapsed_color, modules_color = Colors.PRIMARY, Colors.SUCCESS, Colors.WARNING
                self._history_widget.configure(
                    bg=Colors.BG_INPUT,
                    fg=Colors.FG_PRIMARY,
                    insertbackground=Colors.FG_PRIMARY,
                    selectbackground=Colors.PRIMARY,
                    selectforeground=Colors.FG_PRIMARY,
                )
            else:
                timestamp_color, elapsed_color, modules_color = "#1565c0", "#2e7d32", "#7b1fa2"

            self._history_widget.tag_config("timestamp", foreground=timestamp_color)
            self._history_widget.tag_config("elapsed", foreground=elapsed_color)
            self._history_widget.tag_config("modules", foreground=modules_color)

            # Input section
            input_lf = ttk.LabelFrame(container, text="New Note")
            input_lf.grid(row=1, column=0, sticky="ew", padx=4, pady=(2, 4))
            input_lf.grid_columnconfigure(0, weight=1)

            self._note_entry = ttk.Entry(input_lf)
            self._note_entry.grid(row=0, column=0, sticky="ew", padx=(4, 8), pady=4)
            self._note_entry.bind("<Return>", self._on_enter_pressed)

            # Post button
            if HAS_THEME and RoundedButton is not None and Colors is not None:
                self._post_button = RoundedButton(
                    input_lf,
                    text="Post",
                    command=lambda: self._run_async(self._post_note_from_entry()),
                    width=80,
                    height=32,
                    corner_radius=6,
                    style='default',
                    bg=Colors.BG_FRAME,
                )
            else:
                self._post_button = ttk.Button(
                    input_lf,
                    text="Post",
                    command=lambda: self._run_async(self._post_note_from_entry()),
                )
            self._post_button.grid(row=0, column=1, padx=(0, 4), pady=4)

        self.view.build_stub_content(builder)
        self._finalize_menus()
        self._render_history()

    def _finalize_menus(self) -> None:
        if fn := getattr(self.view, "finalize_view_menu", None):
            if callable(fn):
                fn(include_capture_stats=False)
        if fn := getattr(self.view, "finalize_file_menu", None):
            if callable(fn):
                fn()

    def _render_history(self) -> None:
        if not self._history_widget or not tk:
            return
        w = self._history_widget
        w.configure(state=tk.NORMAL)
        w.delete("1.0", tk.END)
        for r in self._history:
            w.insert(tk.END, f"[{r.timestamp_iso or '--'}] ", "timestamp")
            w.insert(tk.END, r.elapsed, "elapsed")
            if r.modules:
                w.insert(tk.END, f" [{r.modules}]", "modules")
            w.insert(tk.END, f" {r.text}\n")
        w.see(tk.END)
        w.configure(state=tk.DISABLED)

    def _run_async(self, coro: Awaitable[Any]) -> None:
        try:
            self.task_manager.create(coro)
        except RuntimeError:
            try:
                asyncio.create_task(coro)
            except RuntimeError:
                # No running event loop
                coro.close()  # type: ignore[union-attr]

    def _on_enter_pressed(self, event: Any):  # type: ignore[override]
        if not tk or event.state & 0x1:
            return None
        self._run_async(self._post_note_from_entry())
        return "break"

    async def _post_note_from_entry(self) -> None:
        if not self._note_entry or not (text := self._note_entry.get().strip()):
            return
        if await self._add_note(text, posted_at=time.time()):
            self._note_entry.delete(0, tk.END)

    async def _start_recording(self) -> bool:
        if not (module_dir := await self._ensure_module_dir()):
            return False

        archive = self.archive
        if archive and archive.base_dir != module_dir:
            try:
                await archive.stop()
            except Exception:
                self.logger.exception("Failed to stop previous archive")
            archive = None

        if not archive:
            archive = self.archive = NotesArchive(module_dir, self.logger.getChild("Archive"))

        if archive.recording:
            self.logger.debug("Archive already active: %s", archive.file_path)
            return False

        trial_number = self._resolve_trial_number()
        try:
            file_path = await archive.start(trial_number)
        except Exception as exc:
            self.logger.exception("Failed to start archive", exc_info=exc)
            return False

        self.preferences.set_last_note_path(str(file_path))
        self.model.recording = True
        self.logger.info("Recording started -> %s", file_path)
        await self._refresh_history()
        self._emit_status(StatusType.RECORDING_STARTED, {
            "session_dir": str(module_dir),
            "notes_file": str(file_path),
            "note_count": archive.note_count,
            "trial_number": trial_number,
        })
        return True

    async def _stop_recording(self) -> bool:
        if not self.archive or not self.archive.recording:
            return False
        try:
            await self.archive.stop()
        except Exception:
            self.logger.exception("Error stopping archive")
        self.model.recording = False
        self.logger.info("Recording stopped (%d note(s))", self.archive.note_count)
        self._emit_status(StatusType.RECORDING_STOPPED, {
            "session_dir": str(self._module_dir) if self._module_dir else None,
            "note_count": self.archive.note_count,
        })
        return True

    async def _add_note(self, note_text: str, *, posted_at: Optional[float] = None) -> bool:
        if not await self._ensure_archive_active() or not self.archive:
            return False

        try:
            record = await self.archive.add_note(
                note_text,
                await self._read_recording_modules(),
                posted_at=posted_at,
                trial_number=self._resolve_trial_number(),
            )
        except ValueError as exc:
            self.logger.debug("Cannot add note: %s", exc)
            return False
        except Exception:
            self.logger.exception("Failed to add note")
            return False

        self._history.append(record)
        self._history = self._history[-self.history_limit:]
        self._render_history()
        self.logger.info("Note %d: %s", record.index, record.text[:77] + "..." if len(record.text) > 80 else record.text)
        self._emit_status("note_added", {
            "note_index": record.index,
            "trial_number": record.trial_number,
            "note_text": record.text,
            "timestamp": record.timestamp_iso,
            "elapsed": record.elapsed,
            "modules": record.modules,
        })
        return True

    async def on_session_dir_available(self, session_dir: Path) -> None:
        if self.archive and self.archive.recording:
            try:
                await self.archive.stop()
            except Exception:
                self.logger.exception("Error stopping archive before session switch")
            else:
                self._emit_status(StatusType.RECORDING_STOPPED, {
                    "session_dir": str(self.archive.base_dir),
                    "note_count": self.archive.note_count,
                })
        self.archive = None
        self.model.recording = False

        try:
            self._module_dir = await asyncio.to_thread(ensure_module_data_dir, session_dir, self.MODULE_SUBDIR)
        except Exception:
            self._module_dir = session_dir / self.MODULE_SUBDIR
            self.logger.exception("Failed to ensure session directory")

        self._missing_session_notice_shown = False
        self._history.clear()
        self._render_history()
        if self.auto_start:
            self._run_async(self._start_recording())

    async def _refresh_history(self) -> None:
        if not self.archive:
            self._history.clear()
            self._render_history()
            return
        try:
            self._history = (await self.archive.load_recent(self.history_limit))[-self.history_limit:]
            self._render_history()
        except Exception:
            self.logger.exception("Failed to load note history")

    async def _ensure_session_dir(self) -> Optional[Path]:
        if session_dir := self.model.session_dir:
            try:
                path = Path(session_dir)
                await asyncio.to_thread(path.mkdir, parents=True, exist_ok=True)
                return path
            except Exception:
                self.logger.exception("Failed to ensure session directory")
                return None
        self._prompt_session_required()
        return None

    async def _ensure_module_dir(self) -> Optional[Path]:
        if not (session_dir := await self._ensure_session_dir()):
            return None
        try:
            self._module_dir = await asyncio.to_thread(ensure_module_data_dir, session_dir, self.MODULE_SUBDIR)
            return self._module_dir
        except Exception:
            self.logger.exception("Failed to ensure module directory")
            return None

    def _resolve_trial_number(self) -> int:
        try:
            value = int(self.model.trial_number or 0)
        except (TypeError, ValueError):
            value = 0
        return max(1, value)

    async def _ensure_archive_active(self) -> bool:
        if self.archive and self.archive.recording:
            return True
        await self._start_recording()
        return bool(self.archive and self.archive.recording)

    def _prompt_session_required(self) -> None:
        if self._missing_session_notice_shown:
            return
        self._missing_session_notice_shown = True
        message = "Start a session from the main logger before saving notes."

        if self.view and tk and messagebox and (root := getattr(self.view, "root", None)):
            try:
                root.after(0, lambda: messagebox.showinfo("Session Required", message))
            except Exception:
                self.logger.warning("Failed to show session prompt")
        else:
            self.logger.warning(message)

    async def _read_recording_modules(self) -> List[str]:
        modules_file = self.project_root / "data" / "running_modules.json"
        try:
            if not await asyncio.to_thread(modules_file.exists):
                return []
            data = json.loads(await asyncio.to_thread(modules_file.read_text, "utf-8"))
            if not isinstance(data, dict):
                return []
            return sorted([str(name) for name, state in data.items() if isinstance(state, dict) and state.get("recording")])
        except Exception:
            self.logger.debug("Failed to read running modules")
            return []

    def _emit_status(self, status: str, payload: Optional[dict[str, Any]] = None) -> None:
        StatusMessage.send(status, payload or {})
