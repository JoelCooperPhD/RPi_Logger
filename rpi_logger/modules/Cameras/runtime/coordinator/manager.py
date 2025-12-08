"""
Worker process manager for the main Cameras process.

Spawns and manages camera worker subprocesses, handles IPC,
and provides async interface for preview frames and commands.
"""
from __future__ import annotations

import asyncio
import atexit
import logging
import multiprocessing
import sys
from dataclasses import dataclass, field
from multiprocessing import Process
from multiprocessing.connection import Connection
from typing import Any, Callable, Dict, Optional, Tuple

# Use spawn context for clean subprocess isolation (avoids fork issues with Tk)
_mp_context = multiprocessing.get_context('spawn')

from rpi_logger.modules.Cameras.worker.shared_preview import (
    PreviewSharedBuffer,
    generate_shm_names,
)

from rpi_logger.modules.Cameras.defaults import (
    DEFAULT_CAPTURE_RESOLUTION,
    DEFAULT_CAPTURE_FPS,
    DEFAULT_RECORD_FPS,
    DEFAULT_PREVIEW_SIZE,
    DEFAULT_PREVIEW_FPS,
    DEFAULT_PREVIEW_JPEG_QUALITY,
)
from rpi_logger.modules.Cameras.worker.protocol import (
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
    Response,
)

logger = logging.getLogger(__name__)


@dataclass
class WorkerHandle:
    """Handle to a running camera worker process."""
    camera_type: str
    camera_id: str
    process: Process
    cmd_conn: Connection  # Main sends, worker receives
    resp_conn: Connection  # Worker sends, main receives

    # State
    state: WorkerState = WorkerState.STARTING
    is_recording: bool = False
    is_previewing: bool = False
    capabilities: dict = field(default_factory=dict)

    # Metrics
    fps_capture: float = 0.0
    fps_encode: float = 0.0
    frames_captured: int = 0
    frames_recorded: int = 0

    # Recording info
    video_path: Optional[str] = None
    csv_path: Optional[str] = None

    # Shared memory for preview (created by main process)
    preview_shm: Optional[PreviewSharedBuffer] = None
    preview_size: Tuple[int, int] = DEFAULT_PREVIEW_SIZE

    # Listener task
    _listener_task: Optional[asyncio.Task] = None


