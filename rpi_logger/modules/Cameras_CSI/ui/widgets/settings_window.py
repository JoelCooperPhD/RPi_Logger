import tkinter as tk
from tkinter import ttk
from typing import Callable
from dataclasses import replace

from core import CameraSettings, CameraCapabilities

try:
    from rpi_logger.core.ui.theme.colors import Colors
    from rpi_logger.core.ui.theme.widgets import RoundedButton
    HAS_THEME = True
except ImportError:
    HAS_THEME = False
    Colors = None
    RoundedButton = None


class SettingsWindow(tk.Toplevel):
    PREVIEW_SCALE_OPTIONS = ["1/2", "1/4", "1/8"]
    FRAME_RATE_OPTIONS = ["1", "2", "5", "15", "30", "MAX"]
    PREVIEW_DIVISOR_OPTIONS = ["1/2", "1/4", "1/8"]

    def __init__(
        self,
        parent: tk.Tk,
        current_settings: CameraSettings,
        capabilities: CameraCapabilities | None,
        on_apply: Callable[[CameraSettings], None],
    ):
        super().__init__(parent)
        self.title("CSI Camera Settings")
        self.resizable(False, False)
        self.transient(parent)

        self._current = current_settings
        self._capabilities = capabilities
        self._on_apply = on_apply

        self._bg = Colors.BG_DARK if HAS_THEME else "#1e1e1e"
        self._bg_card = Colors.BG_FRAME if HAS_THEME else "#2d2d2d"
        self._fg = Colors.FG_PRIMARY if HAS_THEME else "#e0e0e0"
        self._fg_muted = Colors.FG_SECONDARY if HAS_THEME else "#888888"
        self._accent = Colors.PRIMARY if HAS_THEME else "#4a9eff"

        self.configure(bg=self._bg)
        self._setup_variables()
        self._setup_ui()
        self._center_window()

    def _setup_variables(self) -> None:
        scale = self._current.preview_scale
        if scale <= 0.125:
            scale_str = "1/8"
        elif scale <= 0.25:
            scale_str = "1/4"
        else:
            scale_str = "1/2"
        self.preview_scale_var = tk.StringVar(value=scale_str)

        frame_rate = self._current.frame_rate
        self.frame_rate_var = tk.StringVar(value="MAX" if frame_rate >= 60 else str(frame_rate))

        divisor = self._current.preview_divisor
        divisor_map = {2: "1/2", 4: "1/4", 8: "1/8"}
        self.preview_divisor_var = tk.StringVar(value=divisor_map.get(divisor, "1/4"))

    def _setup_ui(self) -> None:
        main = tk.Frame(self, bg=self._bg, padx=16, pady=16)
        main.pack(fill=tk.BOTH, expand=True)

        # Camera info header
        if self._capabilities:
            header = tk.Frame(main, bg=self._bg)
            header.pack(fill=tk.X, pady=(0, 12))
            tk.Label(
                header, text=self._capabilities.camera_id,
                bg=self._bg, fg=self._fg, font=("", 11, "bold")
            ).pack(side=tk.LEFT)
            tk.Label(
                header, text="CSI Camera",
                bg=self._bg, fg=self._fg_muted, font=("", 9)
            ).pack(side=tk.RIGHT)

        # Frame rate settings card
        self._build_frame_rate_card(main)

        # Preview settings card
        self._build_preview_card(main)

        # Buttons
        self._build_buttons(main)

    def _build_frame_rate_card(self, parent) -> None:
        card = self._create_card(parent, "Frame Rate")
        res = self._current.resolution

        row = tk.Frame(card, bg=self._bg_card)
        row.pack(fill=tk.X, pady=2)
        tk.Label(row, text="Sensor Resolution", bg=self._bg_card, fg=self._fg_muted, anchor="w").pack(side=tk.LEFT)
        tk.Label(row, text=f"{res[0]} x {res[1]}", bg=self._bg_card, fg=self._fg, anchor="e").pack(side=tk.RIGHT)

        row = tk.Frame(card, bg=self._bg_card)
        row.pack(fill=tk.X, pady=4)
        tk.Label(row, text="Capture Rate", bg=self._bg_card, fg=self._fg, anchor="w").pack(side=tk.LEFT)
        fps_combo = ttk.Combobox(
            row, textvariable=self.frame_rate_var,
            values=self.FRAME_RATE_OPTIONS, state="readonly", width=6
        )
        fps_combo.pack(side=tk.RIGHT)
        tk.Label(row, text="fps", bg=self._bg_card, fg=self._fg_muted).pack(side=tk.RIGHT, padx=(0, 4))

    def _build_preview_card(self, parent) -> None:
        card = self._create_card(parent, "Preview")

        row = tk.Frame(card, bg=self._bg_card)
        row.pack(fill=tk.X, pady=4)
        tk.Label(row, text="Scale", bg=self._bg_card, fg=self._fg, anchor="w").pack(side=tk.LEFT)
        scale_combo = ttk.Combobox(
            row, textvariable=self.preview_scale_var,
            values=self.PREVIEW_SCALE_OPTIONS, state="readonly", width=6
        )
        scale_combo.pack(side=tk.RIGHT)

        row = tk.Frame(card, bg=self._bg_card)
        row.pack(fill=tk.X, pady=4)
        tk.Label(row, text="Rate", bg=self._bg_card, fg=self._fg, anchor="w").pack(side=tk.LEFT)
        divisor_combo = ttk.Combobox(
            row, textvariable=self.preview_divisor_var,
            values=self.PREVIEW_DIVISOR_OPTIONS, state="readonly", width=6
        )
        divisor_combo.pack(side=tk.RIGHT)
        tk.Label(row, text="of capture", bg=self._bg_card, fg=self._fg_muted).pack(side=tk.RIGHT, padx=(0, 4))

    def _create_card(self, parent, title: str) -> tk.Frame:
        outer = tk.Frame(parent, bg=self._bg)
        outer.pack(fill=tk.X, pady=(0, 8))

        tk.Label(
            outer, text=title, bg=self._bg, fg=self._fg_muted,
            font=("", 9), anchor="w"
        ).pack(fill=tk.X, pady=(0, 4))

        card = tk.Frame(outer, bg=self._bg_card, padx=12, pady=10)
        card.pack(fill=tk.X)
        return card

    def _build_buttons(self, parent) -> None:
        btn_frame = tk.Frame(parent, bg=self._bg)
        btn_frame.pack(fill=tk.X, pady=(8, 0))

        # Always use ttk.Button for testability (.invoke() support)
        self.cancel_button = ttk.Button(btn_frame, text="Cancel", command=self.destroy)
        self.cancel_button.pack(side=tk.RIGHT, padx=(8, 0))

        self.apply_button = ttk.Button(btn_frame, text="Apply", command=self._on_apply_click)
        self.apply_button.pack(side=tk.RIGHT)

    def _center_window(self) -> None:
        self.update_idletasks()
        w, h = 300, self.winfo_reqheight()
        self.geometry(f"{w}x{h}")
        x = self.master.winfo_x() + (self.master.winfo_width() - w) // 2
        y = self.master.winfo_y() + (self.master.winfo_height() - h) // 2
        self.geometry(f"+{x}+{y}")

    def _on_apply_click(self) -> None:
        scale_str = self.preview_scale_var.get()
        scale_map = {"1/2": 0.5, "1/4": 0.25, "1/8": 0.125}
        preview_scale = scale_map.get(scale_str, 0.25)

        fps_str = self.frame_rate_var.get()
        frame_rate = 60 if fps_str == "MAX" else int(fps_str)

        divisor_str = self.preview_divisor_var.get()
        divisor_map = {"1/2": 2, "1/4": 4, "1/8": 8}
        preview_divisor = divisor_map.get(divisor_str, 4)

        new_settings = replace(
            self._current,
            frame_rate=frame_rate,
            preview_scale=preview_scale,
            preview_divisor=preview_divisor,
        )

        self._on_apply(new_settings)
        self.destroy()
