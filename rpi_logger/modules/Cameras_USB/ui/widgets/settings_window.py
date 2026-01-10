import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional
import logging

from ...core.state import (
    CameraCapabilities, CameraSettings,
    FRAME_RATE_OPTIONS, PREVIEW_DIVISOR_OPTIONS, SAMPLE_RATE_OPTIONS,
)

try:
    from rpi_logger.core.ui.theme.colors import Colors
    HAS_THEME = True
except ImportError:
    HAS_THEME = False
    Colors = None

logger = logging.getLogger(__name__)


class USBSettingsWindow:
    PREVIEW_SCALE_OPTIONS = ["1", "1/2", "1/4", "1/8"]

    def __init__(
        self,
        parent,
        capabilities: Optional[CameraCapabilities],
        settings: CameraSettings,
        audio_available: bool,
        on_apply: Callable[[CameraSettings], None],
        on_close: Callable[[], None],
        audio_sample_rates: tuple[int, ...] = (),
    ):
        self._parent = parent
        self._capabilities = capabilities
        self._settings = settings
        self._audio_available = audio_available
        self._on_apply = on_apply
        self._on_close = on_close
        self._audio_sample_rates = audio_sample_rates if audio_sample_rates else SAMPLE_RATE_OPTIONS

        self._bg = Colors.BG_DARK if HAS_THEME else "#2b2b2b"
        self._bg_card = Colors.BG_FRAME if HAS_THEME else "#363636"
        self._fg = Colors.FG_PRIMARY if HAS_THEME else "#ecf0f1"
        self._fg_muted = Colors.FG_SECONDARY if HAS_THEME else "#6c7a89"

        self._window: Optional[tk.Toplevel] = None
        self._resolution_var: Optional[tk.StringVar] = None
        self._fps_var: Optional[tk.StringVar] = None
        self._preview_scale_var: Optional[tk.StringVar] = None
        self._audio_enabled_var: Optional[tk.BooleanVar] = None
        self._sample_rate_var: Optional[tk.StringVar] = None
        self._sample_rate_row: Optional[tk.Frame] = None

        self._build_window()

    def _build_window(self) -> None:
        self._window = tk.Toplevel(self._parent)
        self._window.title("USB Camera Settings")
        self._window.configure(bg=self._bg)
        self._window.resizable(True, True)
        self._window.minsize(300, 250)
        self._window.protocol("WM_DELETE_WINDOW", self._handle_close)

        self._setup_variables()
        self._setup_ui()
        self._center_window()

    def _setup_variables(self) -> None:
        res = self._settings.resolution
        self._resolution_var = tk.StringVar(value=f"{res[0]}x{res[1]}")
        self._fps_var = tk.StringVar(value=str(self._settings.frame_rate))

        divisor = self._settings.preview_divisor
        divisor_map = {1: "1", 2: "1/2", 4: "1/4", 8: "1/8"}
        self._preview_scale_var = tk.StringVar(value=divisor_map.get(divisor, "1/4"))

        self._audio_enabled_var = tk.BooleanVar(value=self._settings.audio_mode != "off")
        if self._settings.sample_rate in self._audio_sample_rates:
            self._sample_rate_var = tk.StringVar(value=str(self._settings.sample_rate))
        else:
            self._sample_rate_var = tk.StringVar(value=str(self._audio_sample_rates[0]))

    def _setup_ui(self) -> None:
        main = tk.Frame(self._window, bg=self._bg, padx=16, pady=16)
        main.pack(fill=tk.BOTH, expand=True)

        # Header
        if self._capabilities:
            header = tk.Frame(main, bg=self._bg)
            header.pack(fill=tk.X, pady=(0, 12))
            tk.Label(
                header, text=self._capabilities.camera_id,
                bg=self._bg, fg=self._fg, font=("", 11, "bold")
            ).pack(side=tk.LEFT)
            tk.Label(
                header, text="USB Camera",
                bg=self._bg, fg=self._fg_muted, font=("", 9)
            ).pack(side=tk.RIGHT)

        # Video settings card
        self._build_video_card(main)

        # Preview settings card
        self._build_preview_card(main)

        # Audio settings card (only if audio available)
        if self._audio_available:
            self._build_audio_card(main)

        # Buttons
        self._build_buttons(main)

    def _build_video_card(self, parent: tk.Frame) -> None:
        card = self._create_card(parent, "Video")

        # Resolution
        row = tk.Frame(card, bg=self._bg_card)
        row.pack(fill=tk.X, pady=2)
        tk.Label(row, text="Resolution", bg=self._bg_card, fg=self._fg).pack(side=tk.LEFT)
        res_combo = ttk.Combobox(
            row, textvariable=self._resolution_var,
            values=self._get_resolution_options(), state="readonly", width=12
        )
        res_combo.pack(side=tk.RIGHT)

        # Frame rate
        row = tk.Frame(card, bg=self._bg_card)
        row.pack(fill=tk.X, pady=4)
        tk.Label(row, text="Record Rate", bg=self._bg_card, fg=self._fg).pack(side=tk.LEFT)
        fps_combo = ttk.Combobox(
            row, textvariable=self._fps_var,
            values=[str(f) for f in FRAME_RATE_OPTIONS], state="readonly", width=6
        )
        fps_combo.pack(side=tk.RIGHT)
        tk.Label(row, text="fps", bg=self._bg_card, fg=self._fg_muted).pack(side=tk.RIGHT, padx=(0, 4))

    def _build_preview_card(self, parent: tk.Frame) -> None:
        card = self._create_card(parent, "Preview")

        row = tk.Frame(card, bg=self._bg_card)
        row.pack(fill=tk.X, pady=4)
        tk.Label(row, text="Scale", bg=self._bg_card, fg=self._fg).pack(side=tk.LEFT)
        scale_combo = ttk.Combobox(
            row, textvariable=self._preview_scale_var,
            values=self.PREVIEW_SCALE_OPTIONS, state="readonly", width=6
        )
        scale_combo.pack(side=tk.RIGHT)

    def _build_audio_card(self, parent: tk.Frame) -> None:
        card = self._create_card(parent, "Audio")

        # Enable audio checkbox
        row = tk.Frame(card, bg=self._bg_card)
        row.pack(fill=tk.X, pady=2)
        audio_cb = tk.Checkbutton(
            row,
            text="Enable Audio",
            variable=self._audio_enabled_var,
            bg=self._bg_card,
            fg=self._fg,
            activebackground=self._bg_card,
            activeforeground=self._fg,
            selectcolor=self._bg,
            command=self._on_audio_toggle,
        )
        audio_cb.pack(side=tk.LEFT)

        # Sample rate row (shown/hidden based on checkbox)
        self._sample_rate_row = tk.Frame(card, bg=self._bg_card)
        tk.Label(
            self._sample_rate_row, text="Sample Rate",
            bg=self._bg_card, fg=self._fg
        ).pack(side=tk.LEFT)
        sr_combo = ttk.Combobox(
            self._sample_rate_row, textvariable=self._sample_rate_var,
            values=[str(r) for r in self._audio_sample_rates], state="readonly", width=8
        )
        sr_combo.pack(side=tk.RIGHT)
        tk.Label(
            self._sample_rate_row, text="Hz",
            bg=self._bg_card, fg=self._fg_muted
        ).pack(side=tk.RIGHT, padx=(0, 4))

        # Show sample rate row if audio is enabled
        if self._audio_enabled_var.get():
            self._sample_rate_row.pack(fill=tk.X, pady=(4, 0))

    def _on_audio_toggle(self) -> None:
        if self._sample_rate_row is None:
            return
        if self._audio_enabled_var.get():
            self._sample_rate_row.pack(fill=tk.X, pady=(4, 0))
        else:
            self._sample_rate_row.pack_forget()

    def _create_card(self, parent: tk.Frame, title: str) -> tk.Frame:
        outer = tk.Frame(parent, bg=self._bg)
        outer.pack(fill=tk.X, pady=(0, 8))

        tk.Label(
            outer, text=title, bg=self._bg, fg=self._fg_muted,
            font=("", 9), anchor="w"
        ).pack(fill=tk.X, pady=(0, 4))

        card = tk.Frame(outer, bg=self._bg_card, padx=12, pady=10)
        card.pack(fill=tk.X)
        return card

    def _build_buttons(self, parent: tk.Frame) -> None:
        btn_frame = tk.Frame(parent, bg=self._bg)
        btn_frame.pack(fill=tk.X, pady=(8, 0), side=tk.BOTTOM)

        ttk.Button(btn_frame, text="Cancel", command=self._handle_close).pack(side=tk.RIGHT, padx=(8, 0))
        ttk.Button(btn_frame, text="Apply", command=self._handle_apply).pack(side=tk.RIGHT)

    def _center_window(self) -> None:
        self._window.update_idletasks()
        w = 320
        h = self._window.winfo_reqheight()
        self._window.geometry(f"{w}x{h}")
        x = self._parent.winfo_x() + (self._parent.winfo_width() - w) // 2
        y = self._parent.winfo_y() + (self._parent.winfo_height() - h) // 2
        self._window.geometry(f"+{x}+{y}")

    def _get_resolution_options(self) -> list[str]:
        if not self._capabilities or not self._capabilities.modes:
            return ["640x480", "1280x720", "1920x1080"]

        resolutions = set()
        for mode in self._capabilities.modes:
            size = mode.get("size", (640, 480))
            resolutions.add(f"{size[0]}x{size[1]}")

        return sorted(resolutions, key=lambda r: int(r.split("x")[0]))

    def _handle_apply(self) -> None:
        try:
            res_str = self._resolution_var.get()
            w, h = map(int, res_str.split("x"))

            fps = int(self._fps_var.get())

            scale_str = self._preview_scale_var.get()
            divisor_map = {"1": 1, "1/2": 2, "1/4": 4, "1/8": 8}
            preview_divisor = divisor_map.get(scale_str, 4)

            audio_mode = "auto" if self._audio_enabled_var.get() else "off"
            sample_rate = int(self._sample_rate_var.get())

            new_settings = CameraSettings(
                resolution=(w, h),
                frame_rate=fps,
                preview_divisor=preview_divisor,
                preview_scale=1.0 / preview_divisor,
                audio_mode=audio_mode,
                sample_rate=sample_rate,
            )

            self._on_apply(new_settings)
            self._handle_close()

        except Exception as e:
            logger.error("Settings apply error: %s", e)

    def _handle_close(self) -> None:
        if self._window:
            self._window.destroy()
            self._window = None
        self._on_close()
