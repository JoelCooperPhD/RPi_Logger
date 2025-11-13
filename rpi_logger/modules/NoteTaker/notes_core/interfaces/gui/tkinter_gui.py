
import asyncio
import logging
import tkinter as tk
from pathlib import Path
from tkinter import ttk, scrolledtext
from typing import TYPE_CHECKING, Optional

from Modules.base import TkinterGUIBase, TkinterMenuBase, gui_utils

if TYPE_CHECKING:
    from ...notes_system import NotesSystem

logger = logging.getLogger("TkinterGUI")


class TkinterGUI(TkinterGUIBase, TkinterMenuBase):

    def __init__(self, notes_system: 'NotesSystem', args):
        self.system = notes_system
        self.args = args

        # Initialize module-specific attributes before GUI framework
        self.status_label: Optional[tk.Label] = None
        self.elapsed_time_label: Optional[tk.Label] = None
        self.note_count_label: Optional[tk.Label] = None
        self.recording_modules_label: Optional[tk.Label] = None
        self.note_entry: Optional[tk.Text] = None
        self.add_note_button: Optional[ttk.Button] = None
        self.note_history: Optional[scrolledtext.ScrolledText] = None
        self.note_history_visible_var: Optional[tk.BooleanVar] = None

        # Use template method for GUI initialization
        self.initialize_gui_framework(
            title="NoteTaker",
            default_width=600,
            default_height=500,
            menu_bar_kwargs={'include_sources': False}  # No Sources menu needed
        )

        # Setup keyboard shortcuts after widgets are created
        self._setup_keyboard_shortcuts()

    def set_close_handler(self, handler):
        """Allow external code to override the window close handler"""
        self.root.protocol("WM_DELETE_WINDOW", handler)

    def populate_module_menus(self):
        pass

    def on_start_recording(self):
        self._start_recording()

    def on_stop_recording(self):
        self._stop_recording()

    def _create_widgets(self):
        content_frame = self.create_standard_layout(logger_height=3, content_title="Notes")
        content_frame.columnconfigure(0, weight=1)
        content_frame.rowconfigure(0, weight=1)  # Note history (expandable)
        content_frame.rowconfigure(1, weight=0)  # Entry frame (fixed)

        self.note_history_frame = ttk.Frame(content_frame)
        self.note_history_frame.grid(row=0, column=0, sticky='nsew', padx=5, pady=(0, 5))

        self.note_history = scrolledtext.ScrolledText(
            self.note_history_frame,
            height=10,
            wrap=tk.WORD,
            state=tk.DISABLED
        )
        self.note_history.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        self.note_history.tag_config("timestamp", foreground="blue")
        self.note_history.tag_config("elapsed", foreground="green")
        self.note_history.tag_config("modules", foreground="purple")

        entry_frame = ttk.Frame(content_frame)
        entry_frame.grid(row=1, column=0, sticky='ew', padx=5, pady=5)

        entry_box_frame = ttk.Frame(entry_frame)
        entry_box_frame.pack(side=tk.TOP, fill=tk.X)

        self.note_entry = tk.Text(
            entry_box_frame,
            height=1,
            width=50,
            wrap=tk.WORD
        )
        self.note_entry.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.add_note_button = ttk.Button(
            entry_box_frame,
            text="Post",
            command=self._on_add_note,
            state=tk.DISABLED
        )
        self.add_note_button.pack(side=tk.LEFT, padx=5)

        hidden_frame = ttk.Frame(content_frame)
        hidden_frame.grid(row=2, column=0)
        hidden_frame.grid_remove()

        self.status_label = ttk.Label(hidden_frame, text="● Ready")
        self.elapsed_time_label = ttk.Label(hidden_frame, text="00:00:00")
        self.note_count_label = ttk.Label(hidden_frame, text="Notes: 0")
        self.recording_modules_label = ttk.Label(hidden_frame, text="Modules: None")

    def _setup_keyboard_shortcuts(self):
        self.root.bind("<Control-n>", lambda e: self._focus_note_entry())

        self.note_entry.bind("<Return>", self._on_enter_key)


    def _focus_note_entry(self):
        self.note_entry.focus_set()

    def _on_enter_key(self, event):
        if not (event.state & 0x1):  # Shift key flag
            self._on_add_note()
            return "break"  # Prevent newline insertion

    def _start_recording(self):
        asyncio.create_task(self._start_recording_async())

    async def _start_recording_async(self):
        if await self.system.start_recording():
            self.sync_recording_state()
            logger.info("Recording started")
        else:
            logger.error("Failed to start recording")

    def _stop_recording(self):
        asyncio.create_task(self._stop_recording_async())

    async def _stop_recording_async(self):
        if await self.system.stop_recording():
            self.sync_recording_state()
            logger.info("Recording stopped")
        else:
            logger.error("Failed to stop recording")

    def _on_add_note(self):
        if not self.system.recording:
            logger.warning("Cannot add note - recording not active")
            return

        note_text = self.note_entry.get("1.0", tk.END).strip()

        if not note_text:
            logger.warning("Cannot add empty note")
            return

        asyncio.create_task(self._add_note_async(note_text))

    async def _add_note_async(self, note_text: str):
        if await self.system.add_note(note_text):
            self.note_entry.delete("1.0", tk.END)

            await self._refresh_note_history()

            self._update_note_count()

            logger.info("Note added successfully")
        else:
            logger.error("Failed to add note")

    async def _refresh_note_history(self):
        if not self.note_history or not self.system.notes_handler:
            return

        notes = await self.system.notes_handler.get_all_notes()

        self.note_history.config(state=tk.NORMAL)
        self.note_history.delete("1.0", tk.END)

        for i, note in enumerate(notes, 1):
            timestamp = note.get("timestamp", "")
            elapsed = note.get("session_elapsed_time", "")
            modules = note.get("recording_modules", "")
            text = note.get("note_text", "")

            self.note_history.insert(tk.END, f"[{timestamp}] ", "timestamp")
            self.note_history.insert(tk.END, f"[{elapsed}] ", "elapsed")
            if modules:
                self.note_history.insert(tk.END, f"({modules}) ", "modules")
            self.note_history.insert(tk.END, f"{text}\n")

        self.note_history.see(tk.END)

        self.note_history.config(state=tk.DISABLED)

    def _update_note_count(self):
        if self.note_count_label and self.system.notes_handler:
            count = self.system.notes_handler.note_count
            self.note_count_label.config(text=f"Notes: {count}")

    def update_elapsed_time(self):
        if not self.elapsed_time_label or not self.system.notes_handler:
            return

        if self.system.recording:
            elapsed = self.system.notes_handler.get_session_elapsed_time()
            self.elapsed_time_label.config(text=elapsed)

            self._update_recording_modules()

    def _update_recording_modules(self):
        if not self.recording_modules_label or not self.system.notes_handler:
            return

        self.recording_modules_label.config(text="Modules: ...")

    def sync_recording_state(self):
        if self.system.recording:
            self.status_label.config(text="⬤ RECORDING", fg="red")
            self.root.title("NoteTaker - ⬤ RECORDING")
            self.add_note_button.config(state=tk.NORMAL)
            self.note_entry.config(state=tk.NORMAL)

            self._refresh_note_history()
            self._update_note_count()
            self.update_elapsed_time()

        else:
            self.status_label.config(text="● Ready", fg="gray")
            self.root.title("NoteTaker")
            self.add_note_button.config(state=tk.DISABLED)
            self.note_entry.config(state=tk.DISABLED)
            self.elapsed_time_label.config(text="00:00:00")
            self.recording_modules_label.config(text="Modules: None")

    def save_window_geometry_to_config(self):
        config_path = gui_utils.get_module_config_path(Path(__file__))
        gui_utils.save_window_geometry(self.root, config_path)
