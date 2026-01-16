import asyncio
import logging
import time
import threading
from typing import AsyncIterator, Any

from .frame import CapturedFrame
from .frame_buffer import FrameBuffer

logger = logging.getLogger(__name__)

try:
    from picamera2 import Picamera2
    HAS_PICAMERA2 = True
except ImportError:
    HAS_PICAMERA2 = False
    Picamera2 = None


class PicamSource:
    def __init__(
        self,
        camera_index: int = 0,
        resolution: tuple[int, int] = (1920, 1080),
        fps: int = 30,
        buffer_capacity: int = 8
    ):
        if not HAS_PICAMERA2:
            raise RuntimeError("picamera2 not available")

        self._camera_index = camera_index
        self._resolution = resolution
        self._fps = fps
        self._camera: Picamera2 | None = None
        self._buffer = FrameBuffer(capacity=buffer_capacity)
        self._capture_thread: threading.Thread | None = None
        self._running = False
        self._frame_count = 0
        self._drop_count = 0
        self._hardware_fps = 0.0
        self._camera_id = ""

    async def start(self) -> None:
        if self._running:
            return

        logger.info("Opening CSI camera %d at %dx%d @ %d fps",
                    self._camera_index, self._resolution[0], self._resolution[1], self._fps)

        self._camera = Picamera2(self._camera_index)
        self._camera_id = self._camera.camera_properties.get("Model", f"camera_{self._camera_index}")

        frame_duration_us = int(1_000_000 / self._fps)
        config = self._camera.create_video_configuration(
            main={"format": "YUV420", "size": self._resolution},
            controls={"FrameDurationLimits": (frame_duration_us, frame_duration_us)},
            buffer_count=4,
        )
        self._camera.configure(config)
        self._camera.start()

        self._running = True
        self._frame_count = 0
        self._drop_count = 0

        self._capture_thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._capture_thread.start()
        logger.info("CSI camera %s started", self._camera_id)

    async def stop(self) -> None:
        if not self._running:
            return

        logger.debug("Stopping CSI camera %s", self._camera_id)
        self._running = False
        self._buffer.stop()

        if self._capture_thread:
            self._capture_thread.join(timeout=2.0)
            self._capture_thread = None

        if self._camera:
            self._camera.stop()
            self._camera.close()
            self._camera = None

        logger.info("CSI camera %s stopped (frames=%d, drops=%d, fps=%.1f)",
                    self._camera_id, self._frame_count, self.drop_count, self._hardware_fps)

    def _capture_loop(self) -> None:
        last_time = time.monotonic()
        frame_times: list[float] = []

        while self._running and self._camera:
            try:
                request = self._camera.capture_request()
                mono_ns = time.monotonic_ns()
                wall_time = time.time()

                metadata = request.get_metadata()
                sensor_ts = metadata.get("SensorTimestamp", 0)
                sequence = metadata.get("FrameCount", self._frame_count)

                array = request.make_array("main")
                request.release()

                frame = CapturedFrame(
                    data=array,
                    frame_number=self._frame_count,
                    sensor_timestamp_ns=sensor_ts,
                    monotonic_ns=mono_ns,
                    wall_time=wall_time,
                    color_format="yuv420",
                    size=self._resolution,
                    metadata=dict(metadata),
                    sequence_number=sequence,
                )

                if not self._buffer.put_overwrite(frame):
                    self._drop_count += 1

                self._frame_count += 1

                now = time.monotonic()
                frame_times.append(now - last_time)
                last_time = now
                if len(frame_times) > 30:
                    frame_times.pop(0)
                # Start calculating FPS after 3 frames (not 31)
                if len(frame_times) >= 3:
                    avg_interval = sum(frame_times) / len(frame_times)
                    self._hardware_fps = 1.0 / avg_interval if avg_interval > 0 else 0.0

            except Exception as e:
                if self._running:
                    logger.debug("CSI capture error: %s", e)
                    time.sleep(0.001)

    async def frames(self) -> AsyncIterator[CapturedFrame]:
        async for frame in self._buffer.frames():
            yield frame

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def hardware_fps(self) -> float:
        return self._hardware_fps

    @property
    def frame_count(self) -> int:
        return self._frame_count

    @property
    def drop_count(self) -> int:
        return self._drop_count + self._buffer.drops

    @property
    def camera_id(self) -> str:
        return self._camera_id

    def get_capabilities(self) -> dict[str, Any]:
        if not self._camera:
            return {}
        return {
            "camera_id": self._camera_id,
            "sensor_modes": self._camera.sensor_modes,
            "properties": dict(self._camera.camera_properties),
        }
