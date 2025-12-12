"""Notes runtime built on the Codex VMC stack."""

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
except Exception:  # pragma: no cover - defensive import for headless environments
    tk = None  # type: ignore
    ttk = None  # type: ignore
    scrolledtext = None  # type: ignore
    messagebox = None  # type: ignore

# Theme imports for dark theme styling
try:
    from rpi_logger.core.ui.theme.styles import Theme
    from rpi_logger.core.ui.theme.colors import Colors
    from rpi_logger.core.ui.theme.widgets import RoundedButton
    HAS_THEME = True
except ImportError:
    HAS_THEME = False
    Theme = None
    Colors = None
    RoundedButton = None

from rpi_logger.core.commands import StatusMessage, StatusType
from rpi_logger.modules.base.storage_utils import ensure_module_data_dir, module_filename_prefix
from vmc import ModuleRuntime, RuntimeContext
from vmc.runtime_helpers import BackgroundTaskManager, ShutdownGuard
try:  # Allow running as a script (no package context)
    from .preferences import NotesPreferences  # type: ignore
    from .config import NotesConfig  # type: ignore
except ImportError:  # pragma: no cover - fallback for script execution
    from preferences import NotesPreferences
    from config import NotesConfig


@dataclass(slots=True)
class NoteRecord:
    """Lightweight container for an individual note."""

    index: int
    trial_number: int
    text: str
    timestamp: float
    timestamp_iso: str
    elapsed: str
    modules: str
    file_line: str


