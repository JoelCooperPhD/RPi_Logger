# Camera settings window
# Task: P6.1

import tkinter as tk
from typing import Callable


class CameraSettingsWindow:
    def __init__(
        self,
        parent: tk.Widget,
        capabilities,
        current_settings: dict,
        on_apply: Callable[[dict], None]
    ):
        self._parent = parent
        self._capabilities = capabilities
        self._current = current_settings
        self._on_apply = on_apply
        # TODO: Complete implementation - Task P6.1
        raise NotImplementedError("See docs/tasks/phase6_settings.md P6.1")
