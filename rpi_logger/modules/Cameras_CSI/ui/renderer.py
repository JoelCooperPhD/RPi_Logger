import tkinter as tk
from tkinter import ttk
from typing import Callable, Awaitable
import asyncio

from ..core import (
    AppState, CameraStatus, RecordingStatus,
    Action, AssignCamera, UnassignCamera, StartRecording, StopRecording,
    ApplySettings, Shutdown,
)


BG_DARK = "#2b2b2b"
BG_LIGHT = "#3c3c3c"
TEXT = "#ffffff"
TEXT_DIM = "#999999"
SUCCESS = "#4caf50"
WARNING = "#ff9800"
ERROR = "#f44336"


class Renderer:
    def __init__(
        self,
        root: tk.Tk,
        dispatch: Callable[[Action], Awaitable[None]],
    ):
        self.root = root
        self.dispatch = dispatch
        self._preview_image: tk.PhotoImage | None = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.root.title("CSI Camera")
        self.root.configure(bg=BG_DARK)
        self.root.geometry("800x600")

        main_frame = tk.Frame(self.root, bg=BG_DARK)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        self.preview_canvas = tk.Canvas(
            main_frame,
            bg=BG_DARK,
            highlightthickness=0,
        )
        self.preview_canvas.pack(fill=tk.BOTH, expand=True)

        metrics_frame = tk.Frame(main_frame, bg=BG_LIGHT, height=60)
        metrics_frame.pack(fill=tk.X, pady=(10, 0))
        metrics_frame.pack_propagate(False)

        self._create_metrics_panel(metrics_frame)
        self._create_control_buttons(metrics_frame)

        self.status_var = tk.StringVar(value="IDLE")
        self.status_label = tk.Label(
            main_frame,
            textvariable=self.status_var,
            bg=BG_DARK,
            fg=TEXT,
            font=("TkDefaultFont", 10),
        )
        self.status_label.pack(pady=(5, 0))

    def _create_metrics_panel(self, parent: tk.Frame) -> None:
        metrics_left = tk.Frame(parent, bg=BG_LIGHT)
        metrics_left.pack(side=tk.LEFT, padx=20, pady=10)

        tk.Label(metrics_left, text="Cap In/Max:", bg=BG_LIGHT, fg=TEXT_DIM).grid(row=0, column=0, sticky="w")
        self.cap_var = tk.StringVar(value="0.0 / 0.0")
        self.cap_label = tk.Label(metrics_left, textvariable=self.cap_var, bg=BG_LIGHT, fg=TEXT)
        self.cap_label.grid(row=0, column=1, padx=(5, 20))

        tk.Label(metrics_left, text="Rec Out/Tgt:", bg=BG_LIGHT, fg=TEXT_DIM).grid(row=0, column=2, sticky="w")
        self.rec_var = tk.StringVar(value="0.0 / 0.0")
        self.rec_label = tk.Label(metrics_left, textvariable=self.rec_var, bg=BG_LIGHT, fg=TEXT)
        self.rec_label.grid(row=0, column=3, padx=(5, 20))

        tk.Label(metrics_left, text="Disp/Tgt:", bg=BG_LIGHT, fg=TEXT_DIM).grid(row=0, column=4, sticky="w")
        self.disp_var = tk.StringVar(value="0.0 / 0.0")
        self.disp_label = tk.Label(metrics_left, textvariable=self.disp_var, bg=BG_LIGHT, fg=TEXT)
        self.disp_label.grid(row=0, column=5, padx=(5, 0))

    def _create_control_buttons(self, parent: tk.Frame) -> None:
        btn_frame = tk.Frame(parent, bg=BG_LIGHT)
        btn_frame.pack(side=tk.RIGHT, padx=20, pady=10)

        self.assign_btn = tk.Button(
            btn_frame,
            text="Assign Camera",
            command=lambda: asyncio.create_task(self.dispatch(AssignCamera(0))),
        )
        self.assign_btn.pack(side=tk.LEFT, padx=5)

        self.record_btn = tk.Button(
            btn_frame,
            text="Start Recording",
            command=self._toggle_recording,
            state=tk.DISABLED,
        )
        self.record_btn.pack(side=tk.LEFT, padx=5)

        self.settings_btn = tk.Button(
            btn_frame,
            text="Settings",
            command=self._open_settings,
            state=tk.DISABLED,
        )
        self.settings_btn.pack(side=tk.LEFT, padx=5)

    def _toggle_recording(self) -> None:
        pass

    def _open_settings(self) -> None:
        pass

    def render(self, state: AppState) -> None:
        status_text = state.camera_status.name
        if state.recording_status == RecordingStatus.RECORDING:
            status_text += " | RECORDING"
        if state.camera_id:
            status_text += f" ({state.camera_id})"
        self.status_var.set(status_text)

        metrics = state.metrics
        cap_target = "MAX" if state.settings.frame_rate >= 60 else str(state.settings.frame_rate)
        self.cap_var.set(f"{metrics.capture_fps_actual:.1f} / {cap_target}")
        self.rec_var.set(f"{metrics.frames_recorded} / {state.settings.frame_rate}")
        self.disp_var.set(f"{metrics.frames_previewed} / {state.settings.preview_fps}")

        self._update_fps_colors(state)
        self._update_buttons(state)

    def _update_fps_colors(self, state: AppState) -> None:
        actual = state.metrics.capture_fps_actual
        target = state.settings.frame_rate
        if target > 0:
            ratio = actual / target
            if ratio >= 0.95:
                self.cap_label.configure(fg=SUCCESS)
            elif ratio >= 0.80:
                self.cap_label.configure(fg=WARNING)
            else:
                self.cap_label.configure(fg=ERROR)

    def _update_buttons(self, state: AppState) -> None:
        if state.camera_status == CameraStatus.IDLE:
            self.assign_btn.configure(text="Assign Camera", state=tk.NORMAL)
            self.record_btn.configure(state=tk.DISABLED)
            self.settings_btn.configure(state=tk.DISABLED)
        elif state.camera_status == CameraStatus.STREAMING:
            self.assign_btn.configure(text="Unassign", state=tk.NORMAL)
            self.record_btn.configure(state=tk.NORMAL)
            self.settings_btn.configure(state=tk.NORMAL)

            if state.recording_status == RecordingStatus.RECORDING:
                self.record_btn.configure(text="Stop Recording")
            else:
                self.record_btn.configure(text="Start Recording")

    def update_preview(self, jpeg_data: bytes) -> None:
        try:
            import base64
            b64 = base64.b64encode(jpeg_data).decode('ascii')
            self._preview_image = tk.PhotoImage(data=b64)

            canvas_w = self.preview_canvas.winfo_width()
            canvas_h = self.preview_canvas.winfo_height()
            if canvas_w > 1 and canvas_h > 1:
                self.preview_canvas.delete("all")
                self.preview_canvas.create_image(
                    canvas_w // 2, canvas_h // 2,
                    image=self._preview_image,
                    anchor=tk.CENTER,
                )
        except Exception:
            pass