class NotesArchive:
    """Manage on-disk persistence for notes using proper CSV format."""

    HEADER = ["Note", "trial", "Content", "Timestamp"]

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
        """Prepare the notes file for the specified trial."""

        try:
            normalized_trial = int(trial_number)
        except (TypeError, ValueError):
            normalized_trial = 1
        normalized_trial = max(1, normalized_trial)

        if self.recording and self.file_path:
            return self.file_path

        await asyncio.to_thread(self.base_dir.mkdir, parents=True, exist_ok=True)

        target = self._resolve_file_path(normalized_trial)
        self.file_path = target
        self._current_trial_number = normalized_trial
        self._start_timestamp = None

        exists = await asyncio.to_thread(target.exists)
        if exists:
            self.note_count = await asyncio.to_thread(self._count_existing_notes, target)
            await asyncio.to_thread(self._open_for_append, target)
            self.logger.info(
                "Appending to existing note file: %s (current notes: %d)",
                target,
                self.note_count,
            )
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
        self.logger.info(
            "Notes archive closed with %d note(s) -> %s",
            self.note_count,
            self.file_path,
        )

    def _close_file(self) -> None:
        """Close the CSV file handle."""
        if self._file_handle:
            try:
                self._file_handle.close()
            except Exception:
                self.logger.debug("Error closing notes file handle")
        self._file_handle = None
        self._csv_writer = None

    async def add_note(
        self,
        text: str,
        modules: Sequence[str],
        *,
        posted_at: Optional[float] = None,
        trial_number: int,
    ) -> NoteRecord:
        if not self.recording:
            raise RuntimeError("Notes archive is not active")

        cleaned = text.strip()
        if not cleaned:
            raise ValueError("Cannot add empty note")

        # Preserve original text - CSV writer handles escaping
        timestamp = float(posted_at) if posted_at is not None else time.time()
        if self._start_timestamp is None:
            self._start_timestamp = timestamp

        await asyncio.to_thread(self._append_row, cleaned, timestamp, trial_number)

        self.note_count += 1

        modules_str = ";".join(sorted(modules)) if modules else ""
        # Generate CSV-formatted line for display
        file_line = self._format_csv_line(["Note", trial_number, cleaned, timestamp])
        iso_stamp = datetime.fromtimestamp(timestamp).isoformat(timespec="seconds")
        elapsed_display = self.format_elapsed(timestamp - self._start_timestamp)

        return NoteRecord(
            index=self.note_count,
            trial_number=trial_number,
            text=cleaned,
            timestamp=timestamp,
            timestamp_iso=iso_stamp,
            elapsed=elapsed_display,
            modules=modules_str,
            file_line=file_line,
        )

    @staticmethod
    def _format_csv_line(row: List[Any]) -> str:
        """Format a row as a CSV line string for display purposes."""
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(row)
        return output.getvalue().rstrip('\r\n')

    async def load_recent(self, limit: int) -> List[NoteRecord]:
        path = self.file_path
        if not path:
            return []
        exists = await asyncio.to_thread(path.exists)
        if not exists:
            return []
        return await asyncio.to_thread(self._read_records, limit, path)

    def current_elapsed(self) -> str:
        if not self.recording or self._start_timestamp is None:
            return "00:00:00"
        return self.format_elapsed(time.time() - self._start_timestamp)

    def _resolve_file_path(self, trial_number: int) -> Path:
        prefix = module_filename_prefix(self.base_dir, "Notes", trial_number, code="NOTES")
        return self.base_dir / f"{prefix}.csv"

    def _write_header(self, path: Path) -> None:
        handle = path.open("w", encoding=self.encoding, newline="")
        writer = csv.writer(handle)
        writer.writerow(self.HEADER)
        self._file_handle = handle
        self._csv_writer = writer

    def _open_for_append(self, path: Path) -> None:
        """Open existing file in append mode."""
        handle = path.open("a", encoding=self.encoding, newline="")
        writer = csv.writer(handle)
        self._file_handle = handle
        self._csv_writer = writer

    def _count_existing_notes(self, path: Path) -> int:
        try:
            with path.open("r", encoding=self.encoding, newline="") as handle:
                reader = csv.reader(handle)
                rows = list(reader)
        except FileNotFoundError:
            return 0

        if len(rows) <= 1:  # Only header or empty
            return 0

        first_timestamp: Optional[float] = None
        count = 0
        for row in rows[1:]:  # Skip header
            if len(row) < 4:
                continue
            count += 1
            if first_timestamp is None:
                try:
                    ts_candidate = float(row[3])
                except (ValueError, IndexError):
                    ts_candidate = None
                if ts_candidate is not None:
                    first_timestamp = ts_candidate

        if first_timestamp is not None:
            self._start_timestamp = first_timestamp
        return count

    def _append_row(self, text: str, timestamp: float, trial_number: int) -> None:
        if not self.file_path:
            raise RuntimeError("Archive file path not set")
        if self._csv_writer and self._file_handle:
            self._csv_writer.writerow(["Note", trial_number, text, timestamp])
            self._file_handle.flush()
        else:
            # Fallback: open in append mode if writer not available
            with self.file_path.open("a", encoding=self.encoding, newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(["Note", trial_number, text, timestamp])

    def _read_records(self, limit: int, path: Path) -> List[NoteRecord]:
        try:
            with path.open("r", encoding=self.encoding, newline="") as handle:
                reader = csv.reader(handle)
                rows = list(reader)
        except FileNotFoundError:
            return []

        if len(rows) <= 1:  # Only header or empty
            return []

        note_rows = [row for row in rows[1:] if len(row) >= 4]
        total_notes = len(note_rows)
        start_index = max(0, total_notes - max(1, limit))
        records: List[NoteRecord] = []
        for idx, row in enumerate(note_rows[start_index:], start=start_index + 1):
            try:
                trial_number = int(row[1])
            except (ValueError, IndexError):
                trial_number = 0
            note_text = row[2] if len(row) > 2 else ""
            try:
                timestamp = float(row[3])
            except (ValueError, IndexError):
                timestamp = 0.0

            if self._start_timestamp is None and timestamp:
                self._start_timestamp = timestamp

            iso_stamp = datetime.fromtimestamp(timestamp).isoformat(timespec="seconds") if timestamp else ""
            elapsed_display = self.format_elapsed(timestamp - (self._start_timestamp or timestamp))
            # Reconstruct CSV line for display
            file_line = self._format_csv_line(row)
            records.append(
                NoteRecord(
                    index=idx,
                    trial_number=trial_number,
                    text=note_text,
                    timestamp=timestamp,
                    timestamp_iso=iso_stamp or "",
                    elapsed=elapsed_display,
                    modules="",
                    file_line=file_line,
                )
            )

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
    """Interactive note-taking runtime built atop the Codex supervisor."""
    MODULE_SUBDIR = "Notes"

    def __init__(self, context: RuntimeContext) -> None:
        self.args = context.args
        scope_fn = getattr(context.model, "preferences_scope", None)
        pref_scope = scope_fn("notes") if callable(scope_fn) else None
        self.preferences = NotesPreferences(pref_scope)

        # Load typed config via preferences_scope
        self.typed_config = NotesConfig.from_preferences(pref_scope, self.args) if pref_scope else NotesConfig()

        self.model = context.model
        self.controller = context.controller
        self.supervisor = context.supervisor
        self.view = context.view
        base_logger = context.logger
        self.logger = base_logger.getChild("NotesRuntime") if base_logger else get_module_logger("NotesRuntime")
        self.display_name = context.display_name

        self.task_manager = BackgroundTaskManager("NotesTasks", self.logger)
        timeout = getattr(self.args, "shutdown_timeout", 15.0)
        self.shutdown_guard = ShutdownGuard(self.logger, timeout=timeout)
        self._stop_event = asyncio.Event()

        self.project_root = context.module_dir.parent.parent

        # Use typed config for history_limit and auto_start
        self.history_limit = max(1, self.typed_config.history_limit)
        if self.preferences.prefs:
            self.history_limit = max(1, self.preferences.history_limit(self.history_limit))
        self.auto_start = self.typed_config.auto_start
        if self.preferences.prefs:
            self.auto_start = self.preferences.auto_start(self.auto_start)
            self.preferences.set_history_limit(self.history_limit)
            self.preferences.set_auto_start(self.auto_start)
        self._module_dir: Optional[Path] = None

        self.archive: Optional[NotesArchive] = None
        self._history: List[NoteRecord] = []
        self._missing_session_notice_shown = False

        # UI handles
        self._history_widget: Optional[scrolledtext.ScrolledText] = None
        self._note_entry: Optional[ttk.Entry] = None
        self._post_button: Optional[ttk.Button] = None

    async def start(self) -> None:
        if not self.view:
            self.logger.info("GUI view unavailable; Notes runtime running headless")
        else:
            self._build_ui()
            if hasattr(self.view, 'set_data_subdir'):
                self.view.set_data_subdir(self.MODULE_SUBDIR)

        if self.preferences.prefs:
            self.preferences.set_auto_start(self.auto_start)

        if self.auto_start:
            self._run_async(self._start_recording())

        # Notify logger that module is ready for commands
        # This is the handshake signal that turns the indicator green
        StatusMessage.send("ready")

    async def shutdown(self) -> None:
        await self.shutdown_guard.start()
        self._stop_event.set()

        if self.archive and self.archive.recording:
            try:
                await self.archive.stop()
            except Exception:  # pragma: no cover - defensive logging
                self.logger.exception("Error while stopping archive during shutdown")
        self.archive = None
        self.model.recording = False

        await self.task_manager.shutdown()
        await self.shutdown_guard.cancel()

    async def cleanup(self) -> None:
        self._history.clear()
        if self._history_widget and tk is not None:
            self._history_widget.configure(state=tk.NORMAL)
            self._history_widget.delete("1.0", tk.END)
            self._history_widget.configure(state=tk.DISABLED)
        if self._note_entry:
            self._note_entry.delete(0, tk.END)

    async def handle_command(self, command: dict[str, Any]) -> bool:
        action = (command.get("command") or "").lower()
        note_text = (command.get("note") or command.get("note_text") or "").strip()
        posted_at = self._extract_note_timestamp(command)
        return await self._dispatch_action(
            action,
            note_text=note_text or None,
            posted_at=posted_at,
            on_empty_note=lambda: self.logger.warning("Received add_note command without note text"),
        )

    async def handle_user_action(self, action: str, **kwargs: Any) -> bool:
        action = (action or "").lower()
        note_text = (kwargs.get("note") or kwargs.get("note_text") or "").strip()
        return await self._dispatch_action(
            action,
            note_text=note_text or None,
            posted_at=time.time(),
            on_empty_note=lambda: self.logger.debug("Ignored add_note user action with empty text"),
        )

    @staticmethod
    def _extract_note_timestamp(payload: dict[str, Any]) -> Optional[float]:
        raw = payload.get("note_timestamp")
        if raw is None:
            raw = payload.get("timestamp")
        if raw is None:
            return None
        if isinstance(raw, (int, float)):
            try:
                return float(raw)
            except (TypeError, ValueError):
                return None
        if isinstance(raw, str):
            try:
                dt = datetime.fromisoformat(raw)
            except ValueError:
                return None
            return dt.timestamp()
        return None

    async def _dispatch_action(
        self,
        action: str,
        *,
        note_text: Optional[str],
        posted_at: Optional[float] = None,
        on_empty_note: Optional[Callable[[], None]] = None,
    ) -> bool:
        if action == "start_recording":
            await self._start_recording()
            return True
        if action == "stop_recording":
            await self._stop_recording()
            return True
        if action == "add_note":
            if note_text:
                effective_ts = posted_at if posted_at is not None else time.time()
                await self._add_note(note_text, posted_at=effective_ts)
            else:
                if on_empty_note:
                    on_empty_note()
            return True
        return False

    async def healthcheck(self) -> bool:
        if self.archive and self.archive.recording:
            return True
        return not self._stop_event.is_set()

    # ------------------------------------------------------------------
    # UI helpers

    def _build_ui(self) -> None:
        if not self.view or tk is None or ttk is None or scrolledtext is None:
            return

        # Apply theme to the window if available
        if HAS_THEME and Theme is not None:
            root = getattr(self.view, 'root', None)
            if root:
                Theme.configure_toplevel(root)

        def builder(parent: tk.Widget) -> None:
            if isinstance(parent, ttk.LabelFrame):
                parent.configure(text="Notes", padding="10")

            parent.grid_columnconfigure(0, weight=1)
            parent.grid_rowconfigure(0, weight=1)

            # Create main container with visible border (matching VOG/DRT style)
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

            # History section in a LabelFrame (matching VOG/DRT pattern)
            history_lf = ttk.LabelFrame(container, text="History")
            history_lf.grid(row=0, column=0, sticky="nsew", padx=4, pady=(4, 2))
            history_lf.grid_columnconfigure(0, weight=1)
            history_lf.grid_rowconfigure(0, weight=1)

            # Create history widget with theme-aware colors
            self._history_widget = scrolledtext.ScrolledText(
                history_lf,
                height=12,
                wrap=tk.WORD,
                state=tk.DISABLED,
            )
            self._history_widget.grid(row=0, column=0, sticky="nsew", padx=2, pady=2)

            # Configure text colors based on theme availability
            if HAS_THEME and Colors is not None:
                # Dark theme colors - visible on dark background
                timestamp_color = Colors.PRIMARY          # Blue (#3498db)
                elapsed_color = Colors.SUCCESS            # Green (#2ecc71)
                modules_color = Colors.WARNING            # Orange (#f39c12)
                text_fg = Colors.FG_PRIMARY               # Light gray (#ecf0f1)
                text_bg = Colors.BG_INPUT                 # Dark input bg (#3d3d3d)

                # Apply ScrolledText theme styling
                self._history_widget.configure(
                    bg=text_bg,
                    fg=text_fg,
                    insertbackground=text_fg,
                    selectbackground=Colors.PRIMARY,
                    selectforeground=Colors.FG_PRIMARY,
                )
            else:
                # Fallback colors for light theme
                timestamp_color = "#1565c0"  # Material Blue 800
                elapsed_color = "#2e7d32"    # Material Green 800
                modules_color = "#7b1fa2"    # Material Purple 700

            self._history_widget.tag_config("timestamp", foreground=timestamp_color)
            self._history_widget.tag_config("elapsed", foreground=elapsed_color)
            self._history_widget.tag_config("modules", foreground=modules_color)

            # New Note section in a LabelFrame (matching VOG/DRT pattern)
            input_lf = ttk.LabelFrame(container, text="New Note")
            input_lf.grid(row=1, column=0, sticky="ew", padx=4, pady=(2, 4))
            input_lf.grid_columnconfigure(0, weight=1)

            # Entry widget - styled via ttk theme
            self._note_entry = ttk.Entry(input_lf)
            self._note_entry.grid(row=0, column=0, sticky="ew", padx=(4, 8), pady=4)
            self._note_entry.bind("<Return>", self._on_enter_pressed)

            # Post button - use RoundedButton if available, else ttk.Button
            # Using 'default' style and height=32 to match VOG/DRT
            if HAS_THEME and RoundedButton is not None and Colors is not None:
                self._post_button = RoundedButton(
                    input_lf,
                    text="Post",
                    command=lambda: self._run_async(self._post_note_from_entry()),
                    width=80,
                    height=32,
                    corner_radius=6,
                    style='default',  # Match VOG/DRT button style
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
        """Finalize View and File menus with standard items."""
        # Finalize View menu (Logger only - Notes doesn't use capture stats)
        finalize_view = getattr(self.view, "finalize_view_menu", None)
        if callable(finalize_view):
            finalize_view(include_capture_stats=False)

        # Finalize File menu (adds Quit)
        finalize_file = getattr(self.view, "finalize_file_menu", None)
        if callable(finalize_file):
            finalize_file()

    def _render_history(self) -> None:
        if not self._history_widget or tk is None:
            return
        widget = self._history_widget
        widget.configure(state=tk.NORMAL)
        widget.delete("1.0", tk.END)
        for record in self._history:
            timestamp = record.timestamp_iso or "--"
            widget.insert(tk.END, f"[{timestamp}] ", "timestamp")
            widget.insert(tk.END, record.elapsed, "elapsed")
            if record.modules:
                widget.insert(tk.END, f" [{record.modules}]", "modules")
            widget.insert(tk.END, f" {record.text}\n")
        widget.see(tk.END)
        widget.configure(state=tk.DISABLED)

    def _run_async(self, coro: Awaitable[Any]) -> None:
        try:
            self.task_manager.create(coro)
        except RuntimeError:
            asyncio.create_task(coro)

    def _on_enter_pressed(self, event: Any):  # type: ignore[override]
        if tk is None:
            return None
        if event.state & 0x1:  # Shift pressed -> allow newline
            return None
        self._run_async(self._post_note_from_entry())
        return "break"

    async def _post_note_from_entry(self) -> None:
        if self._note_entry is None:
            return
        text = self._note_entry.get().strip()
        if not text:
            return
        success = await self._add_note(text, posted_at=time.time())
        if success:
            self._note_entry.delete(0, tk.END)

    # ------------------------------------------------------------------
    # Recording lifecycle

    async def _start_recording(self) -> bool:
        module_dir = await self._ensure_module_dir()
        if module_dir is None:
            return False
        archive = self.archive

        if archive and archive.base_dir != module_dir:
            try:
                await archive.stop()
            except Exception:
                self.logger.exception("Failed to stop previous archive before session switch")
            archive = None

        if archive is None:
            archive = NotesArchive(module_dir, self.logger.getChild("Archive"))
            self.archive = archive

        if archive.recording:
            self.logger.debug("Notes archive already active: %s", archive.file_path)
            return False

        trial_number = self._resolve_trial_number()

        try:
            file_path = await archive.start(trial_number)
        except Exception as exc:
            self.logger.exception("Failed to start note archive", exc_info=exc)
            return False
        self.preferences.set_last_note_path(str(file_path))

        self.model.recording = True
        self.logger.info("Notes recording started -> %s", file_path)
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
            self.logger.exception("Error stopping notes archive")

        module_dir = self._module_dir
        self.model.recording = False
        self.logger.info("Notes recording stopped (%d note(s))", self.archive.note_count)
        self._emit_status(StatusType.RECORDING_STOPPED, {
            "session_dir": str(module_dir) if module_dir else None,
            "note_count": self.archive.note_count,
        })
        return True

    async def _add_note(self, note_text: str, *, posted_at: Optional[float] = None) -> bool:
        if not await self._ensure_archive_active():
            return False

        archive = self.archive
        if not archive:
            return False

        trial_number = self._resolve_trial_number()
        modules = await self._read_recording_modules()
        try:
            record = await archive.add_note(
                note_text,
                modules,
                posted_at=posted_at,
                trial_number=trial_number,
            )
        except ValueError as exc:
            self.logger.debug("Cannot add note: %s", exc)
            return False
        except Exception:
            self.logger.exception("Failed to add note")
            return False

        self._history.append(record)
        self._history = self._history[-self.history_limit :]
        self._render_history()

        preview = record.text if len(record.text) <= 80 else record.text[:77] + "..."
        self.logger.info("Note %d recorded: %s", record.index, preview)

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
        """Ensure the legacy notes directory exists when the session starts."""

        archive = self.archive
        if archive and archive.recording:
            previous_session = archive.base_dir
            try:
                await archive.stop()
            except Exception:
                self.logger.exception("Error stopping archive before session switch")
            else:
                self._emit_status(StatusType.RECORDING_STOPPED, {
                    "session_dir": str(previous_session),
                    "note_count": archive.note_count,
                })
        self.archive = None
        self.model.recording = False

        try:
            module_dir = await asyncio.to_thread(ensure_module_data_dir, session_dir, self.MODULE_SUBDIR)
        except Exception:
            module_dir = session_dir / self.MODULE_SUBDIR
            self.logger.exception("Failed to ensure session directory exists", exc_info=True)
        self._module_dir = module_dir

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
            records = await self.archive.load_recent(self.history_limit)
        except Exception:
            self.logger.exception("Failed to load note history")
            return

        self._history = records[-self.history_limit :]
        self._render_history()

    async def _ensure_session_dir(self) -> Optional[Path]:
        session_dir = self.model.session_dir
        if session_dir:
            try:
                path = Path(session_dir)
            except TypeError:
                self.logger.exception("Session directory is invalid", exc_info=True)
                return None
            try:
                await asyncio.to_thread(path.mkdir, parents=True, exist_ok=True)
            except Exception:
                self.logger.exception("Failed to ensure session directory exists", exc_info=True)
            return path

        self._prompt_session_required()
        return None

    async def _ensure_module_dir(self) -> Optional[Path]:
        session_dir = await self._ensure_session_dir()
        if session_dir is None:
            return None
        try:
            module_dir = await asyncio.to_thread(ensure_module_data_dir, session_dir, self.MODULE_SUBDIR)
        except Exception:
            self.logger.exception("Failed to ensure notes module directory exists", exc_info=True)
            return None
        self._module_dir = module_dir
        return module_dir

    def _resolve_trial_number(self) -> int:
        try:
            value = int(self.model.trial_number or 0)
        except (TypeError, ValueError):
            value = 0
        if value <= 0:
            value = 1
        return value

    async def _ensure_archive_active(self) -> bool:
        archive = self.archive
        if archive and archive.recording:
            return True

        await self._start_recording()
        archive = self.archive
        return bool(archive and archive.recording)

    def _prompt_session_required(self) -> None:
        if self._missing_session_notice_shown:
            return
        self._missing_session_notice_shown = True

        message = (
            "Start a session from the main logger before saving notes.\n"
            "Use the Start Session button to choose where data will be stored."
        )

        if self.view and tk is not None and messagebox is not None:
            root = getattr(self.view, "root", None)

            def _show_popup() -> None:
                try:
                    messagebox.showinfo("Session Required", message)
                except Exception:
                    self.logger.warning("Cannot display session prompt", exc_info=True)

            if root is not None:
                try:
                    root.after(0, _show_popup)
                except Exception:
                    self.logger.warning("Failed to schedule session prompt", exc_info=True)
            else:
                self.logger.warning(message)
        else:
            self.logger.warning(message)

    async def _read_recording_modules(self) -> List[str]:
        modules_file = self.project_root / "data" / "running_modules.json"
        try:
            exists = await asyncio.to_thread(modules_file.exists)
            if not exists:
                return []
            content = await asyncio.to_thread(modules_file.read_text, "utf-8")
            data = json.loads(content)
            if not isinstance(data, dict):
                return []
            modules: List[str] = []
            for name, state in data.items():
                if isinstance(state, dict) and state.get("recording"):
                    modules.append(str(name))
            modules.sort()
            return modules
        except Exception:
            self.logger.debug("Failed to read running modules info", exc_info=True)
            return []

    def _emit_status(self, status: str, payload: Optional[dict[str, Any]] = None) -> None:
        StatusMessage.send(status, payload or {})