class WorkerManager:
    """
    Manages camera worker processes.

    Spawns workers, routes commands, and delivers preview frames/state updates
    via callbacks.
    """

    def __init__(
        self,
        *,
        on_preview_frame: Optional[Callable[[str, RespPreviewFrame], None]] = None,
        on_state_update: Optional[Callable[[str, RespStateUpdate], None]] = None,
        on_recording_started: Optional[Callable[[str, RespRecordingStarted], None]] = None,
        on_recording_complete: Optional[Callable[[str, RespRecordingComplete], None]] = None,
        on_error: Optional[Callable[[str, RespError], None]] = None,
        on_worker_ready: Optional[Callable[[str, RespReady], None]] = None,
    ) -> None:
        self._workers: Dict[str, WorkerHandle] = {}
        self._on_preview_frame = on_preview_frame
        self._on_state_update = on_state_update
        self._on_recording_started = on_recording_started
        self._on_recording_complete = on_recording_complete
        self._on_error = on_error
        self._on_worker_ready = on_worker_ready
        self._shutdown = False

    @property
    def workers(self) -> Dict[str, WorkerHandle]:
        return self._workers

    def get_worker(self, key: str) -> Optional[WorkerHandle]:
        return self._workers.get(key)

    async def spawn_worker(
        self,
        camera_type: str,
        camera_id: str,
        resolution: tuple[int, int] = DEFAULT_CAPTURE_RESOLUTION,
        fps: float = DEFAULT_CAPTURE_FPS,
        *,
        key: str = "",
        preview_size: Optional[Tuple[int, int]] = None,
    ) -> WorkerHandle:
        """
        Spawn a new camera worker process.

        Args:
            camera_type: "picam" or "usb"
            camera_id: sensor ID or device path
            resolution: capture resolution
            fps: target frame rate
            key: unique key for this worker (defaults to camera_type:camera_id)
            preview_size: preview resolution for Picamera2 lores stream (ISP-scaled)

        Returns:
            WorkerHandle for the spawned worker
        """
        if not key:
            key = f"{camera_type}:{camera_id}"
        logger.info("[MANAGER] spawn_worker called: key=%s type=%s id=%s res=%s fps=%.1f preview=%s",
                   key, camera_type, camera_id, resolution, fps, preview_size)

        if key in self._workers:
            logger.error("[MANAGER] Worker already exists for %s!", key)
            raise ValueError(f"Worker already exists for {key}")

        # Create pipes for IPC (use spawn context for Tk compatibility)
        logger.debug("[MANAGER] Creating IPC pipes (using spawn context)...")
        cmd_parent_conn, cmd_child_conn = _mp_context.Pipe()
        resp_child_conn, resp_parent_conn = _mp_context.Pipe()

        # Spawn worker process using spawn context
        logger.info("[MANAGER] Spawning subprocess for %s (spawn method)...", key)
        process = _mp_context.Process(
            target=_worker_entry,
            args=(cmd_child_conn, resp_child_conn),
            daemon=True,
            name=f"camera-worker-{key}",
        )
        process.start()
        logger.info("[MANAGER] Subprocess started: pid=%d name=%s", process.pid, process.name)

        # Close child ends in parent
        cmd_child_conn.close()
        resp_child_conn.close()

        handle = WorkerHandle(
            camera_type=camera_type,
            camera_id=camera_id,
            process=process,
            cmd_conn=cmd_parent_conn,
            resp_conn=resp_parent_conn,
        )

        # Send initial configuration
        logger.info("[MANAGER] Sending CmdConfigure to worker %s...", key)
        cmd_parent_conn.send(CmdConfigure(
            camera_type=camera_type,
            camera_id=camera_id,
            capture_resolution=resolution,
            capture_fps=fps,
            preview_size=preview_size,  # For Picamera2 ISP-scaled lores stream
        ))
        logger.debug("[MANAGER] CmdConfigure sent")

        # Start listener for responses
        logger.debug("[MANAGER] Starting response listener task...")
        handle._listener_task = asyncio.create_task(
            self._listen_worker(key, handle),
            name=f"worker-listener-{key}",
        )

        self._workers[key] = handle
        logger.info("[MANAGER] Worker spawn complete for %s (pid=%d)", key, process.pid)
        return handle

    async def _listen_worker(self, key: str, handle: WorkerHandle) -> None:
        """Listen for responses from a worker process."""
        logger.info("[LISTENER] Starting listener for %s (pid=%d)", key, handle.process.pid)
        msg_count = 0
        try:
            while handle.process.is_alive() and not self._shutdown:
                if await asyncio.to_thread(handle.resp_conn.poll, 0.1):
                    try:
                        msg: Response = handle.resp_conn.recv()
                        msg_count += 1
                    except EOFError:
                        logger.warning("[LISTENER] Worker %s connection closed (EOF)", key)
                        break
                    except Exception as e:
                        logger.error("[LISTENER] Failed to receive from worker %s: %s", key, e)
                        break

                    # Log message type (but not preview frames to avoid spam)
                    if not isinstance(msg, RespPreviewFrame):
                        logger.debug("[LISTENER] %s: received %s (msg #%d)",
                                    key, type(msg).__name__, msg_count)

                    self._handle_response(key, handle, msg)

            if not handle.process.is_alive():
                logger.warning("[LISTENER] Worker %s process died (pid=%d)", key, handle.process.pid)
        except asyncio.CancelledError:
            logger.debug("[LISTENER] Listener cancelled for %s", key)
        except Exception as e:
            logger.exception("[LISTENER] Worker listener error for %s", key)
        logger.info("[LISTENER] Listener exiting for %s (processed %d messages)", key, msg_count)

    def _handle_response(self, key: str, handle: WorkerHandle, msg: Response) -> None:
        """Process a response message from a worker."""
        if isinstance(msg, RespReady):
            handle.state = WorkerState.IDLE
            handle.capabilities = msg.capabilities
            logger.info("[HANDLER] Worker %s READY - dispatching callback", key)
            if self._on_worker_ready:
                self._on_worker_ready(key, msg)
            else:
                logger.warning("[HANDLER] No on_worker_ready callback registered!")

        elif isinstance(msg, RespPreviewFrame):
            if self._on_preview_frame:
                self._on_preview_frame(key, msg)

        elif isinstance(msg, RespStateUpdate):
            handle.state = msg.state
            handle.is_recording = msg.is_recording
            handle.is_previewing = msg.is_previewing
            handle.fps_capture = msg.fps_capture
            handle.fps_encode = msg.fps_encode
            handle.frames_captured = msg.frames_captured
            handle.frames_recorded = msg.frames_recorded
            if self._on_state_update:
                self._on_state_update(key, msg)

        elif isinstance(msg, RespRecordingStarted):
            handle.video_path = msg.video_path
            handle.csv_path = msg.csv_path
            logger.info("[HANDLER] Recording started for %s: %s @ %.1f fps", key, msg.video_path, msg.actual_fps)
            if self._on_recording_started:
                self._on_recording_started(key, msg)

        elif isinstance(msg, RespRecordingComplete):
            handle.is_recording = False
            logger.info("[HANDLER] Recording complete for %s: %s", key, msg.video_path)
            if self._on_recording_complete:
                self._on_recording_complete(key, msg)

        elif isinstance(msg, RespError):
            logger.error("[HANDLER] Worker %s error: %s (fatal=%s)", key, msg.message, msg.fatal)
            if msg.fatal:
                handle.state = WorkerState.ERROR
            if self._on_error:
                self._on_error(key, msg)

        elif isinstance(msg, RespShutdownAck):
            logger.info("[HANDLER] Worker %s acknowledged shutdown", key)

    # ------------------------------------------------------------------ Commands

    async def start_preview(
        self,
        key: str,
        preview_size: tuple[int, int] = DEFAULT_PREVIEW_SIZE,
        target_fps: float = DEFAULT_PREVIEW_FPS,
        jpeg_quality: int = DEFAULT_PREVIEW_JPEG_QUALITY,
        use_shared_memory: bool = True,
    ) -> None:
        """Start preview streaming from a worker."""
        handle = self._workers.get(key)
        if not handle:
            raise ValueError(f"No worker for {key}")

        shm_name_a = ""
        shm_name_b = ""

        # Create shared memory buffers if requested
        if use_shared_memory:
            # Clean up existing shared memory if size changed
            if handle.preview_shm is not None and handle.preview_size != preview_size:
                logger.info("[MANAGER] Preview size changed, recreating shared memory for %s", key)
                handle.preview_shm.close_and_unlink()
                handle.preview_shm = None

            # Create shared memory if not exists
            if handle.preview_shm is None:
                shm_name_a, shm_name_b = generate_shm_names(key)
                try:
                    handle.preview_shm = PreviewSharedBuffer(
                        name_a=shm_name_a,
                        name_b=shm_name_b,
                        width=preview_size[0],
                        height=preview_size[1],
                        create=True,
                    )
                    handle.preview_size = preview_size
                    logger.info("[MANAGER] Created shared memory for %s: %s, %s",
                               key, shm_name_a, shm_name_b)
                except Exception as e:
                    logger.warning("[MANAGER] Failed to create shared memory for %s: %s, falling back to JPEG", key, e)
                    use_shared_memory = False
            else:
                shm_name_a = handle.preview_shm.name_a
                shm_name_b = handle.preview_shm.name_b

        handle.cmd_conn.send(CmdStartPreview(
            preview_size=preview_size,
            target_fps=target_fps,
            jpeg_quality=jpeg_quality,
            use_shared_memory=use_shared_memory,
            shm_name_a=shm_name_a,
            shm_name_b=shm_name_b,
        ))

    async def stop_preview(self, key: str) -> None:
        """Stop preview streaming from a worker."""
        handle = self._workers.get(key)
        if not handle:
            return
        handle.cmd_conn.send(CmdStopPreview())

    async def start_recording(
        self,
        key: str,
        output_dir: str,
        filename: str,
        resolution: tuple[int, int] = DEFAULT_CAPTURE_RESOLUTION,
        fps: float = DEFAULT_RECORD_FPS,
        overlay_enabled: bool = True,
        trial_number: Optional[int] = None,
        csv_enabled: bool = True,
    ) -> None:
        """Start recording on a worker."""
        handle = self._workers.get(key)
        if not handle:
            raise ValueError(f"No worker for {key}")

        handle.cmd_conn.send(CmdStartRecord(
            output_dir=output_dir,
            filename=filename,
            resolution=resolution,
            fps=fps,
            overlay_enabled=overlay_enabled,
            trial_number=trial_number,
            csv_enabled=csv_enabled,
        ))

    async def stop_recording(self, key: str) -> None:
        """Stop recording on a worker."""
        handle = self._workers.get(key)
        if not handle:
            return
        handle.cmd_conn.send(CmdStopRecord())

    async def shutdown_worker(self, key: str, timeout: float = 5.0) -> None:
        """Gracefully shut down a worker."""
        handle = self._workers.get(key)
        if not handle:
            return

        try:
            handle.cmd_conn.send(CmdShutdown(timeout_sec=timeout))
        except Exception:
            pass

        # Cancel listener
        if handle._listener_task:
            handle._listener_task.cancel()
            try:
                await handle._listener_task
            except asyncio.CancelledError:
                pass

        # Wait for process to exit
        if handle.process.is_alive():
            await asyncio.to_thread(handle.process.join, timeout=timeout)

        # Force kill if still alive
        if handle.process.is_alive():
            logger.warning("Force killing worker %s", key)
            handle.process.terminate()
            await asyncio.to_thread(handle.process.join, timeout=1.0)

        # Clean up shared memory
        if handle.preview_shm is not None:
            try:
                handle.preview_shm.close_and_unlink()
                logger.debug("[MANAGER] Cleaned up shared memory for %s", key)
            except Exception as e:
                logger.warning("[MANAGER] Error cleaning up shared memory for %s: %s", key, e)
            handle.preview_shm = None

        # Close pipes
        try:
            handle.cmd_conn.close()
        except Exception:
            pass
        try:
            handle.resp_conn.close()
        except Exception:
            pass

        self._workers.pop(key, None)
        logger.info("Worker %s shut down", key)

    async def shutdown_all(self, timeout: float = 5.0) -> None:
        """Shut down all workers."""
        self._shutdown = True
        keys = list(self._workers.keys())
        for key in keys:
            await self.shutdown_worker(key, timeout=timeout)


