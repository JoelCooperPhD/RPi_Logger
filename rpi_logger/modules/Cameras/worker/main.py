"""
Camera worker main loop - runs in a separate process per camera.

Handles camera capture, video encoding, and preview streaming independently
from the main process, avoiding GIL contention across cameras.
"""
from __future__ import annotations

import asyncio
import logging
import time
from multiprocessing.connection import Connection
from typing import Any, Optional

from rpi_logger.modules.Cameras.defaults import (
    DEFAULT_CAPTURE_RESOLUTION,
    DEFAULT_CAPTURE_FPS,
    DEFAULT_PREVIEW_SIZE,
    DEFAULT_PREVIEW_FPS,
    DEFAULT_PREVIEW_JPEG_QUALITY,
)
from .protocol import (
    WorkerState,
    CmdConfigure,
    CmdStartPreview,
    CmdStopPreview,
    CmdStartRecord,
    CmdStopRecord,
    CmdShutdown,
    RespReady,
    RespPreviewFrame,
    RespStateUpdate,
    RespRecordingStarted,
    RespRecordingComplete,
    RespError,
    RespShutdownAck,
    Command,
)

logger = logging.getLogger(__name__)


class CameraWorker:
    """Manages a single camera's capture, encoding, and preview."""

    def __init__(self, cmd_conn: Connection, resp_conn: Connection) -> None:
        self._cmd_conn = cmd_conn
        self._resp_conn = resp_conn

        self._state = WorkerState.STARTING
        self._running = True
        self._shutdown_requested = False

        # Camera config (set by CmdConfigure)
        self._camera_type: Optional[str] = None
        self._camera_id: Optional[str] = None
        self._capture_resolution: tuple[int, int] = DEFAULT_CAPTURE_RESOLUTION
        self._capture_fps: float = DEFAULT_CAPTURE_FPS

        # Runtime components (initialized after configure)
        self._capture: Any = None  # Capture handle
        self._encoder: Any = None  # Encoder instance
        self._capabilities: dict = {}

        # Preview state
        self._preview_enabled = False
        self._preview_size: tuple[int, int] = DEFAULT_PREVIEW_SIZE
        self._preview_target_fps: float = DEFAULT_PREVIEW_FPS
        self._preview_jpeg_quality: int = DEFAULT_PREVIEW_JPEG_QUALITY
        self._last_preview_time: float = 0.0

        # Recording state
        self._recording = False
        self._record_output_dir: Optional[str] = None
        self._record_filename: Optional[str] = None
        self._record_target_fps: float = 0.0

        # Metrics
        self._frames_captured = 0
        self._frames_recorded = 0
        self._frames_preview_sent = 0
        self._fps_capture = 0.0
        self._fps_encode = 0.0
        self._fps_preview = 0.0
        self._last_state_update = 0.0
        self._capture_wait_ms = 0.0
        self._last_frame_time: float = 0.0

    def _send(self, msg) -> None:
        try:
            self._resp_conn.send(msg)
        except Exception as e:
            logger.error("Failed to send response: %s", e)

    def _send_error(self, message: str, fatal: bool = False) -> None:
        self._send(RespError(message=message, fatal=fatal))
        if fatal:
            self._state = WorkerState.ERROR

    async def run(self) -> None:
        logger.info("Camera worker starting")

        # Wait for initial configuration
        await self._wait_for_configure()
        if not self._running:
            return

        # Initialize camera
        try:
            await self._init_camera()
        except Exception as e:
            self._send_error(f"Failed to initialize camera: {e}", fatal=True)
            return

        self._state = WorkerState.IDLE
        self._send(RespReady(
            camera_type=self._camera_type or "",
            camera_id=self._camera_id or "",
            capabilities=self._capabilities,
        ))

        # Main capture loop
        try:
            await self._capture_loop()
        except asyncio.CancelledError:
            logger.info("Worker cancelled")
        except Exception as e:
            logger.exception("Worker error")
            self._send_error(f"Worker error: {e}", fatal=True)
        finally:
            await self._cleanup()

        self._send(RespShutdownAck())
        logger.info("Camera worker exiting")

    async def _wait_for_configure(self) -> None:
        while self._running and self._camera_type is None:
            if await asyncio.to_thread(self._cmd_conn.poll, 0.1):
                cmd = self._cmd_conn.recv()
                if isinstance(cmd, CmdConfigure):
                    self._camera_type = cmd.camera_type
                    self._camera_id = cmd.camera_id
                    self._capture_resolution = cmd.capture_resolution
                    self._capture_fps = cmd.capture_fps
                    logger.info("Configured: %s/%s", self._camera_type, self._camera_id)
                elif isinstance(cmd, CmdShutdown):
                    self._running = False
                    return

    async def _init_camera(self) -> None:
        from .capture import open_capture
        self._capture, self._capabilities = await open_capture(
            self._camera_type,
            self._camera_id,
            resolution=self._capture_resolution,
            fps=self._capture_fps,
        )

    async def _capture_loop(self) -> None:
        from .preview import compress_preview
        from .encoder import Encoder

        encoder: Optional[Encoder] = None
        frame_times: list[float] = []
        encode_times: list[float] = []
        preview_times: list[float] = []
        wait_times: list[float] = []

        async for frame_data in self._capture.frames():
            if not self._running:
                break

            now = time.monotonic()

            # Track inter-frame wait time
            if self._last_frame_time > 0:
                wait_times.append((now - self._last_frame_time) * 1000.0)
            self._last_frame_time = now

            self._frames_captured += 1
            frame_times.append(now)

            # Process commands (non-blocking)
            while self._cmd_conn.poll(0):
                cmd = self._cmd_conn.recv()
                result = await self._handle_command(cmd, encoder)
                if isinstance(result, Encoder):
                    encoder = result
                elif result == "stop_encoder" and encoder:
                    await self._finalize_recording(encoder)
                    encoder = None

            # Preview: downscale, compress, send
            if self._preview_enabled:
                preview_interval = 1.0 / self._preview_target_fps
                if now - self._last_preview_time >= preview_interval:
                    self._last_preview_time = now
                    self._frames_preview_sent += 1
                    preview_times.append(now)
                    jpeg_bytes = compress_preview(
                        frame_data.data,
                        self._preview_size,
                        quality=self._preview_jpeg_quality,
                        color_format=frame_data.color_format,
                    )
                    self._send(RespPreviewFrame(
                        frame_data=jpeg_bytes,
                        width=self._preview_size[0],
                        height=self._preview_size[1],
                        timestamp=frame_data.wall_time,
                        frame_number=frame_data.frame_number,
                    ))

            # Recording: encode frame
            if self._recording and encoder:
                encoder.write_frame(
                    frame_data.data,
                    timestamp=frame_data.wall_time,
                    pts_time_ns=frame_data.sensor_timestamp_ns or frame_data.monotonic_ns,
                    color_format=frame_data.color_format,
                )
                encode_times.append(now)
                self._frames_recorded += 1

            # Update FPS metrics periodically
            if now - self._last_state_update >= 1.0:
                self._update_fps_metrics(frame_times, encode_times, preview_times, wait_times)
                frame_times.clear()
                encode_times.clear()
                preview_times.clear()
                wait_times.clear()
                self._last_state_update = now
                self._send_state_update()

            if self._shutdown_requested:
                break

        # Finalize any ongoing recording
        if encoder:
            await self._finalize_recording(encoder)

    async def _handle_command(self, cmd: Command, encoder) -> Any:
        if isinstance(cmd, CmdStartPreview):
            self._preview_enabled = True
            self._preview_size = cmd.preview_size
            self._preview_target_fps = cmd.target_fps
            self._preview_jpeg_quality = cmd.jpeg_quality
            self._state = WorkerState.PREVIEWING if not self._recording else WorkerState.RECORDING
            logger.info("Preview started: %s @ %.1f fps", self._preview_size, self._preview_target_fps)

        elif isinstance(cmd, CmdStopPreview):
            self._preview_enabled = False
            self._state = WorkerState.RECORDING if self._recording else WorkerState.IDLE
            logger.info("Preview stopped")

        elif isinstance(cmd, CmdStartRecord):
            from .encoder import Encoder
            if self._recording:
                logger.warning("Already recording, ignoring start command")
                return None

            self._recording = True
            self._record_output_dir = cmd.output_dir
            self._record_filename = cmd.filename
            self._record_target_fps = cmd.fps
            self._frames_recorded = 0
            self._state = WorkerState.RECORDING

            video_path = f"{cmd.output_dir}/{cmd.filename}"
            csv_path = f"{cmd.output_dir}/{cmd.filename.rsplit('.', 1)[0]}_timing.csv" if cmd.csv_enabled else None

            new_encoder = Encoder(
                video_path=video_path,
                resolution=cmd.resolution,
                fps=cmd.fps,
                overlay_enabled=cmd.overlay_enabled,
                csv_path=csv_path,
                trial_number=cmd.trial_number,
            )
            await asyncio.to_thread(new_encoder.start)
            logger.info("Recording started: %s", video_path)

            self._send(RespRecordingStarted(video_path=video_path, csv_path=csv_path))
            return new_encoder

        elif isinstance(cmd, CmdStopRecord):
            if not self._recording:
                logger.warning("Not recording, ignoring stop command")
                return None
            self._recording = False
            self._state = WorkerState.PREVIEWING if self._preview_enabled else WorkerState.IDLE
            return "stop_encoder"

        elif isinstance(cmd, CmdShutdown):
            logger.info("Shutdown requested")
            self._shutdown_requested = True
            self._running = False

        return None

    async def _finalize_recording(self, encoder) -> None:
        from .encoder import Encoder
        if not isinstance(encoder, Encoder):
            return

        video_path = encoder.video_path
        csv_path = encoder.csv_path
        frames_total = self._frames_recorded
        duration = encoder.duration_sec

        await asyncio.to_thread(encoder.stop)
        logger.info("Recording finalized: %s (%d frames, %.1fs)", video_path, frames_total, duration)

        self._send(RespRecordingComplete(
            video_path=video_path,
            csv_path=csv_path,
            frames_total=frames_total,
            duration_sec=duration,
            success=True,
        ))

    def _update_fps_metrics(
        self,
        frame_times: list[float],
        encode_times: list[float],
        preview_times: list[float],
        wait_times: list[float],
    ) -> None:
        if len(frame_times) >= 2:
            duration = frame_times[-1] - frame_times[0]
            if duration > 0:
                self._fps_capture = (len(frame_times) - 1) / duration

        if len(encode_times) >= 2:
            duration = encode_times[-1] - encode_times[0]
            if duration > 0:
                self._fps_encode = (len(encode_times) - 1) / duration
        elif not encode_times:
            self._fps_encode = 0.0

        if len(preview_times) >= 2:
            duration = preview_times[-1] - preview_times[0]
            if duration > 0:
                self._fps_preview = (len(preview_times) - 1) / duration
        elif len(preview_times) == 1:
            self._fps_preview = 1.0
        else:
            self._fps_preview = 0.0

        if wait_times:
            self._capture_wait_ms = sum(wait_times) / len(wait_times)

    def _send_state_update(self) -> None:
        self._send(RespStateUpdate(
            state=self._state,
            is_recording=self._recording,
            is_previewing=self._preview_enabled,
            fps_capture=self._fps_capture,
            fps_encode=self._fps_encode,
            frames_captured=self._frames_captured,
            frames_recorded=self._frames_recorded,
            fps_preview=self._fps_preview,
            target_record_fps=self._record_target_fps,
            target_preview_fps=self._preview_target_fps,
            capture_wait_ms=self._capture_wait_ms,
        ))

    async def _cleanup(self) -> None:
        self._state = WorkerState.STOPPING
        if self._capture:
            try:
                await self._capture.stop()
            except Exception as e:
                logger.warning("Capture cleanup failed: %s", e)


async def run_worker(cmd_conn: Connection, resp_conn: Connection) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="[worker %(process)d] %(levelname)s %(name)s: %(message)s",
    )
    worker = CameraWorker(cmd_conn, resp_conn)
    await worker.run()
