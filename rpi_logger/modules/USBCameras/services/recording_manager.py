"""Recording lifecycle coordination for the USB cameras controller."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from rpi_logger.core.logging_utils import ensure_structured_logger


class RecordingManager:
    """Keeps trial context and delegates recording start/stop to the storage manager."""

    def __init__(self, controller, *, storage_manager, logger) -> None:
        self.controller = controller
        self.storage_manager = storage_manager
        self.logger = ensure_structured_logger(
            logger,
            component="RecordingManager",
            fallback_name=f"{__name__}.RecordingManager",
        )
        self._active_trial_number = 0
        self._active_trial_label: str = ""

    # ------------------------------------------------------------------
    # Trial helpers

    @property
    def current_trial_number(self) -> int:
        return self._active_trial_number or 1

    @property
    def current_trial_label(self) -> str:
        return self._active_trial_label

    @staticmethod
    def _normalize_trial_number(value: Any) -> Optional[int]:
        try:
            if value is None:
                return None
            trial = int(value)
            if trial <= 0:
                return None
            return trial
        except (TypeError, ValueError):
            return None

    # ------------------------------------------------------------------
    # Recording lifecycle

    async def start_recording(
        self,
        *,
        directory: Optional[Path | str],
        trial_number: Optional[int],
        trial_label: str,
    ) -> bool:
        normalized_trial = self._normalize_trial_number(trial_number)
        if normalized_trial is None:
            normalized_trial = (self._active_trial_number or 0) + 1

        self._active_trial_number = normalized_trial
        self._active_trial_label = trial_label.strip()

        success = await self.storage_manager.enable_saving(directory)
        if success:
            self.logger.info(
                "Frame saving enabled | trial=%s label=%s",
                self._active_trial_number,
                self._active_trial_label,
            )
        return success

    async def stop_recording(self) -> bool:
        if not self.controller.save_enabled:
            self.logger.info("Stop recording ignored; already inactive")
            return True
        await self.storage_manager.disable_saving()
        self._active_trial_label = ""
        self.logger.info("Frame saving disabled via recording manager")
        return True


__all__ = ["RecordingManager"]
