import tkinter as tk
from tkinter import ttk, scrolledtext
from pathlib import Path
from typing import Dict, Optional, Any


class QuickStatusPanel:
    """Simple monitor mirroring the DRT output CSV file contents."""

    def __init__(self, parent: tk.Misc):
        self.parent = parent
        self.frame: Optional[ttk.LabelFrame] = None
        self.text_widget: Optional[scrolledtext.ScrolledText] = None
        self.device_files: Dict[str, Optional[Path]] = {}
        self.current_file: Optional[Path] = None
        self._module_state: str = "Idle"

    def build(
        self,
        row: int = 0,
        column: int = 0,
        rowspan: int = 1,
        columnspan: int = 1,
        *,
        container: Optional[ttk.LabelFrame] = None
    ) -> ttk.LabelFrame:
        if container is not None:
            frame = container
        else:
            frame = ttk.LabelFrame(self.parent, text="Session Output", padding="3")
            frame.grid(
                row=row,
                column=column,
                rowspan=rowspan,
                columnspan=columnspan,
                sticky='ew'
            )
        frame.columnconfigure(0, weight=1)

        text_widget = scrolledtext.ScrolledText(
            frame,
            height=2,
            wrap=tk.NONE,
            undo=False,
            font=('TkFixedFont', 9),
            bg='#f5f5f5',
            fg='#333333'
        )
        text_widget.grid(row=0, column=0, sticky='ew')
        text_widget.config(state='disabled')

        self.frame = frame
        self.text_widget = text_widget
        return frame

    # ---- Public update helpers -------------------------------------------------

    def set_module_state(self, state: str) -> None:
        self._module_state = state

    def device_connected(self, port: str) -> None:
        self.device_files.setdefault(port, None)

    def device_disconnected(self, port: str) -> None:
        file_path = self.device_files.pop(port, None)
        if file_path and file_path == self.current_file:
            self.current_file = None
            self._set_text('')
        elif not self.device_files:
            self.current_file = None
            self._set_text('')

    def update_logged_trial(self, port: str, log_entry: Dict[str, Any]) -> None:
        file_path_str = log_entry.get('file_path')
        if file_path_str:
            file_path = Path(file_path_str)
            self.device_files[port] = file_path
            self.current_file = file_path
            self._load_file_contents(file_path)
            return

        line = log_entry.get('line') or log_entry.get('raw')
        if line is not None:
            self._append_line(line)

    # ---- Internal helpers ------------------------------------------------------

    def _load_file_contents(self, file_path: Path) -> None:
        try:
            contents = file_path.read_text()
        except OSError:
            contents = ''
        self._set_text(contents)

    def _append_line(self, line: str) -> None:
        if not self.text_widget:
            return
        self.text_widget.config(state='normal')
        if not line.endswith('\n'):
            line = f"{line}\n"
        self.text_widget.insert(tk.END, line)
        self.text_widget.see(tk.END)
        self.text_widget.config(state='disabled')

    def _set_text(self, text: str) -> None:
        if not self.text_widget:
            return
        self.text_widget.config(state='normal')
        self.text_widget.delete('1.0', tk.END)
        if text:
            self.text_widget.insert('1.0', text)
        self.text_widget.see(tk.END)
        self.text_widget.config(state='disabled')
