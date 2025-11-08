"""Tkinter view adapter for the Cameras stub runtime."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable, Optional

try:
    import tkinter as tk
    from tkinter import ttk
except Exception:  # pragma: no cover - defensive import
    tk = None  # type: ignore
    ttk = None  # type: ignore

from PIL import Image, ImageTk

try:  # Pillow 10+
    DEFAULT_RESAMPLE = Image.Resampling.BILINEAR
except AttributeError:  # pragma: no cover - legacy Pillow fallback
    DEFAULT_RESAMPLE = Image.BILINEAR  # type: ignore[attr-defined]


class CameraStubViewAdapter:
    """Encapsulates interactions with the StubCodexView and Tk widgets."""

    def __init__(
        self,
        view,
        *,
        preview_size: tuple[int, int],
        task_manager,
        logger: logging.Logger,
    ) -> None:
        self.view = view
        self.preview_size = preview_size
        self.task_manager = task_manager
        self.logger = logger
        self._preview_row: Optional[ttk.Frame] = None
        self._preview_fps_var: Optional[tk.StringVar] = None
        self._preview_fraction_getter: Optional[Callable[[], Optional[float]]] = None
        self._preview_fraction_handler: Optional[Callable[[Optional[float]], Awaitable[None]]] = None
        self._last_metrics_text: Optional[str] = None
        self._frame_logged: set[int] = set()

    # ------------------------------------------------------------------
    # Layout helpers
    # ------------------------------------------------------------------
    def build_camera_grid(self, max_columns: int) -> None:
        if not self.view or tk is None or ttk is None:
            return

        def builder(parent: tk.Widget) -> None:
            if not isinstance(parent, ttk.LabelFrame):
                container = ttk.LabelFrame(parent, text="Cameras", padding="8")
                container.grid(row=0, column=0, sticky="nsew")
                container.columnconfigure(0, weight=1)
                container.rowconfigure(0, weight=1)
            else:
                container = parent
                container.columnconfigure(0, weight=1)
                container.rowconfigure(0, weight=1)

            row = ttk.Frame(container)
            row.grid(row=0, column=0, sticky="nsew")

            total_columns = max(2, int(max_columns or 2))
            uniform_group = "camera_preview_columns"
            for col in range(total_columns):
                row.columnconfigure(col, weight=1, uniform=uniform_group)
            row.rowconfigure(0, weight=1)
            self._preview_row = row

        self.view.build_stub_content(builder)

    def create_preview_slot(self, index: int, title: str) -> tuple[Any, Any, Any]:
        if ttk is None or self._preview_row is None:
            raise RuntimeError("Preview grid not initialized")

        frame = ttk.Frame(self._preview_row)
        frame.grid(row=0, column=index, sticky="nsew", padx=4, pady=4)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)

        holder = tk.Frame(frame, background="#000000", bd=1, relief=tk.SOLID)
        holder.grid(row=0, column=0, sticky="nsew")
        holder.columnconfigure(0, weight=1)
        holder.rowconfigure(0, weight=1)

        label = tk.Label(holder, background="#000000", anchor="center", justify=tk.CENTER)
        label.grid(row=0, column=0, sticky="nsew")
        label.configure(text="Waiting for frames…", fg="#cccccc", font=("TkDefaultFont", 10))
        label._preview_title = title  # type: ignore[attr-defined]

        return frame, holder, label

    def bind_preview_resize(self, frame: Any, callback: Callable[[int, int], None]) -> None:
        if tk is None:
            return

        def _on_configure(event: Any) -> None:
            try:
                width = max(int(event.width), 1)
                height = max(int(event.height), 1)
            except Exception:
                return
            callback(width, height)

        try:
            frame.bind("<Configure>", _on_configure)
        except Exception:  # pragma: no cover - defensive
            pass

    def prime_preview_dimensions(self, frame: Any, callback: Callable[[int, int], None]) -> None:
        def _capture() -> None:
            try:
                width = max(frame.winfo_width(), 1)
                height = max(frame.winfo_height(), 1)
            except Exception:
                return
            callback(width, height)

        try:
            frame.after(0, _capture)
        except Exception:  # pragma: no cover - defensive
            pass

    # ------------------------------------------------------------------
    # Preview FPS menu wiring
    # ------------------------------------------------------------------
    def install_preview_fps_menu(
        self,
        getter: Callable[[], Optional[float]],
        handler: Callable[[Optional[float]], Awaitable[None]],
    ) -> None:
        self._preview_fraction_getter = getter
        self._preview_fraction_handler = handler

        if not self.view or tk is None:
            return
        settings_menu = getattr(self.view, "capture_menu", None)

        if settings_menu is None:
            root = getattr(self.view, "root", None)
            if root is None:
                return
            try:
                menubar_name = root["menu"]
            except Exception:
                return
            if not menubar_name:
                return
            try:
                menubar = root.nametowidget(menubar_name)
            except Exception:
                return
            settings_menu = self._locate_menu(menubar, "Settings")

        if settings_menu is None:
            return

        preview_menu = tk.Menu(settings_menu, tearoff=True)
        var = self._ensure_preview_fps_var()
        for key, label, fraction in self._preview_fraction_options():
            preview_menu.add_radiobutton(
                label=label,
                value=key,
                variable=var,
                command=lambda value=fraction: self._handle_preview_fraction_selection(value),
            )

        settings_menu.add_cascade(label="Preview FPS", menu=preview_menu)

    def refresh_preview_fps_ui(self) -> None:
        if not self._preview_fps_var or not self._preview_fraction_getter:
            return
        key = self._preview_fraction_key_for_value(self._preview_fraction_getter())
        try:
            self._preview_fps_var.set(key)
        except Exception:  # pragma: no cover - defensive
            pass

    def _ensure_preview_fps_var(self) -> tk.StringVar:
        if self._preview_fps_var is not None:
            return self._preview_fps_var
        master = self.view.root if self.view else None
        current = self._preview_fraction_key_for_value(self._preview_fraction_getter()) if self._preview_fraction_getter else "full"
        self._preview_fps_var = tk.StringVar(master=master, value=current)
        return self._preview_fps_var

    def _locate_menu(self, menubar: tk.Menu, label: str) -> Optional[tk.Menu]:
        try:
            end_index = menubar.index("end")
        except Exception:
            return None
        if end_index is None:
            return None
        for index in range(end_index + 1):
            try:
                entry_label = menubar.entrycget(index, "label")
            except Exception:
                continue
            if entry_label != label:
                continue
            try:
                submenu_name = menubar.entrycget(index, "menu")
                if not submenu_name:
                    return None
                return menubar.nametowidget(submenu_name)
            except Exception:
                return None
        return None

    def _preview_fraction_options(self) -> list[tuple[str, str, float]]:
        return [
            ("full", "Full (100%)", 1.0),
            ("half", "Half (50%)", 0.5),
            ("third", "One Third (33%)", 1 / 3),
            ("quarter", "Quarter (25%)", 0.25),
        ]

    def _preview_fraction_key_for_value(self, fraction: Optional[float]) -> str:
        if fraction is None or fraction <= 0:
            return "full"
        for key, _label, value in self._preview_fraction_options():
            if abs(value - fraction) < 1e-3:
                return key
        return "full"

    def _handle_preview_fraction_selection(self, fraction_value: Optional[float]) -> None:
        if not self._preview_fraction_handler:
            return
        if self.task_manager:
            self.task_manager.create(
                self._preview_fraction_handler(fraction_value),
                name="PreviewFractionUpdate",
            )
        else:
            asyncio.create_task(self._preview_fraction_handler(fraction_value))

    # ------------------------------------------------------------------
    # Record toggle & capture menu
    # ------------------------------------------------------------------
    def sync_record_toggle(self, enabled: bool, *, capture_disabled: bool) -> None:
        if not self.view or tk is None:
            return
        record_var = getattr(self.view, "record_enabled_var", None)
        if record_var is None:
            return
        try:
            current = bool(record_var.get())
        except Exception:
            current = None
        if current != enabled:
            try:
                record_var.set(enabled)
            except Exception:  # pragma: no cover - defensive
                pass

        update_menu = getattr(self.view, "_update_capture_menu_state", None)
        if callable(update_menu):
            try:
                update_menu()
            except Exception:  # pragma: no cover - defensive
                pass

        self.set_capture_controls_enabled(not capture_disabled)

    def set_capture_controls_enabled(self, enabled: bool) -> None:
        if not self.view or tk is None:
            return
        menu = getattr(self.view, "capture_menu", None)
        if menu is None:
            return
        state = tk.NORMAL if enabled else tk.DISABLED
        for attr in ("capture_resolution_index", "capture_rate_index"):
            index = getattr(self.view, attr, None)
            if index is None:
                continue
            try:
                menu.entryconfig(index, state=state)
            except Exception:  # pragma: no cover - defensive
                continue

    def configure_capture_menu(self) -> None:
        if not self.view or tk is None:
            return
        menu = getattr(self.view, "capture_menu", None)
        if menu is None:
            return

        try:
            end_index = menu.index("end")
        except Exception:
            end_index = None

        if end_index is None:
            return

        labels_to_remove = {"Enable Frame Capture", "Format", "Quality"}
        removed_any = False
        for index in range(end_index, -1, -1):
            try:
                label = menu.entrycget(index, "label")
            except Exception:
                continue
            if label in labels_to_remove:
                try:
                    menu.delete(index)
                except Exception:
                    continue
                removed_any = True

        if removed_any:
            for attr in (
                "capture_format_menu",
                "capture_quality_menu",
                "capture_format_index",
                "capture_quality_index",
            ):
                if hasattr(self.view, attr):
                    setattr(self.view, attr, None)

        try:
            end_index = menu.index("end")
        except Exception:
            end_index = None

        if end_index is None:
            return

        label_to_index: dict[str, int] = {}
        for idx in range(end_index + 1):
            try:
                label = menu.entrycget(idx, "label")
            except Exception:
                continue
            label_to_index[label] = idx

        self.view.capture_resolution_index = label_to_index.get("Resolution")
        self.view.capture_rate_index = label_to_index.get("Frame Rate")

    # ------------------------------------------------------------------
    # IO metrics display
    # ------------------------------------------------------------------
    def update_pipeline_metrics(
        self,
        *,
        capture_fps: float,
        process_fps: float,
        preview_fps: float,
        storage_fps: float,
    ) -> None:
        if not self.view or tk is None:
            return

        var = getattr(self.view, "io_metrics_var", None)
        root = getattr(self.view, "root", None)
        if var is None or root is None:
            return

        text = self._format_pipeline_metrics(
            capture_fps=capture_fps,
            process_fps=process_fps,
            preview_fps=preview_fps,
            storage_fps=storage_fps,
        )

        if text == self._last_metrics_text:
            return
        self._last_metrics_text = text

        def _update() -> None:
            try:
                var.set(text)
            except tk.TclError:  # pragma: no cover - defensive
                pass

        try:
            root.after(0, _update)
        except Exception:  # pragma: no cover - defensive
            pass

    def _format_pipeline_metrics(
        self,
        *,
        capture_fps: float,
        process_fps: float,
        preview_fps: float,
        storage_fps: float,
    ) -> str:
        def _fmt(value: float) -> str:
            return f"{value:.1f}" if value > 0 else "--"

        return (
            f"Capture FPS: {_fmt(capture_fps)}"
            f" | Process FPS: {_fmt(process_fps)}"
            f" | View FPS: {_fmt(preview_fps)}"
            f" | Save FPS: {_fmt(storage_fps)}"
        )

    # ------------------------------------------------------------------
    # Preview rendering
    # ------------------------------------------------------------------
    def view_is_resizing(self) -> bool:
        view = self.view
        if view and hasattr(view, "is_resizing"):
            try:
                return bool(view.is_resizing())
            except Exception:  # pragma: no cover - defensive
                return False
        return False

    async def display_frame(self, slot, frame: Any, pixel_format: str) -> None:
        if self.view_is_resizing():
            return
        image = await asyncio.to_thread(self._frame_to_image, frame, pixel_format)
        target_size = getattr(slot, "size", self.preview_size) or self.preview_size
        if target_size[0] <= 0 or target_size[1] <= 0:
            target_size = self.preview_size

        if image.size != target_size:
            if slot.index not in self._frame_logged:
                self.logger.info(
                    "Camera %s frame size %s differs from preview slot %s; resizing",
                    slot.index,
                    image.size,
                    target_size,
                )
                self._frame_logged.add(slot.index)
            image = await asyncio.to_thread(image.resize, target_size, DEFAULT_RESAMPLE)
        elif slot.index not in self._frame_logged:
            self.logger.info(
                "Camera %s frame size %s matches preview slot",
                slot.index,
                image.size,
            )
            self._frame_logged.add(slot.index)

        master = self.view.root if self.view else None
        photo = ImageTk.PhotoImage(image, master=master)
        label = getattr(slot, "label", None)
        if label is None:
            return

        def _update() -> None:
            if not label.winfo_exists():
                return
            label.configure(image=photo, text="")
            label.image = photo  # type: ignore[attr-defined]

        try:
            label.after(0, _update)
        except Exception:  # pragma: no cover - defensive
            pass

    def _frame_to_image(self, frame: Any, pixel_format: str) -> Image.Image:
        pixel_format = (pixel_format or "").upper()

        if getattr(frame, "ndim", 0) == 3 and frame.shape[2] == 3:
            if pixel_format in {"BGR888", "RGB888"}:
                return Image.fromarray(frame[..., ::-1], mode="RGB")
            return Image.fromarray(frame, mode="RGB")

        if getattr(frame, "ndim", 0) == 3 and frame.shape[2] == 4:
            if pixel_format == "XBGR8888":
                return Image.fromarray(frame[..., 1:4][..., ::-1], mode="RGB")
            if pixel_format == "XRGB8888":
                return Image.fromarray(frame[..., 1:4], mode="RGB")
            if pixel_format == "ABGR8888":
                return Image.fromarray(frame[..., [3, 2, 1]], mode="RGB")
            if pixel_format == "ARGB8888":
                return Image.fromarray(frame[..., 1:4], mode="RGB")
            return Image.fromarray(frame, mode="RGBA").convert("RGB")

        if getattr(frame, "ndim", 0) == 2:
            return Image.fromarray(frame, mode="L")

        return Image.fromarray(frame).convert("RGB")


__all__ = ["CameraStubViewAdapter"]