def _worker_entry(cmd_conn: Connection, resp_conn: Connection) -> None:
    """Entry point for worker subprocess."""
    import asyncio
    import logging
    import sys
    import traceback

    # Setup logging in the subprocess
    logging.basicConfig(
        level=logging.DEBUG,
        format="[worker %(process)d] %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    log = logging.getLogger(__name__)
    log.info("[WORKER_ENTRY] Worker subprocess started (pid=%d)", multiprocessing.current_process().pid)

    try:
        log.debug("[WORKER_ENTRY] Importing run_worker...")
        from rpi_logger.modules.Cameras.worker.main import run_worker
        log.debug("[WORKER_ENTRY] Import successful, starting asyncio.run(run_worker)...")
        asyncio.run(run_worker(cmd_conn, resp_conn))
        log.info("[WORKER_ENTRY] run_worker completed normally")
    except KeyboardInterrupt:
        log.info("[WORKER_ENTRY] KeyboardInterrupt received")
    except Exception as e:
        log.error("[WORKER_ENTRY] Worker crashed with exception: %s", e)
        log.error("[WORKER_ENTRY] Traceback:\n%s", traceback.format_exc())
        # Try to send error back to main process
        try:
            from rpi_logger.modules.Cameras.worker.protocol import RespError
            resp_conn.send(RespError(message=f"Worker crash: {e}", fatal=True))
        except Exception:
            pass
    finally:
        log.info("[WORKER_ENTRY] Closing connections...")
        try:
            cmd_conn.close()
        except Exception:
            pass
        try:
            resp_conn.close()
        except Exception:
            pass
        log.info("[WORKER_ENTRY] Worker subprocess exiting")


__all__ = ["WorkerManager", "WorkerHandle"]
