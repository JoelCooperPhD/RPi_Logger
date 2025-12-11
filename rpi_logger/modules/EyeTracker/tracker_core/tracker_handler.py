import asyncio
from typing import Optional

from rpi_logger.core.logging_utils import get_module_logger

from .gaze_tracker import GazeTracker


class TrackerHandler:
    """Coordinator for the gaze tracker runtime loops and state."""

    def __init__(self, config, device_manager, stream_handler, frame_processor, recording_manager):
        self.logger = get_module_logger("TrackerHandler")
        self.config = config
        self.device_manager = device_manager
        self.stream_handler = stream_handler
        self.frame_processor = frame_processor
        self.recording_manager = recording_manager

        self.gaze_tracker: Optional[GazeTracker] = None
        self._run_task: Optional[asyncio.Task] = None

    def ensure_tracker(self, *, display_enabled: bool) -> GazeTracker:
        """Create the gaze tracker if needed and return it."""
        if self.gaze_tracker is None:
            self.gaze_tracker = GazeTracker(
                self.config,
                device_manager=self.device_manager,
                stream_handler=self.stream_handler,
                frame_processor=self.frame_processor,
                recording_manager=self.recording_manager,
                display_enabled=display_enabled,
            )
        else:
            self.gaze_tracker.display_enabled = display_enabled
        return self.gaze_tracker

    async def start_background(self, *, display_enabled: bool) -> GazeTracker:
        tracker = self.ensure_tracker(display_enabled=display_enabled)
        if self._run_task and not self._run_task.done():
            return tracker

        self._run_task = asyncio.create_task(tracker.run(), name="gaze-tracker-run")
        return tracker

    async def pause(self) -> None:
        if self.gaze_tracker is None:
            return
        await self.gaze_tracker.pause()

    async def resume(self) -> None:
        if self.gaze_tracker is None:
            return
        await self.gaze_tracker.resume()

    def is_paused(self) -> bool:
        if self.gaze_tracker is None:
            return False
        return self.gaze_tracker.is_paused

    def get_display_frame(self):
        if self.gaze_tracker is None:
            return None
        return getattr(self.gaze_tracker, "_latest_display_frame", None)

    def get_display_fps(self) -> float:
        """Get current display output FPS."""
        if self.gaze_tracker is None:
            return 0.0
        return self.gaze_tracker.get_display_fps()

    async def stop(self) -> None:
        if self._run_task and not self._run_task.done():
            self._run_task.cancel()
            try:
                await self._run_task
            except asyncio.CancelledError:
                pass
        self._run_task = None

    async def cleanup(self) -> None:
        await self.stop()
        if self.gaze_tracker is not None:
            try:
                await self.gaze_tracker.cleanup()
            except Exception as exc:  # pragma: no cover - defensive
                self.logger.debug("Gaze tracker cleanup error: %s", exc, exc_info=True)
            finally:
                self.gaze_tracker = None

        # Ensure dependent components are stopped even if tracker never ran
        await self.stream_handler.stop_streaming()
        self.frame_processor.destroy_windows()
