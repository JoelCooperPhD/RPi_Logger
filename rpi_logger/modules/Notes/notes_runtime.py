"""Notes runtime built on the Codex VMC stack."""

from __future__ import annotations

import asyncio
import json
from rpi_logger.core.logging_utils import get_module_logger
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable, List, Optional, Sequence

try:
    import tkinter as tk
    from tkinter import ttk, scrolledtext, messagebox
except Exception:  # pragma: no cover - defensive import for headless environments
    tk = None  # type: ignore
    ttk = None  # type: ignore
    scrolledtext = None  # type: ignore
    messagebox = None  # type: ignore

from rpi_logger.core.commands import StatusMessage, StatusType
from rpi_logger.modules.base.storage_utils import ensure_module_data_dir, module_filename_prefix
from vmc import ModuleRuntime, RuntimeContext
from vmc.runtime_helpers import BackgroundTaskManager, ShutdownGuard


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
    """Manage on-disk persistence for notes using the legacy format."""

    HEADER = "Note,trial,Content,Timestamp"

    def __init__(self, base_dir: Path, logger: logging.Logger, *, encoding: str = "utf-8") -> None:
        self.base_dir = base_dir
        self.logger = logger
        self.encoding = encoding
        self.recording = False
        self.note_count = 0
        self._start_timestamp: Optional[float] = None
        self.file_path: Optional[Path] = None
        self._current_trial_number: Optional[int] = None

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
        self.logger.info(
            "Notes archive closed with %d note(s) -> %s",
            self.note_count,
            self.file_path,
        )

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

        sanitized = self._sanitize_note_text(cleaned)

        timestamp = float(posted_at) if posted_at is not None else time.time()
        if self._start_timestamp is None:
            self._start_timestamp = timestamp

        await asyncio.to_thread(self._append_row, sanitized, timestamp, trial_number)

        self.note_count += 1

        modules_str = ";".join(sorted(modules)) if modules else ""
        file_line = f"Note,{trial_number},{sanitized},{timestamp}"
        iso_stamp = datetime.fromtimestamp(timestamp).isoformat(timespec="seconds")
        elapsed_display = self.format_elapsed(timestamp - self._start_timestamp)

        return NoteRecord(
            index=self.note_count,
            trial_number=trial_number,
            text=sanitized,
            timestamp=timestamp,
            timestamp_iso=iso_stamp,
            elapsed=elapsed_display,
            modules=modules_str,
            file_line=file_line,
        )

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
        return self.base_dir / f"{prefix}.txt"

    def _write_header(self, path: Path) -> None:
        with path.open("w", encoding=self.encoding) as handle:
            handle.write(f"{self.HEADER}\n")

    def _count_existing_notes(self, path: Path) -> int:
        try:
            with path.open("r", encoding=self.encoding) as handle:
                lines = handle.readlines()
        except FileNotFoundError:
            return 0

        if not lines:
            return 0

        first_timestamp: Optional[float] = None
        count = 0
        for raw in lines[1:]:
            stripped = raw.strip()
            if not stripped:
                continue
            count += 1
            if first_timestamp is None:
                parts = stripped.split(",", 3)
                if len(parts) >= 4:
                    try:
                        ts_candidate = float(parts[3])
                    except ValueError:
                        ts_candidate = None
                    if ts_candidate is not None:
                        first_timestamp = ts_candidate

        if first_timestamp is not None:
            self._start_timestamp = first_timestamp
        return count

    def _append_row(self, text: str, timestamp: float, trial_number: int) -> None:
        if not self.file_path:
            raise RuntimeError("Archive file path not set")
        with self.file_path.open("a", encoding=self.encoding) as handle:
            handle.write(f"Note,{trial_number},{text},{timestamp}\n")

    def _read_records(self, limit: int, path: Path) -> List[NoteRecord]:
        try:
            with path.open("r", encoding=self.encoding) as handle:
                lines = handle.readlines()
        except FileNotFoundError:
            return []

        if not lines:
            return []

        note_lines = [line for line in lines[1:] if line.strip()]
        total_notes = len(note_lines)
        start_index = max(0, total_notes - max(1, limit))
        records: List[NoteRecord] = []
        for idx, line in enumerate(note_lines[start_index:], start=start_index + 1):
            raw = line.rstrip("\n")
            parts = raw.split(",", 3)
            if len(parts) < 4:
                continue
            try:
                trial_number = int(parts[1])
            except ValueError:
                trial_number = 0
            note_text = parts[2]
            try:
                timestamp = float(parts[3])
            except ValueError:
                timestamp = 0.0

            if self._start_timestamp is None and timestamp:
                self._start_timestamp = timestamp

            iso_stamp = datetime.fromtimestamp(timestamp).isoformat(timespec="seconds") if timestamp else ""
            elapsed_display = self.format_elapsed(timestamp - (self._start_timestamp or timestamp))
            records.append(
                NoteRecord(
                    index=idx,
                    trial_number=trial_number,
                    text=note_text,
                    timestamp=timestamp,
                    timestamp_iso=iso_stamp or "",
                    elapsed=elapsed_display,
                    modules="",
                    file_line=raw,
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

    @staticmethod
    def _sanitize_note_text(text: str) -> str:
        normalized = text.replace("\r", "\n")
        segments = [segment.strip() for segment in normalized.split("\n")]
        joined = " ".join(segment for segment in segments if segment)
        return joined.replace(",", "-")


class NotesRuntime(ModuleRuntime):
    """Interactive note-taking runtime built atop the Codex supervisor."""
    MODULE_SUBDIR = "Notes"

    def __init__(self, context: RuntimeContext) -> None:
        self.args = context.args
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
        self.history_limit = max(1, int(getattr(self.args, "history_limit", 200)))
        self.auto_start = bool(getattr(self.args, "auto_start", False))
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

        if self.auto_start:
            self._run_async(self._start_recording())

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

        def builder(parent: tk.Widget) -> None:
            if isinstance(parent, ttk.LabelFrame):
                parent.configure(text="Notes", padding="10")

            parent.grid_columnconfigure(0, weight=1)
            parent.grid_columnconfigure(1, weight=0)
            parent.grid_rowconfigure(0, weight=1)
            parent.grid_rowconfigure(1, weight=0)

            self._history_widget = scrolledtext.ScrolledText(
                parent,
                height=12,
                wrap=tk.WORD,
                state=tk.DISABLED,
            )
            self._history_widget.grid(row=0, column=0, columnspan=2, sticky="nsew", pady=(0, 8))
            self._history_widget.tag_config("timestamp", foreground="#1a237e")
            self._history_widget.tag_config("elapsed", foreground="#1b5e20")
            self._history_widget.tag_config("modules", foreground="#4a148c")

            self._note_entry = ttk.Entry(parent)
            self._note_entry.grid(row=1, column=0, sticky="ew", padx=(0, 8))
            self._note_entry.bind("<Return>", self._on_enter_pressed)

            self._post_button = ttk.Button(
                parent,
                text="Post",
                command=lambda: self._run_async(self._post_note_from_entry()),
            )
            self._post_button.grid(row=1, column=1, sticky="ew")

        self.view.build_stub_content(builder)
        self.view.hide_io_stub()
        self._render_history()

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
