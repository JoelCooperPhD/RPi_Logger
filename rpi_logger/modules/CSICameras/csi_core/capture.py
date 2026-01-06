"""CSI camera capture using Picamera2 with native H.264 recording."""
from __future__ import annotations

import asyncio
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Optional, Tuple

import cv2
import numpy as np

from rpi_logger.modules.base.camera_types import CaptureFrame, CaptureHandle
from rpi_logger.modules.CSICameras.csi_core.backends.picam_color import get_picam_color_format
from rpi_logger.modules.CSICameras.csi_core.picam_recorder import TimingAwareFfmpegOutput
from rpi_logger.core.logging_utils import get_module_logger

logger = get_module_logger(__name__)

def _capture_debug(msg: str) -> None:
    """Write debug message to unified log file."""
    ts = time.strftime('%H:%M:%S') + f'.{int((time.time() % 1) * 1000):03d}'
    tid = threading.current_thread().name
    pid = os.getpid()
    try:
        with open('/tmp/csi_debug.log', 'a') as f:
            f.write(f"{ts} [CAPTURE] [{pid}:{tid}] {msg}\n")
            f.flush()
    except Exception:
        pass

# Try to import Picamera2 - may not be available on non-Pi platforms
try:
    from picamera2 import Picamera2, MappedArray  # type: ignore
    from picamera2.encoders import H264Encoder  # type: ignore
except Exception:  # pragma: no cover - picamera2 may be absent on non-Pi platforms
    Picamera2 = None  # type: ignore
    MappedArray = None  # type: ignore
    H264Encoder = None  # type: ignore


