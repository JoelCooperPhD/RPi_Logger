import tkinter as tk
from tkinter import ttk
from typing import Callable
from dataclasses import replace

from core import CameraSettings, CameraCapabilities


BG_DARK = "#2b2b2b"
BG_LIGHT = "#3c3c3c"
TEXT = "#ffffff"


class SettingsWindow(tk.Toplevel):
    RESOLUTION_OPTIONS = [
        "1920x1080",
        "1456x1088",
        "1280x720",
        "640x480",
    ]
    FPS_OPTIONS = ["5", "10", "15", "30", "60"]
    PREVIEW_FPS_OPTIONS = ["1", "2", "5", "10"]
    RECORD_FPS_OPTIONS = ["1", "2", "5", "10", "15", "30"]

    def __init__(
        self,
        parent: tk.Tk,
        current_settings: CameraSettings,
        capabilities: CameraCapabilities | None,
        on_apply: Callable[[CameraSettings], None],
    ):
        super().__init__(parent)
        self.title("CSI Camera Settings")
        self.configure(bg=BG_DARK)
        self.geometry("400x350")
        self.resizable(False, False)

        self._current = current_settings
        self._capabilities = capabilities
        self._on_apply = on_apply

        self._setup_variables()
        self._setup_ui()

    def _setup_variables(self) -> None:
        res_str = f"{self._current.resolution[0]}x{self._current.resolution[1]}"
        self.resolution_var = tk.StringVar(value=res_str)
        self.capture_fps_var = tk.StringVar(value=str(self._current.capture_fps))
        self.preview_fps_var = tk.StringVar(value=str(self._current.preview_fps))
        self.record_fps_var = tk.StringVar(value=str(self._current.record_fps))

    def _setup_ui(self) -> None:
        main_frame = tk.Frame(self, bg=BG_DARK, padx=20, pady=20)
        main_frame.pack(fill=tk.BOTH, expand=True)

        row = 0
        tk.Label(main_frame, text="Resolution:", bg=BG_DARK, fg=TEXT).grid(
            row=row, column=0, sticky="w", pady=5
        )
        self.resolution_combo = ttk.Combobox(
            main_frame,
            textvariable=self.resolution_var,
            values=self.RESOLUTION_OPTIONS,
            state="readonly",
            width=15,
        )
        self.resolution_combo.grid(row=row, column=1, pady=5, padx=(10, 0))

        row += 1
        tk.Label(main_frame, text="Capture FPS:", bg=BG_DARK, fg=TEXT).grid(
            row=row, column=0, sticky="w", pady=5
        )
        self.capture_fps_combo = ttk.Combobox(
            main_frame,
            textvariable=self.capture_fps_var,
            values=self.FPS_OPTIONS,
            state="readonly",
            width=15,
        )
        self.capture_fps_combo.grid(row=row, column=1, pady=5, padx=(10, 0))

        row += 1
        tk.Label(main_frame, text="Preview FPS:", bg=BG_DARK, fg=TEXT).grid(
            row=row, column=0, sticky="w", pady=5
        )
        self.preview_fps_combo = ttk.Combobox(
            main_frame,
            textvariable=self.preview_fps_var,
            values=self.PREVIEW_FPS_OPTIONS,
            state="readonly",
            width=15,
        )
        self.preview_fps_combo.grid(row=row, column=1, pady=5, padx=(10, 0))

        row += 1
        tk.Label(main_frame, text="Record FPS:", bg=BG_DARK, fg=TEXT).grid(
            row=row, column=0, sticky="w", pady=5
        )
        self.record_fps_combo = ttk.Combobox(
            main_frame,
            textvariable=self.record_fps_var,
            values=self.RECORD_FPS_OPTIONS,
            state="readonly",
            width=15,
        )
        self.record_fps_combo.grid(row=row, column=1, pady=5, padx=(10, 0))

        if self._capabilities:
            row += 1
            tk.Label(
                main_frame,
                text=f"Camera: {self._capabilities.camera_id}",
                bg=BG_DARK,
                fg=TEXT,
            ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(20, 5))

        btn_frame = tk.Frame(main_frame, bg=BG_DARK)
        btn_frame.grid(row=row + 1, column=0, columnspan=2, pady=(30, 0))

        self.apply_button = tk.Button(
            btn_frame,
            text="Apply",
            command=self._on_apply_click,
            width=10,
        )
        self.apply_button.pack(side=tk.LEFT, padx=5)

        self.cancel_button = tk.Button(
            btn_frame,
            text="Cancel",
            command=self.destroy,
            width=10,
        )
        self.cancel_button.pack(side=tk.LEFT, padx=5)

    def _on_apply_click(self) -> None:
        res_parts = self.resolution_var.get().split("x")
        resolution = (int(res_parts[0]), int(res_parts[1]))

        new_settings = CameraSettings(
            resolution=resolution,
            capture_fps=int(self.capture_fps_var.get()),
            preview_fps=int(self.preview_fps_var.get()),
            record_fps=int(self.record_fps_var.get()),
        )

        self._on_apply(new_settings)
        self.destroy()
