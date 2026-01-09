from typing import Callable, Optional, Any
import logging

from ...core.state import (
    CameraCapabilities, CameraSettings,
    FRAME_RATE_OPTIONS, PREVIEW_DIVISOR_OPTIONS, SAMPLE_RATE_OPTIONS,
)

logger = logging.getLogger(__name__)


class USBSettingsWindow:
    def __init__(
        self,
        parent,
        capabilities: Optional[CameraCapabilities],
        settings: CameraSettings,
        audio_available: bool,
        on_apply: Callable[[CameraSettings], None],
        on_close: Callable[[], None],
    ):
        self._parent = parent
        self._capabilities = capabilities
        self._settings = settings
        self._audio_available = audio_available
        self._on_apply = on_apply
        self._on_close = on_close

        self._window = None
        self._resolution_var = None
        self._fps_var = None
        self._preview_div_var = None
        self._audio_var = None
        self._sample_rate_var = None

        self._build_window()

    def _build_window(self) -> None:
        try:
            import tkinter as tk
            from tkinter import ttk
        except ImportError:
            logger.warning("Tkinter not available")
            return

        self._tk = tk
        self._ttk = ttk

        self._window = tk.Toplevel(self._parent)
        self._window.title("USB Camera Settings")
        self._window.geometry("350x400")
        self._window.resizable(False, False)
        self._window.protocol("WM_DELETE_WINDOW", self._handle_close)

        main_frame = ttk.Frame(self._window, padding=10)
        main_frame.pack(fill="both", expand=True)

        row = 0

        # Camera info
        if self._capabilities:
            info_frame = ttk.LabelFrame(main_frame, text="Camera Info", padding=5)
            info_frame.grid(row=row, column=0, columnspan=2, sticky="ew", pady=5)
            row += 1

            ttk.Label(info_frame, text=f"ID: {self._capabilities.camera_id}").pack(anchor="w")
            ttk.Label(info_frame, text=f"Default: {self._capabilities.default_resolution[0]}x{self._capabilities.default_resolution[1]} @ {self._capabilities.default_fps:.0f}fps").pack(anchor="w")

        # Resolution
        ttk.Label(main_frame, text="Resolution:").grid(row=row, column=0, sticky="w", pady=5)
        self._resolution_var = tk.StringVar(value=f"{self._settings.resolution[0]}x{self._settings.resolution[1]}")
        res_combo = ttk.Combobox(main_frame, textvariable=self._resolution_var, state="readonly", width=15)
        res_combo["values"] = self._get_resolution_options()
        res_combo.grid(row=row, column=1, sticky="e", pady=5)
        row += 1

        # Frame rate
        ttk.Label(main_frame, text="Record FPS:").grid(row=row, column=0, sticky="w", pady=5)
        self._fps_var = tk.StringVar(value=str(self._settings.frame_rate))
        fps_combo = ttk.Combobox(main_frame, textvariable=self._fps_var, state="readonly", width=15)
        fps_combo["values"] = [str(f) for f in FRAME_RATE_OPTIONS]
        fps_combo.grid(row=row, column=1, sticky="e", pady=5)
        row += 1

        # Preview divisor
        ttk.Label(main_frame, text="Preview Scale:").grid(row=row, column=0, sticky="w", pady=5)
        self._preview_div_var = tk.StringVar(value=f"1/{self._settings.preview_divisor}")
        preview_combo = ttk.Combobox(main_frame, textvariable=self._preview_div_var, state="readonly", width=15)
        preview_combo["values"] = [f"1/{d}" for d in PREVIEW_DIVISOR_OPTIONS]
        preview_combo.grid(row=row, column=1, sticky="e", pady=5)
        row += 1

        # Audio section
        audio_frame = ttk.LabelFrame(main_frame, text="Audio", padding=5)
        audio_frame.grid(row=row, column=0, columnspan=2, sticky="ew", pady=10)
        row += 1

        ttk.Label(audio_frame, text="Audio Mode:").grid(row=0, column=0, sticky="w", pady=2)
        self._audio_var = tk.StringVar(value=self._settings.audio_mode)
        audio_combo = ttk.Combobox(audio_frame, textvariable=self._audio_var, state="readonly", width=12)
        audio_combo["values"] = ["auto", "on", "off"]
        audio_combo.grid(row=0, column=1, sticky="e", pady=2)

        ttk.Label(audio_frame, text="Sample Rate:").grid(row=1, column=0, sticky="w", pady=2)
        self._sample_rate_var = tk.StringVar(value=str(self._settings.sample_rate))
        sr_combo = ttk.Combobox(audio_frame, textvariable=self._sample_rate_var, state="readonly", width=12)
        sr_combo["values"] = [str(r) for r in SAMPLE_RATE_OPTIONS]
        sr_combo.grid(row=1, column=1, sticky="e", pady=2)

        if not self._audio_available:
            ttk.Label(audio_frame, text="(No audio device detected)", foreground="gray").grid(
                row=2, column=0, columnspan=2, sticky="w", pady=2
            )

        # Buttons
        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=row, column=0, columnspan=2, pady=20)

        ttk.Button(button_frame, text="Apply", command=self._handle_apply).pack(side="left", padx=5)
        ttk.Button(button_frame, text="Cancel", command=self._handle_close).pack(side="left", padx=5)

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

            fps_str = self._fps_var.get()
            fps = int(fps_str)

            preview_str = self._preview_div_var.get()
            preview_div = int(preview_str.split("/")[1])

            audio_mode = self._audio_var.get()

            sample_rate_str = self._sample_rate_var.get()
            sample_rate = int(sample_rate_str)

            new_settings = CameraSettings(
                resolution=(w, h),
                frame_rate=fps,
                preview_divisor=preview_div,
                preview_scale=1.0 / preview_div,
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
