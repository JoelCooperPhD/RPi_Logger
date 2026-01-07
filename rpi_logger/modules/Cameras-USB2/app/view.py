# Camera view - main UI
# Task: P5.2

import tkinter as tk
from tkinter import ttk
from typing import Callable


class CameraView:
    def __init__(
        self,
        parent: tk.Widget,
        on_settings: Callable[[], None] | None = None,
        on_control_change: Callable[[str, int], None] | None = None
    ):
        self._parent = parent
        self._on_settings = on_settings
        self._on_control_change = on_control_change
        self._capabilities = None
        # TODO: Complete implementation - Task P5.2

    def build_ui(self) -> tk.Frame:
        # TODO: Implement - Task P5.2
        raise NotImplementedError("See docs/tasks/phase5_preview.md P5.2")

    @property
    def canvas_size(self) -> tuple[int, int]:
        # TODO: Implement - Task P5.2
        return (640, 480)

    def push_frame(self, ppm_data: bytes) -> None:
        # TODO: Implement - Task P5.2
        pass

    def update_metrics(
        self,
        capture_fps: float,
        record_fps: float,
        queue_depth: int,
        target_fps: float = 30.0
    ) -> None:
        # TODO: Implement - Task P5.3
        pass

    def set_camera_name(self, name: str) -> None:
        # TODO: Implement - Task P5.3
        pass

    def set_recording_state(self, recording: bool) -> None:
        # TODO: Implement - Task P5.3
        pass

    def set_capabilities(self, capabilities) -> None:
        self._capabilities = capabilities
