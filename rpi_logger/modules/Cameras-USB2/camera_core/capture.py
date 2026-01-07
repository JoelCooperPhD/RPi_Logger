# USB camera capture
# Task: P2.1

from .types import CaptureFrame


class USBCapture:
    QUEUE_SIZE = 3

    def __init__(
        self,
        device_path: str,
        width: int,
        height: int,
        fps: float,
        pixel_format: str = "MJPG"
    ):
        self._device_path = device_path
        self._width = width
        self._height = height
        self._fps = fps
        self._pixel_format = pixel_format
        self._running = False
        self._actual_fps = 0.0
        # TODO: Complete implementation - Task P2.1

    async def start(self) -> None:
        # TODO: Implement - Task P2.1
        raise NotImplementedError("See docs/tasks/phase2_capture.md P2.1")

    async def stop(self) -> None:
        # TODO: Implement - Task P2.1
        raise NotImplementedError("See docs/tasks/phase2_capture.md P2.1")

    def __aiter__(self):
        return self

    async def __anext__(self) -> CaptureFrame:
        # TODO: Implement - Task P2.1
        raise NotImplementedError("See docs/tasks/phase2_capture.md P2.1")

    @property
    def actual_fps(self) -> float:
        return self._actual_fps

    @property
    def is_running(self) -> bool:
        return self._running
