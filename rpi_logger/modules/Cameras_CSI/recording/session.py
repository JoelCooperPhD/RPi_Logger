from pathlib import Path
from dataclasses import dataclass
import time

from rpi_logger.modules.base.storage_utils import module_filename_prefix

from capture.frame import CapturedFrame
from .timing_writer import TimingCSVWriter
from .encoder import VideoEncoder


@dataclass
class RecordingMetrics:
    frames_recorded: int
    duration_seconds: float
    output_path: Path
    timing_path: Path


class RecordingSession:
    def __init__(
        self,
        session_dir: Path,
        trial_number: int,
        device_id: str,
        resolution: tuple[int, int],
        fps: int,
        label: str = ""
    ):
        self._session_dir = session_dir
        self._trial_number = trial_number
        self._device_id = device_id
        self._resolution = resolution
        self._fps = fps
        self._label = label

        prefix = module_filename_prefix(session_dir, "Cameras_CSI", trial_number, code="CSI")
        safe_name = label.replace(" ", "-").replace(":", "").lower() if label else device_id.replace(":", "_")
        self._video_path = session_dir / f"{prefix}_{safe_name}.avi"
        self._timing_path = session_dir / f"{prefix}_{safe_name}_timing.csv"

        self._encoder = VideoEncoder(self._video_path, resolution, fps)
        self._timing_writer = TimingCSVWriter(self._timing_path, trial_number, device_id, label)

        self._is_recording = False
        self._start_time = 0.0
        self._frame_count = 0

    async def start(self) -> None:
        self._session_dir.mkdir(parents=True, exist_ok=True)
        await self._encoder.start()
        await self._timing_writer.start()
        self._is_recording = True
        self._start_time = time.time()
        self._frame_count = 0

    async def write_frame(self, frame: CapturedFrame) -> None:
        if not self._is_recording:
            return
        await self._encoder.write_frame(frame)
        await self._timing_writer.write_frame(frame)
        self._frame_count += 1

    async def stop(self) -> RecordingMetrics:
        self._is_recording = False
        duration = time.time() - self._start_time if self._start_time else 0.0

        await self._encoder.stop()
        await self._timing_writer.stop()

        return RecordingMetrics(
            frames_recorded=self._frame_count,
            duration_seconds=duration,
            output_path=self._video_path,
            timing_path=self._timing_path,
        )

    @property
    def is_recording(self) -> bool:
        return self._is_recording

    @property
    def frame_count(self) -> int:
        return self._frame_count

    @property
    def video_path(self) -> Path:
        return self._video_path

    @property
    def timing_path(self) -> Path:
        return self._timing_path
