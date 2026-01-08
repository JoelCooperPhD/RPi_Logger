import asyncio
import sys
from pathlib import Path
from typing import Callable, Awaitable, Optional

from rpi_logger.core.logging_utils import LoggerLike, ensure_structured_logger

# Ensure module can find sibling packages when run in various contexts
_module_dir = Path(__file__).resolve().parent.parent
if str(_module_dir) not in sys.path:
    sys.path.insert(0, str(_module_dir))

from core import (
    Action, Effect,
    CameraAssigned, CameraError, RecordingStarted, RecordingStopped,
    UpdateMetrics, PreviewFrameReady,
    ProbeCamera, OpenCamera, CloseCamera,
    StartCapture, StopCapture,
    StartEncoder, StopEncoder,
    StartTimingWriter, StopTimingWriter,
    ApplyCameraSettings, SendStatus, CleanupResources,
    CameraCapabilities, FrameMetrics,
)
from capture import PicamSource, CapturedFrame, HAS_PICAMERA2
from recording import RecordingSession


class EffectExecutor:
    def __init__(
        self,
        status_callback: Callable[[str, dict], None] | None = None,
        settings_save_callback: Callable[..., None] | None = None,
        logger: LoggerLike = None,
    ):
        self._logger = ensure_structured_logger(logger, fallback_name=__name__)
        self._camera: PicamSource | None = None
        self._recording: RecordingSession | None = None
        self._capture_task: asyncio.Task | None = None
        self._status_callback = status_callback
        self._settings_save_callback = settings_save_callback
        self._preview_callback: Callable[[bytes], None] | None = None
        self._record_fps = 5
        self._preview_fps = 10
        self._preview_scale = 0.25  # 1/4 scale default
        self._resolution = (1920, 1080)
        self._camera_id: str = ""

    def set_preview_callback(self, callback: Callable[[bytes], None] | None) -> None:
        self._preview_callback = callback

    async def __call__(
        self,
        effect: Effect,
        dispatch: Callable[[Action], Awaitable[None]]
    ) -> None:
        match effect:
            case ProbeCamera(camera_index):
                await self._probe_camera(camera_index, dispatch)

            case OpenCamera(camera_index, settings):
                self._resolution = settings.resolution
                self._record_fps = settings.record_fps
                self._preview_fps = settings.preview_fps
                self._preview_scale = settings.preview_scale
                await self._open_camera(camera_index, settings.resolution, settings.capture_fps)

            case CloseCamera():
                await self._close_camera()

            case StartCapture():
                self._start_capture_loop(dispatch)

            case StopCapture():
                await self._stop_capture_loop()

            case StartEncoder(output_path, fps, resolution):
                await self._start_recording(output_path, fps, resolution, dispatch)

            case StopEncoder():
                await self._stop_recording(dispatch)

            case StartTimingWriter(output_path):
                pass

            case StopTimingWriter():
                pass

            case ApplyCameraSettings(settings):
                self._resolution = settings.resolution
                self._record_fps = settings.record_fps
                self._preview_fps = settings.preview_fps
                self._preview_scale = settings.preview_scale
                if self._settings_save_callback:
                    self._settings_save_callback(settings)

            case SendStatus(status_type, payload):
                if self._status_callback:
                    self._status_callback(status_type, payload)

            case CleanupResources():
                await self._cleanup()

    async def _probe_camera(
        self,
        camera_index: int,
        dispatch: Callable[[Action], Awaitable[None]]
    ) -> None:
        if not HAS_PICAMERA2:
            self._logger.warning("picamera2 not available")
            await dispatch(CameraError("picamera2 not available"))
            if self._status_callback:
                self._status_callback("camera_error", {"error": "picamera2 not available"})
            return

        try:
            from picamera2 import Picamera2
            cam = Picamera2(camera_index)
            camera_id = cam.camera_properties.get("Model", f"camera_{camera_index}")
            modes = cam.sensor_modes
            cam.close()

            self._camera_id = camera_id
            caps = CameraCapabilities(
                camera_id=camera_id,
                sensor_modes=tuple(modes),
            )
            self._logger.info("Camera probed: %s with %d modes", camera_id, len(modes))
            await dispatch(CameraAssigned(camera_id, camera_index, caps))
            if self._status_callback:
                self._status_callback("camera_assigned", {"camera_id": camera_id})
        except Exception as e:
            self._logger.error("Camera probe failed: %s", e)
            await dispatch(CameraError(str(e)))
            if self._status_callback:
                self._status_callback("camera_error", {"error": str(e)})

    async def _open_camera(
        self,
        camera_index: int,
        resolution: tuple[int, int],
        fps: int
    ) -> None:
        if self._camera:
            await self._camera.stop()

        self._logger.info("Opening camera %d at %dx%d @ %d fps",
                        camera_index, resolution[0], resolution[1], fps)
        self._camera = PicamSource(
            camera_index=camera_index,
            resolution=resolution,
            fps=fps,
        )
        await self._camera.start()

    async def _close_camera(self) -> None:
        if self._camera:
            self._logger.info("Closing camera")
            await self._camera.stop()
            self._camera = None

    def _start_capture_loop(self, dispatch: Callable[[Action], Awaitable[None]]) -> None:
        if self._capture_task and not self._capture_task.done():
            self._logger.debug("Capture task already running")
            return

        self._logger.info("Starting capture loop task")
        self._capture_task = asyncio.create_task(self._capture_loop(dispatch))

    async def _stop_capture_loop(self) -> None:
        if self._capture_task:
            self._capture_task.cancel()
            try:
                await self._capture_task
            except asyncio.CancelledError:
                pass
            self._capture_task = None

    async def _capture_loop(self, dispatch: Callable[[Action], Awaitable[None]]) -> None:
        if not self._camera:
            self._logger.warning("Capture loop: no camera available")
            return

        self._logger.info("Capture loop starting, preview_callback=%s", self._preview_callback is not None)

        frame_count = 0
        record_count = 0
        preview_count = 0
        last_record_time = 0.0
        last_preview_time = 0.0

        async for frame in self._camera.frames():
            frame_count += 1
            now = frame.wall_time

            # Read intervals dynamically so settings changes take effect immediately
            record_interval = 1.0 / self._record_fps if self._record_fps > 0 else 1.0
            preview_interval = 1.0 / self._preview_fps if self._preview_fps > 0 else 0.1

            if self._recording and (now - last_record_time) >= record_interval:
                await self._recording.write_frame(frame)
                record_count += 1
                last_record_time = now

            if self._preview_callback and (now - last_preview_time) >= preview_interval:
                preview_data = self._frame_to_ppm(frame)
                if preview_data:
                    self._preview_callback(preview_data)
                    if preview_count < 3:
                        self._logger.info("Preview frame %d sent, size=%d bytes", preview_count, len(preview_data))
                elif preview_count < 3:
                    self._logger.warning("Preview frame %d: _frame_to_ppm returned None", preview_count)
                preview_count += 1
                last_preview_time = now

            if frame_count % 30 == 0:
                metrics = FrameMetrics(
                    frames_captured=frame_count,
                    frames_recorded=record_count,
                    frames_previewed=preview_count,
                    frames_dropped=self._camera.drop_count,
                    last_frame_time=now,
                    capture_fps_actual=self._camera.hardware_fps,
                )
                await dispatch(UpdateMetrics(metrics))

    def _frame_to_ppm(self, frame: CapturedFrame) -> bytes | None:
        """Convert frame to PPM format for Tkinter PhotoImage.

        Uses preview_scale (default 0.25 = 1/4 scale). Never upscales.
        Handles buffer stride padding (e.g., 1456 -> 1536 for DMA alignment).
        """
        try:
            import cv2
            target_width, target_height = frame.size

            if frame.color_format == "yuv420":
                # YUV420 buffer has stride padding for DMA alignment
                # Shape is (height * 1.5, stride) where stride >= width
                if len(frame.data.shape) == 2:
                    yuv_height, stride = frame.data.shape
                    rgb = cv2.cvtColor(frame.data, cv2.COLOR_YUV2RGB_I420)
                    # Crop to actual image size (remove stride padding)
                    rgb = rgb[:target_height, :target_width]
                else:
                    # Fallback: try to reshape using actual dimensions
                    yuv_height = target_height + target_height // 2
                    yuv = frame.data.reshape((yuv_height, -1))
                    rgb = cv2.cvtColor(yuv, cv2.COLOR_YUV2RGB_I420)
                    rgb = rgb[:target_height, :target_width]
            else:
                rgb = frame.data
                if len(rgb.shape) == 3 and rgb.shape[2] == 3:
                    rgb = cv2.cvtColor(rgb, cv2.COLOR_BGR2RGB)
                # Crop if needed
                rgb = rgb[:target_height, :target_width]

            h, w = rgb.shape[:2]

            # Use preview_scale (default 1/4), never upscale
            scale = min(self._preview_scale, 1.0)
            if scale < 1.0:
                new_w = int(w * scale)
                new_h = int(h * scale)
                if new_w > 0 and new_h > 0:
                    rgb = cv2.resize(rgb, (new_w, new_h), interpolation=cv2.INTER_NEAREST)

            h, w = rgb.shape[:2]
            header = f"P6\n{w} {h}\n255\n".encode('ascii')
            return header + rgb.tobytes()
        except Exception as e:
            self._logger.warning("Preview frame error: %s (format=%s, size=%s, shape=%s)",
                               e, frame.color_format, frame.size, frame.data.shape)
            return None

    async def _start_recording(
        self,
        output_path: Path,
        fps: int,
        resolution: tuple[int, int],
        dispatch: Callable[[Action], Awaitable[None]]
    ) -> None:
        session_dir = output_path.parent
        trial = int(output_path.stem.split('_')[1]) if '_' in output_path.stem else 1

        self._recording = RecordingSession(
            session_dir=session_dir,
            trial_number=trial,
            device_id=self._camera_id or "unknown",
            resolution=resolution,
            fps=fps,
        )
        await self._recording.start()
        await dispatch(RecordingStarted())
        if self._status_callback:
            self._status_callback("recording_started", {
                "video_path": str(output_path),
                "camera_id": self._camera_id,
            })

    async def _stop_recording(self, dispatch: Callable[[Action], Awaitable[None]]) -> None:
        if self._recording:
            await self._recording.stop()
            self._recording = None
        await dispatch(RecordingStopped())
        if self._status_callback:
            self._status_callback("recording_stopped", {
                "camera_id": self._camera_id,
            })

    async def _cleanup(self) -> None:
        await self._stop_capture_loop()
        if self._recording:
            await self._recording.stop()
            self._recording = None
        await self._close_camera()