class PicamCapture(CaptureHandle):
    """Picamera2 capture for Raspberry Pi CSI cameras with native H.264 recording."""

    # Default encoder settings for minimal CPU usage on Pi 5
    DEFAULT_BITRATE = 5_000_000  # 5 Mbps
    DEFAULT_IPERIOD = 30  # I-frame every 30 frames

    def __init__(
        self,
        sensor_id: str,
        resolution: tuple[int, int],
        fps: float,
        lores_size: Optional[Tuple[int, int]] = None,
        overlay_enabled: bool = True,
    ) -> None:
        if Picamera2 is None:
            raise RuntimeError(
                "Picamera2 is not available. "
                "Install with: pip install picamera2"
            )
        self._sensor_id = sensor_id
        self._resolution = resolution
        self._fps = fps
        self._lores_size = lores_size  # If set, enables dual-stream with ISP-scaled lores
        self._overlay_enabled = overlay_enabled
        self._cam = None
        self._running = False
        self._frame_number = 0

        # Recording state (native picamera2 pipeline)
        self._encoder: Optional[Any] = None
        self._output: Optional[TimingAwareFfmpegOutput] = None
        self._recording = False
        self._recording_frame_count = 0

    @property
    def actual_fps(self) -> float:
        """Actual FPS (hardware-enforced)."""
        return self._fps

    @property
    def actual_size(self) -> tuple[int, int]:
        """Actual image size (may be smaller than buffer due to stride padding)."""
        return getattr(self, '_actual_size', self._resolution)

    async def start(self) -> None:
        cam_num = int(self._sensor_id) if self._sensor_id.isdigit() else 0
        logger.info("Opening Picamera2 sensor %s (cam_num=%d)", self._sensor_id, cam_num)
        _capture_debug(f"START_ASYNC sensor={self._sensor_id} cam_num={cam_num}")

        # Run all blocking Picamera2 operations in thread pool
        await asyncio.to_thread(self._start_sync, cam_num)
        _capture_debug(f"START_ASYNC_DONE running=True")
        self._running = True

    def _start_sync(self, cam_num: int) -> None:
        _capture_debug(f"START_SYNC cam_num={cam_num} res={self._resolution} fps={self._fps} lores={self._lores_size}")
        logger.info("Creating Picamera2 instance...")
        _capture_debug(f"CAM_CREATE_START")
        self._cam = Picamera2(camera_num=cam_num)
        _capture_debug(f"CAM_CREATE_DONE")
        logger.info("Creating video configuration: %s @ %.1f fps", self._resolution, self._fps)

        # Build lores config if requested
        lores_config = None
        if self._lores_size is not None:
            lores_config = {
                "size": self._lores_size,
                "format": "YUV420",
                "preserve_ar": False,
            }
            logger.info("Enabling lores stream: %s (YUV420)", self._lores_size)

        # Use YUV420 for main stream - required for H.264 encoding
        # (RGB888 would require conversion, wasting CPU)
        frame_duration_us = int(1_000_000 / self._fps)
        config = self._cam.create_video_configuration(
            main={"size": self._resolution, "format": "YUV420"},
            lores=lores_config,
            buffer_count=6,
            controls={"FrameDurationLimits": (frame_duration_us, frame_duration_us)},
        )

        _capture_debug(f"CONFIG_CREATE_DONE main={config.get('main')} lores={config.get('lores')}")
        logger.info("Configuring camera...")
        _capture_debug("CONFIGURE_START")
        self._cam.configure(config)
        _capture_debug("CONFIGURE_DONE")

        # Get actual image size (vs stride-padded buffer size)
        main_config = self._cam.camera_configuration().get('main', {})
        self._actual_size = main_config.get('size', self._resolution)
        logger.info("Actual image size: %s (buffer may be larger due to stride)", self._actual_size)

        logger.info("Starting camera...")
        _capture_debug("CAM_START_START")
        self._cam.start()
        _capture_debug("CAM_START_DONE")
        # Log camera state after start
        try:
            _capture_debug(f"CAM_STATE started={self._cam.started} camera_config={self._cam.camera_configuration()}")
        except Exception as e:
            _capture_debug(f"CAM_STATE_ERROR {e}")
        logger.info("Camera started successfully")

    def _capture_thread_func(self, queue: "asyncio.Queue[Any]", loop: asyncio.AbstractEventLoop) -> None:
        """Dedicated capture thread that puts frames in a queue.

        Uses capture_request() for proper stream access - works reliably with
        dual stream configuration.
        """
        _capture_debug("CAPTURE_THREAD_START")
        frame_num = 0
        while self._running:
            try:
                # Log camera state before capture (first 3 frames only)
                if frame_num < 3:
                    try:
                        _capture_debug(f"CAPTURE_PRE_STATE frame={frame_num} cam_started={self._cam.started if self._cam else 'N/A'}")
                    except Exception:
                        pass

                # Use capture_request() which returns a CompletedRequest
                # This is more reliable than capture_array() with dual streams
                _capture_debug(f"CAPTURE_REQ_START frame={frame_num}")
                request = self._cam.capture_request()
                _capture_debug(f"CAPTURE_REQ_DONE frame={frame_num} request={type(request).__name__ if request else 'None'}")
                if request is None:
                    _capture_debug(f"CAPTURE_REQ_NONE frame={frame_num}")
                    continue

                frame_num += 1
                monotonic_ns = time.monotonic_ns()
                wall_time = time.time()

                # Get frame array - use lores if configured, otherwise main
                _capture_debug(f"MAKE_ARRAY_START frame={frame_num}")
                if self._lores_size is not None:
                    try:
                        lores_frame = request.make_array("lores")
                        _capture_debug(f"MAKE_ARRAY_DONE frame={frame_num} stream=lores shape={lores_frame.shape}")
                    except Exception as e:
                        _capture_debug(f"MAKE_ARRAY_LORES_FAIL frame={frame_num} err={e}")
                        lores_frame = request.make_array("main")
                        _capture_debug(f"MAKE_ARRAY_DONE frame={frame_num} stream=main shape={lores_frame.shape}")
                else:
                    lores_frame = request.make_array("main")
                    _capture_debug(f"MAKE_ARRAY_DONE frame={frame_num} stream=main shape={lores_frame.shape}")

                # Get metadata
                metadata = request.get_metadata() or {}

                # Release the request buffer back to the camera
                _capture_debug(f"REQUEST_RELEASE frame={frame_num}")
                request.release()

                # Put frame data in queue (thread-safe via call_soon_threadsafe)
                loop.call_soon_threadsafe(
                    queue.put_nowait,
                    (lores_frame, monotonic_ns, wall_time, metadata, lores_frame, frame_num)
                )
                if frame_num <= 5:
                    _capture_debug(f"FRAME_QUEUED frame={frame_num}")
            except Exception as e:
                if self._running:
                    _capture_debug(f"CAPTURE_THREAD_ERROR frame={frame_num} err={type(e).__name__}: {e}")
                    import traceback
                    _capture_debug(f"CAPTURE_THREAD_TRACEBACK\n{traceback.format_exc()}")
                break
        _capture_debug("CAPTURE_THREAD_EXIT")

    async def frames(self) -> AsyncIterator[CaptureFrame]:
        import threading

        _capture_debug(f"FRAMES_START running={self._running}")

        # Create queue and start capture thread
        queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=4)
        loop = asyncio.get_running_loop()
        capture_thread = threading.Thread(
            target=self._capture_thread_func,
            args=(queue, loop),
            daemon=True
        )
        capture_thread.start()
        _capture_debug(f"FRAMES_THREAD_LAUNCHED thread={capture_thread.name}")

        try:
            while self._running:
                try:
                    # Wait for frame from capture thread
                    frame_data = await asyncio.wait_for(queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    if self._frame_number < 10:
                        _capture_debug(f"QUEUE_TIMEOUT frame={self._frame_number + 1} qsize={queue.qsize()}")
                    continue

                frame, monotonic_ns, wall_time, metadata, lores_frame, frame_num = frame_data
                self._frame_number = frame_num
                if self._frame_number <= 5:
                    _capture_debug(f"FRAME_YIELD frame={self._frame_number}")

                sensor_ts = self._extract_sensor_timestamp(metadata)
                # Note: frame IS lores_frame now (YUV420 format)
                # The preview code converts YUV420 to BGR for display
                yield CaptureFrame(
                    data=frame,
                    timestamp=monotonic_ns / 1_000_000_000,
                    frame_number=self._frame_number,
                    monotonic_ns=monotonic_ns,
                    sensor_timestamp_ns=sensor_ts,
                    wall_time=wall_time,
                    color_format="yuv420",  # lores stream is always YUV420
                    lores_data=lores_frame,
                    lores_format="yuv420",
                )
        finally:
            self._running = False  # Signal capture thread to stop

    async def stop(self) -> None:
        self._running = False
        if self._cam:
            try:
                await asyncio.to_thread(self._cam.stop)
            except Exception:
                pass
            try:
                await asyncio.to_thread(self._cam.close)
            except Exception:
                pass
            self._cam = None

    @staticmethod
    def _extract_sensor_timestamp(metadata: dict) -> Optional[int]:
        sensor_ts = metadata.get("SensorTimestamp")
        if isinstance(sensor_ts, (int, float)):
            try:
                return int(sensor_ts)
            except Exception:
                return None
        return None

    def set_control(self, name: str, value: Any) -> bool:
        """Set control value."""
        if not self._cam:
            logger.warning("Cannot set control %s: camera not open", name)
            return False

        try:
            # Handle enum controls - convert string to index if needed
            from rpi_logger.modules.CSICameras.csi_core.backends.picam_backend import PICAM_ENUMS
            if name in PICAM_ENUMS and isinstance(value, str):
                options = PICAM_ENUMS[name]
                if value in options:
                    value = options.index(value)
                else:
                    logger.warning("Invalid enum value %s for %s", value, name)
                    return False

            self._cam.set_controls({name: value})
            logger.debug("Set Picam control %s = %s", name, value)
            return True
        except Exception as e:
            logger.warning("Failed to set Picam control %s: %s", name, e)
            return False

    # -------------------------------------------------------------------------
    # Native H.264 Recording (canonical picamera2 pipeline)
    # -------------------------------------------------------------------------

    async def start_recording(
        self,
        video_path: str,
        csv_path: Optional[str] = None,
        trial_number: Optional[int] = None,
        device_id: str = "",
        bitrate: Optional[int] = None,
    ) -> None:
        """Start H.264 recording using picamera2's native encoder pipeline.

        This uses the canonical picamera2 recording API with H264Encoder
        and FfmpegOutput for zero-copy, CPU-efficient encoding.
        """
        if self._recording:
            logger.warning("Recording already in progress")
            return

        if not self._cam:
            logger.error("Camera not started, cannot begin recording")
            return

        if H264Encoder is None:
            raise RuntimeError("H264Encoder not available")

        logger.info("Starting native H.264 recording: %s", video_path)

        # Create encoder with ultrafast preset for minimal CPU
        effective_bitrate = bitrate or self.DEFAULT_BITRATE
        self._encoder = H264Encoder(
            bitrate=effective_bitrate,
            repeat=True,
            iperiod=self.DEFAULT_IPERIOD,
            framerate=int(self._fps),
        )
        # Set ultrafast preset for minimal CPU usage on Pi 5
        self._encoder.preset = "ultrafast"

        # Create output with timing CSV
        self._output = TimingAwareFfmpegOutput(
            video_path,
            csv_path=csv_path,
            trial_number=trial_number,
            device_id=device_id,
            module_name="CSICameras",
        )

        # Set up overlay callback if enabled
        if self._overlay_enabled:
            self._cam.pre_callback = self._overlay_callback

        # Start recording using picamera2's native API
        await asyncio.to_thread(
            self._cam.start_recording,
            self._encoder,
            self._output,
            name="main",
        )

        self._recording = True
        self._recording_frame_count = 0
        logger.info("Native H.264 recording started: bitrate=%d, preset=ultrafast", effective_bitrate)

    async def stop_recording(self) -> dict:
        """Stop recording and return metrics.

        Returns dict with frame_count, duration_sec, frames_dropped.
        """
        if not self._recording:
            return {"frame_count": 0, "duration_sec": 0.0, "frames_dropped": 0}

        logger.info("Stopping native H.264 recording...")
        self._recording = False

        # Remove overlay callback
        if self._cam:
            self._cam.pre_callback = None

        # Stop the encoder
        try:
            await asyncio.to_thread(self._cam.stop_recording)
        except Exception as e:
            logger.warning("Error stopping recording: %s", e)

        # Collect metrics
        metrics = {
            "frame_count": self._output.frame_count if self._output else 0,
            "duration_sec": self._output.duration_sec if self._output else 0.0,
            "frames_dropped": self._output.frames_dropped if self._output else 0,
        }

        logger.info(
            "Recording stopped: %d frames, %.1f sec",
            metrics["frame_count"],
            metrics["duration_sec"],
        )

        self._encoder = None
        self._output = None

        return metrics

    @property
    def is_recording(self) -> bool:
        """Check if currently recording."""
        return self._recording

    @property
    def recording_frame_count(self) -> int:
        """Get current recording frame count."""
        if self._output:
            return self._output.frame_count
        return 0

    def _overlay_callback(self, request: Any) -> None:
        """Pre-encode callback to burn timestamp overlay into frames.

        This is called by picamera2 before each frame is sent to the encoder.
        Uses MappedArray for zero-copy access to the frame buffer.
        """
        if not self._overlay_enabled or MappedArray is None:
            return

        try:
            # Get current timestamp and frame count
            wall_time = time.time()
            frame_num = self._output.frame_count + 1 if self._output else 0

            # Format overlay text: YYYY-MM-DDTHH:MM:SS.mmm #frame
            dt = datetime.fromtimestamp(wall_time, tz=timezone.utc)
            ms = int((wall_time % 1) * 1000)
            text = f"{dt.strftime('%Y-%m-%dT%H:%M:%S')}.{ms:03d} #{frame_num}"

            # Access frame buffer and draw overlay
            with MappedArray(request, "main") as m:
                # MappedArray provides numpy array access to frame buffer
                # For YUV420, we're writing to the Y plane only (grayscale text)
                frame = m.array
                # Convert to BGR for cv2.putText (it handles the conversion internally)
                cv2.putText(
                    frame,
                    text,
                    (8, 24),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.5,
                    (255, 255, 255),  # White text
                    1,
                    cv2.LINE_AA,
                )
        except Exception as e:
            # Don't let overlay errors stop recording
            logger.debug("Overlay callback error: %s", e)


__all__ = ["PicamCapture"]
