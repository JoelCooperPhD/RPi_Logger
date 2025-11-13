"""Device menu helpers for the audio Tk view."""

from __future__ import annotations

import logging
from typing import Awaitable, Callable, Dict

try:  # pragma: no cover - Tk unavailable on some hosts
    import tkinter as tk
except Exception:  # pragma: no cover
    tk = None  # type: ignore

from ..domain import AudioSnapshot

ToggleCoroutine = Callable[[int, bool], Awaitable[None]]
SubmitCoroutine = Callable[[Awaitable[None], str], None]


class DeviceMenuController:
    """Builds and refreshes the Devices menubar entries."""

    def __init__(
        self,
        vmc_view,
        submit_async: SubmitCoroutine,
        logger: logging.Logger,
    ) -> None:
        self._vmc_view = vmc_view
        self._submit = submit_async
        self.logger = logger.getChild("DeviceMenu")
        self._menu: tk.Menu | None = None  # type: ignore[assignment]
        self._menu_vars: Dict[int, "tk.BooleanVar"] = {}

    def refresh(self, snapshot: AudioSnapshot, toggle_callback: ToggleCoroutine) -> None:
        if tk is None:
            return
        menu = self._ensure_menu()
        if menu is None:
            return

        menu.delete(0, tk.END)
        self._menu_vars.clear()

        if not snapshot.devices:
            menu.add_command(label="No devices detected", state=tk.DISABLED)
            return

        for device_id in sorted(snapshot.devices.keys()):
            device = snapshot.devices[device_id]
            var = tk.BooleanVar(value=device_id in snapshot.selected_devices)
            self._menu_vars[device_id] = var

            def _toggle(did=device_id, flag_var=var) -> None:
                try:
                    coro = toggle_callback(did, flag_var.get())
                except Exception:
                    self.logger.debug("Toggle callback failed", exc_info=True)
                    return
                if self._submit:
                    self._submit(coro, f"device_toggle_{did}")

            label = f"Device {device_id}: {device.name} ({device.channels}ch, {device.sample_rate:.0f}Hz)"
            menu.add_checkbutton(label=label, variable=var, command=_toggle)

    def _ensure_menu(self) -> "tk.Menu | None":  # type: ignore[name-defined]
        if tk is None:
            return None
        if self._menu is not None:
            return self._menu
        add_menu = getattr(self._vmc_view, "add_menu", None)
        if not callable(add_menu):
            self.logger.debug("View does not expose add_menu; skipping device menu setup")
            return None
        self._menu = add_menu("Devices")
        return self._menu


__all__ = ["DeviceMenuController"]
