"""Capture and preview configuration helpers for the Cameras controller."""

from __future__ import annotations

from typing import Any, Optional, TYPE_CHECKING

from ...domain.model import CameraModel
from ...logging_utils import get_module_logger

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..slot import CameraSlot
    from ..runtime import CameraController


logger = get_module_logger(__name__)


class CaptureSettingsService:
    """Encapsulates preview and storage cadence adjustments."""

    def __init__(self, controller: "CameraController") -> None:
        self._controller = controller
        self._logger = controller.logger.getChild("capture_settings")

    # ------------------------------------------------------------------
    # Preview cadence helpers

    def clamp_preview_fraction(self, value: float) -> float:
        controller = self._controller
        choices = controller.PREVIEW_FRACTION_CHOICES
        value = max(min(value, choices[0]), choices[-1])
        return min(choices, key=lambda choice: abs(choice - value))

    def fraction_to_stride(self, fraction: float) -> int:
        fraction = self.clamp_preview_fraction(fraction)
        mapping = {1.0: 1, 0.5: 2, 1 / 3: 3, 0.25: 4}
        return mapping.get(fraction, 1)

    def apply_preview_fraction(self) -> None:
        controller = self._controller
        base_interval = (
            controller.save_frame_interval
            if controller.save_frame_interval > 0
            else (1.0 / controller.MAX_SENSOR_FPS)
        )
        fraction = controller.preview_fraction if controller.preview_fraction > 0 else 1.0
        interval = base_interval / fraction
        controller.preview_frame_interval = interval
        controller.preview_stride = self.fraction_to_stride(controller.preview_fraction)
        for slot in controller._previews:
            slot.preview_gate.configure(interval)
            slot.preview_stride = controller.preview_stride
            controller.storage_manager.configure_storage_gate(slot)
        controller.state.preview_fraction = controller.preview_fraction
        if hasattr(controller.args, "preview_fps"):
            if controller.save_frame_interval > 0:
                capture_fps = 1.0 / controller.save_frame_interval
                setattr(controller.args, "preview_fps", round(capture_fps * controller.preview_fraction, 3))
            else:
                setattr(controller.args, "preview_fps", None)
        controller.view_manager.refresh_preview_fps_ui()
        controller.telemetry.request_sensor_sync()

    async def handle_preview_fraction_selection(self, fraction_value: Optional[float]) -> None:
        await self.update_preview_settings({"fraction": fraction_value})

    async def update_preview_settings(self, settings: dict[str, Any]) -> None:
        controller = self._controller
        changed = False
        fraction_raw = settings.get("fraction")
        fps = settings.get("fps")
        interval = settings.get("interval")

        fraction_value = CameraModel._safe_float(fraction_raw)
        if fraction_value is not None and fraction_value > 0:
            new_fraction = self.clamp_preview_fraction(fraction_value)
            if abs(new_fraction - controller.preview_fraction) > 1e-3:
                controller.preview_fraction = new_fraction
                setattr(controller.args, "preview_fraction", new_fraction)
                self.apply_preview_fraction()
                changed = True
        elif fps is not None or interval is not None:
            absolute_interval = self.derive_interval(fps=fps, interval=interval)
            if absolute_interval > 0 and controller.save_frame_interval > 0:
                desired_fraction = controller.save_frame_interval / absolute_interval
                new_fraction = self.clamp_preview_fraction(desired_fraction)
                if abs(new_fraction - controller.preview_fraction) > 1e-3:
                    controller.preview_fraction = new_fraction
                    setattr(controller.args, "preview_fraction", new_fraction)
                    self.apply_preview_fraction()
                    changed = True
            else:
                self._logger.info("Preview FPS adjustments require a configured recording FPS; ignoring request")
        if any(key in settings for key in ("size", "resolution")):
            self._logger.info("Preview resolution controls are disabled; ignoring request")

        if changed:
            await controller.state.persist_module_preferences()

    # ------------------------------------------------------------------
    # Capture/save configuration

    async def update_record_settings(self, settings: dict[str, Any]) -> None:
        controller = self._controller
        enabled = settings.get("enabled")
        directory = settings.get("directory")
        size = settings.get("size")
        fps = settings.get("fps")
        interval = settings.get("interval")
        fmt = settings.get("format")
        quality = settings.get("quality")

        if enabled is not None:
            requested = bool(enabled)
            if controller.save_enabled and not requested:
                self._logger.info("Capture menu disable ignored; recording is controlled by the logger.")
                controller.capture_preferences_enabled = True
            else:
                controller.capture_preferences_enabled = requested
                if requested and not controller.save_enabled:
                    self._logger.info(
                        "Capture menu enabled for configuration. Recording will start when triggered by the logger."
                    )
            controller.view_manager.sync_record_toggle()

        if directory:
            if hasattr(controller.args, "save_dir"):
                setattr(controller.args, "save_dir", directory)
            await controller.storage_manager.update_save_directory(directory)

        if fmt:
            fmt_lower = str(fmt).lower()
            if fmt_lower in {"jpeg", "jpg", "png", "webp"}:
                controller.save_format = fmt_lower
                if hasattr(controller.args, "save_format"):
                    setattr(controller.args, "save_format", fmt_lower)
                self._logger.info("Save format set to %s", controller.save_format)

        if quality is not None:
            q_val = CameraModel._safe_int(quality)
            if q_val is not None:
                controller.save_quality = max(1, min(q_val, 100))
                if hasattr(controller.args, "save_quality"):
                    setattr(controller.args, "save_quality", controller.save_quality)
                self._logger.info("Save quality set to %d", controller.save_quality)

        if fps is not None or interval is not None:
            new_interval = self.derive_interval(fps=fps, interval=interval)
            if new_interval != controller.save_frame_interval:
                controller.save_frame_interval = new_interval
                if hasattr(controller.args, "save_fps"):
                    if new_interval <= 0.0:
                        setattr(controller.args, "save_fps", None)
                    else:
                        setattr(controller.args, "save_fps", round(1.0 / new_interval, 3))
                if new_interval <= 0.0:
                    self._logger.info("Recording FPS uncapped")
                else:
                    self._logger.info(
                        "Recording FPS limited to %.2f (interval %.3fs)",
                        1.0 / new_interval,
                        new_interval,
                    )
                self.apply_preview_fraction()
                await controller.telemetry.sync_sensor_frame_rates()

        if size is not None:
            native_selected = isinstance(size, str) and size.lower() == "native"
            normalized_size: Optional[tuple[int, int]] = None
            if not native_selected:
                normalized_size = controller.setup_manager.normalize_size(size)
                if normalized_size is None:
                    self._logger.warning("Invalid recording resolution selection: %s", size)
                else:
                    self.set_logical_resolution(normalized_size)
                    self.apply_save_resolution_choice(normalized_size, native_selected=False)
            else:
                self.set_logical_resolution(None)
                self.apply_save_resolution_choice(None, native_selected=True)

        await controller.state.persist_module_preferences()
        controller.view_manager.refresh_status()

    def derive_interval(self, *, fps: Any = None, interval: Any = None) -> float:
        controller = self._controller
        if fps is not None:
            try:
                fps_val = float(fps)
            except (TypeError, ValueError):
                fps_val = 0.0
            if fps_val <= 0.0:
                return 0.0
            fps_val = min(fps_val, controller.MAX_SENSOR_FPS)
            return 1.0 / fps_val
        if interval is not None:
            try:
                interval_val = float(interval)
            except (TypeError, ValueError):
                interval_val = 0.0
            if interval_val <= 0.0:
                return 0.0
            interval_val = max(interval_val, 1.0 / controller.MAX_SENSOR_FPS)
            return interval_val
        return 0.0

    def set_logical_resolution(self, size: Optional[tuple[int, int]]) -> None:
        controller = self._controller
        if size is None:
            setattr(controller.args, "save_width", None)
            setattr(controller.args, "save_height", None)
            return

        width, height = size
        setattr(controller.args, "save_width", int(width))
        setattr(controller.args, "save_height", int(height))

    def apply_save_resolution_choice(
        self,
        size: Optional[tuple[int, int]],
        *,
        native_selected: bool,
    ) -> None:
        controller = self._controller
        if native_selected:
            self._logger.info("Preview/save resolution set to native stream size (software)")
        elif size is not None:
            self._logger.info(
                "Preview/save resolution set to %sx%s (software scaling)",
                size[0],
                size[1],
            )

        for slot in controller._previews:
            controller.setup_manager.update_slot_targets(slot)


__all__ = ["CaptureSettingsService"]
