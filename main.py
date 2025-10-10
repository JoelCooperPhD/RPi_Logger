#!/usr/bin/env python3
"""Async car data logger entrypoint.

This version replaces the legacy multiprocessing controller with an
``asyncio``-driven architecture that focuses on the eye tracker module.
It exclusively uses the Pupil Labs **async** realtime API as documented at
https://pupil-labs.github.io/pl-realtime-api/dev/api/async/ and adds
comprehensive debug logging so that every stage of the data flow can be
observed from the CLI.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import datetime as dt
import logging
import signal
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

import cv2
import numpy as np
from pupil_labs.realtime_api.discovery import discover_devices
from pupil_labs.realtime_api.device import Device
from pupil_labs.realtime_api.streaming.gaze import GazeData, receive_gaze_data
from pupil_labs.realtime_api.streaming.video import receive_video_frames

from cli_utils import (
    add_common_cli_arguments,
    configure_logging,
    ensure_directory,
    positive_float,
)

# ---------------------------------------------------------------------------
# Utility dataclasses
# ---------------------------------------------------------------------------


@dataclass
class SessionInfo:
    """Represents a recording session."""

    name: str
    path: Path


@dataclass
class ModuleStatus:
    """Lightweight status descriptor used by the CLI."""

    state: str = "idle"
    details: Dict[str, Any] = field(default_factory=dict)
    last_update: float = field(default_factory=time.time)


# ---------------------------------------------------------------------------
# Eye tracker module
# ---------------------------------------------------------------------------


class EyeTrackerModule:
    """Async eye tracker interface built on the Pupil Labs async API."""

    def __init__(self, data_root: Path, target_fps: float = 30.0) -> None:
        self.logger = logging.getLogger("eye_tracker")
        self.data_root = data_root
        self.target_fps = target_fps

        self.device: Optional[Device] = None
        self.device_info: Optional[Any] = None
        self.video_url: Optional[str] = None
        self.gaze_url: Optional[str] = None

        self._running = False
        self._connected = False
        self._status = ModuleStatus(state="created")

        self._session: Optional[SessionInfo] = None
        self._session_active = False

        self._gaze_task: Optional[asyncio.Task] = None
        self._video_task: Optional[asyncio.Task] = None
        self._monitor_task: Optional[asyncio.Task] = None
        self._gaze_writer_task: Optional[asyncio.Task] = None
        self._video_writer_task: Optional[asyncio.Task] = None

        self._gaze_queue: Optional[asyncio.Queue[Any]] = None
        self._video_queue: Optional[asyncio.Queue[Any]] = None
        self._queue_sentinel: object = object()

        self._last_gaze: Optional[GazeData] = None
        self._last_frame: Optional[np.ndarray] = None
        self._frame_shape: Optional[tuple[int, int, int]] = None

        self._frame_count = 0
        self._gaze_count = 0
        self._reconnect_attempts = 0

        self._start_time = 0.0
        self._last_metrics_time = 0.0
        self._last_metrics_frame_count = 0
        self._last_metrics_gaze_count = 0
        self._last_frame_time = 0.0
        self._last_gaze_time = 0.0
        self._connect_lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Status helpers
    # ------------------------------------------------------------------

    def _set_status(self, state: str, **details: Any) -> None:
        """Update the exposed status object."""
        self._status.state = state
        self._status.details = details
        self._status.last_update = time.time()
        self.logger.debug("status -> %s | %s", state, details)

    def snapshot(self) -> ModuleStatus:
        """Return a copy of the current module status."""
        details = dict(self._status.details)
        details.update(
            {
                "connected": self._connected,
                "running": self._running,
                "session": self._session.name if self._session else None,
                "frames": self._frame_count,
                "gaze_samples": self._gaze_count,
                "frame_shape": self._frame_shape,
                "last_frame_age": self._age(self._last_frame_time),
                "last_gaze_age": self._age(self._last_gaze_time),
            }
        )
        return ModuleStatus(
            state=self._status.state,
            details=details,
            last_update=self._status.last_update,
        )

    @staticmethod
    def _age(timestamp: float) -> Optional[float]:
        if not timestamp:
            return None
        return round(time.time() - timestamp, 3)

    # ------------------------------------------------------------------
    # Connection and streaming lifecycle
    # ------------------------------------------------------------------

    async def connect(self, timeout_seconds: float = 10.0) -> bool:
        """Discover and connect to the first available Pupil Labs device."""
        if self._connected and self.device and self.video_url and self.gaze_url:
            self.logger.debug("Device already connected")
            return True

        async with self._connect_lock:
            if self._connected and self.device and self.video_url and self.gaze_url:
                self.logger.debug("Device already connected")
                return True

            self.logger.info(
                "Searching for Pupil Labs devices (timeout %.1fs)...", timeout_seconds
            )
        start_time = time.perf_counter()

        try:
            async for device_info in discover_devices(timeout_seconds=timeout_seconds):
                self.logger.info(
                    "Discovered device '%s' at %s:%s",
                    device_info.name,
                    device_info.addresses[0],
                    device_info.port,
                )

                self.device_info = device_info
                self.device = Device.from_discovered_device(device_info)
                self.video_url = f"rtsp://{device_info.addresses[0]}:8086/?camera=world"
                self.gaze_url = f"rtsp://{device_info.addresses[0]}:8086/?camera=gaze"
                self._connected = True
                self._set_status(
                    "connected",
                    device=device_info.name,
                    ip=device_info.addresses[0],
                    port=device_info.port,
                )

                # Basic health check so we fail fast if the device is unhappy
                with contextlib.suppress(Exception):
                    await self.device.get_status()
                    self.logger.debug("Device status query succeeded")

                elapsed = time.perf_counter() - start_time
                self.logger.info("Connected in %.2fs", elapsed)
                return True
        except Exception as exc:  # pragma: no cover - defensive logging
            self.logger.exception("Device discovery failed: %s", exc)
            self._set_status("error", error=str(exc))
            return False

        elapsed = time.perf_counter() - start_time
        self.logger.error("No Pupil Labs device found after %.2fs", elapsed)
        self._set_status("error", error="device_not_found")
        return False

    async def start_streams(self) -> None:
        """Start the RTSP gaze and video streams."""
        if not self._connected or not self.device:
            raise RuntimeError("Cannot start streams before connecting to the device")
        if not self.video_url or not self.gaze_url:
            raise RuntimeError("Missing RTSP URLs for video or gaze stream")
        if self._running:
            self.logger.debug("Stream already running")
            return

        self.logger.info("Starting gaze and video streams")
        self._running = True
        self._start_time = time.time()
        self._last_metrics_time = self._start_time
        self._last_metrics_frame_count = 0
        self._last_metrics_gaze_count = 0

        self._gaze_task = asyncio.create_task(self._gaze_stream_loop(), name="gaze-stream")
        self._video_task = asyncio.create_task(
            self._video_stream_loop(), name="video-stream"
        )
        self._monitor_task = asyncio.create_task(
            self._metrics_monitor_loop(), name="eye-metrics"
        )
        self._set_status("streaming")

    async def stop(self) -> None:
        """Stop streaming and release device resources."""
        if not self._running and not self._connected:
            return

        self.logger.info("Stopping eye tracker module")
        await self.stop_session()

        self._running = False
        tasks = [self._gaze_task, self._video_task, self._monitor_task]
        for task in tasks:
            if task and not task.done():
                task.cancel()

        await asyncio.gather(*[t for t in tasks if t], return_exceptions=True)

        self._gaze_task = None
        self._video_task = None
        self._monitor_task = None

        if self.device:
            with contextlib.suppress(Exception):
                await self.device.close()
        self.device = None
        self._connected = False
        self._set_status("stopped")

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    def can_record(self) -> bool:
        return self._running and self._connected

    def is_connected(self) -> bool:
        return self._connected and self.device is not None

    def is_streaming(self) -> bool:
        return self._running

    async def start_session(self, session: SessionInfo) -> None:
        if not self.can_record():
            raise RuntimeError("Eye tracker is not streaming; cannot start session")
        if self._session_active:
            raise RuntimeError("Recording session already active")

        eye_dir = session.path / "eye_tracker"
        eye_dir.mkdir(parents=True, exist_ok=True)

        self._gaze_queue = asyncio.Queue(maxsize=5000)
        self._video_queue = asyncio.Queue(maxsize=300)
        self._session = session
        self._session_active = True

        self._gaze_writer_task = asyncio.create_task(
            self._gaze_writer_loop(eye_dir), name="gaze-writer"
        )
        self._video_writer_task = asyncio.create_task(
            self._video_writer_loop(eye_dir), name="video-writer"
        )

        self._set_status("recording", session=session.name)
        self.logger.info("Recording eye tracker data into %s", eye_dir)

    async def stop_session(self) -> None:
        if not self._session_active:
            return

        self.logger.info("Stopping eye tracker recording")
        self._session_active = False

        if self._gaze_queue:
            await self._gaze_queue.put(self._queue_sentinel)
        if self._video_queue:
            await self._video_queue.put(self._queue_sentinel)

        await asyncio.gather(
            *[t for t in (self._gaze_writer_task, self._video_writer_task) if t],
            return_exceptions=True,
        )

        self._gaze_queue = None
        self._video_queue = None
        self._gaze_writer_task = None
        self._video_writer_task = None
        self._session = None
        self._set_status("streaming")

    # ------------------------------------------------------------------
    # Streaming loops
    # ------------------------------------------------------------------

    async def _gaze_stream_loop(self) -> None:
        assert self.gaze_url is not None
        while self._running:
            try:
                async for datum in receive_gaze_data(self.gaze_url):
                    if not self._running:
                        break
                    await self._handle_gaze_sample(datum)
            except asyncio.CancelledError:
                break
            except Exception as exc:  # pragma: no cover - defensive logging
                self._reconnect_attempts += 1
                self.logger.exception("Gaze stream error (%d): %s", self._reconnect_attempts, exc)
                await asyncio.sleep(1.0)
            else:
                if self._running:
                    self.logger.warning("Gaze stream ended unexpectedly; retrying...")
                    await asyncio.sleep(1.0)

    async def _video_stream_loop(self) -> None:
        assert self.video_url is not None
        while self._running:
            try:
                async for frame in receive_video_frames(self.video_url):
                    if not self._running:
                        break
                    await self._handle_video_frame(frame)
            except asyncio.CancelledError:
                break
            except Exception as exc:  # pragma: no cover - defensive logging
                self._reconnect_attempts += 1
                self.logger.exception(
                    "Video stream error (%d): %s", self._reconnect_attempts, exc
                )
                await asyncio.sleep(1.0)
            else:
                if self._running:
                    self.logger.warning("Video stream ended unexpectedly; retrying...")
                    await asyncio.sleep(1.0)

    async def _metrics_monitor_loop(self) -> None:
        while self._running:
            await asyncio.sleep(1.0)
            now = time.time()
            interval = max(now - self._last_metrics_time, 1e-6)
            frame_rate = (
                self._frame_count - self._last_metrics_frame_count
            ) / interval
            gaze_rate = (
                self._gaze_count - self._last_metrics_gaze_count
            ) / interval

            self._last_metrics_time = now
            self._last_metrics_frame_count = self._frame_count
            self._last_metrics_gaze_count = self._gaze_count

            self._set_status(
                "streaming" if not self._session_active else "recording",
                frame_rate=round(frame_rate, 2),
                gaze_rate=round(gaze_rate, 2),
                reconnects=self._reconnect_attempts,
                session=self._session.name if self._session else None,
            )

    # ------------------------------------------------------------------
    # Helpers for handling incoming data
    # ------------------------------------------------------------------

    async def _handle_gaze_sample(self, datum: GazeData) -> None:
        self._last_gaze = datum
        self._gaze_count += 1
        self._last_gaze_time = time.time()

        if self._session_active and self._gaze_queue:
            csv_line = self._format_gaze_csv(datum)
            await self._enqueue_with_backpressure(self._gaze_queue, csv_line)

    async def _handle_video_frame(self, frame: Any) -> None:
        try:
            array = frame.to_ndarray(format="bgr24")
        except Exception:  # pragma: no cover - fallback
            array = frame.to_ndarray()

        if array.ndim == 2:
            array = cv2.cvtColor(array, cv2.COLOR_GRAY2BGR)

        self._last_frame = array
        self._frame_shape = array.shape
        self._frame_count += 1
        self._last_frame_time = time.time()

        if self._session_active and self._video_queue:
            await self._enqueue_with_backpressure(self._video_queue, array)

    async def _enqueue_with_backpressure(
        self, queue: asyncio.Queue[Any], item: Any
    ) -> None:
        try:
            queue.put_nowait(item)
        except asyncio.QueueFull:
            with contextlib.suppress(asyncio.QueueEmpty):
                _ = queue.get_nowait()
            queue.put_nowait(item)
            self.logger.debug("Queue full; dropped oldest item")

    @staticmethod
    def _format_gaze_csv(datum: GazeData) -> str:
        return f"{datum.timestamp_unix_seconds:.6f},{datum.x:.6f},{datum.y:.6f},{int(datum.worn)}\n"

    # ------------------------------------------------------------------
    # Writer loops
    # ------------------------------------------------------------------

    async def _gaze_writer_loop(self, eye_dir: Path) -> None:
        assert self._gaze_queue is not None
        file_path = eye_dir / "gaze.csv"
        self.logger.debug("Writing gaze data to %s", file_path)

        try:
            with file_path.open("w", encoding="utf-8") as fh:
                await asyncio.to_thread(fh.write, "timestamp,x,y,worn\n")
                writes = 0
                while True:
                    item = await self._gaze_queue.get()
                    if item is self._queue_sentinel:
                        break
                    await asyncio.to_thread(fh.write, item)
                    writes += 1
                    if writes % 100 == 0:
                        await asyncio.to_thread(fh.flush)
                await asyncio.to_thread(fh.flush)
        except Exception as exc:  # pragma: no cover - defensive logging
            self.logger.exception("Failed to write gaze data: %s", exc)

    async def _video_writer_loop(self, eye_dir: Path) -> None:
        assert self._video_queue is not None
        file_path = eye_dir / "scene.mp4"
        self.logger.debug("Recording video to %s", file_path)

        writer: Optional[cv2.VideoWriter] = None
        try:
            while True:
                item = await self._video_queue.get()
                if item is self._queue_sentinel:
                    break
                frame = item
                if writer is None:
                    height, width = frame.shape[:2]
                    writer = cv2.VideoWriter(
                        str(file_path),
                        cv2.VideoWriter_fourcc(*"mp4v"),
                        self.target_fps,
                        (width, height),
                    )
                    if not writer.isOpened():
                        raise RuntimeError("Failed to open video writer")
                await asyncio.to_thread(writer.write, frame)
        except Exception as exc:  # pragma: no cover - defensive logging
            self.logger.exception("Video writer failed: %s", exc)
        finally:
            if writer is not None:
                await asyncio.to_thread(writer.release)
                self.logger.info("Scene video saved to %s", file_path)


# ---------------------------------------------------------------------------
# Application controller
# ---------------------------------------------------------------------------


class AsyncController:
    """Coordinates the eye tracker module and exposes a CLI."""

    def __init__(self, recordings_dir: Path, *, session_prefix: str = "session") -> None:
        self.logger = logging.getLogger("controller")
        self.recordings_dir = ensure_directory(recordings_dir)

        self.session_prefix = session_prefix
        self.eye_tracker = EyeTrackerModule(self.recordings_dir)
        self.session: Optional[SessionInfo] = None
        self.running = True
        self.discovery_timeout = 10.0
        self.auto_reconnect_interval = 5.0
        self._auto_reconnect_task: Optional[asyncio.Task] = None

    async def initialize(
        self,
        *,
        auto_connect: bool,
        discovery_timeout: float,
        reconnect_interval: float,
    ) -> None:
        self.discovery_timeout = discovery_timeout
        self.auto_reconnect_interval = reconnect_interval
        if not auto_connect:
            self.logger.info("Auto-connect disabled; waiting for manual 'connect' command")
        else:
            connected = await self.eye_tracker.connect(
                timeout_seconds=self.discovery_timeout
            )
            if connected:
                await self.eye_tracker.start_streams()
            else:
                self.logger.warning(
                    "Eye tracker not found. Will continue watching for device availability."
                )

        self._ensure_auto_reconnect_task()

    async def shutdown(self) -> None:
        self.logger.info("Shutting down controller")
        await self.stop_session()
        await self._stop_auto_reconnect()
        await self.eye_tracker.stop()
        self.running = False

    # ------------------------------------------------------------------
    # Session commands
    # ------------------------------------------------------------------

    def _generate_session_name(self, name: Optional[str] = None) -> str:
        if name:
            return name
        timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        prefix = self.session_prefix.rstrip("_")
        return f"{prefix}_{timestamp}" if prefix else timestamp

    async def start_session(self, name: Optional[str] = None) -> None:
        if self.session is not None:
            self.logger.warning("Session %s already active", self.session.name)
            return
        if not self.eye_tracker.can_record():
            raise RuntimeError("Eye tracker stream not running; cannot start session")

        session_name = self._generate_session_name(name)
        session_path = self.recordings_dir / session_name
        session_path.mkdir(parents=True, exist_ok=True)
        self.session = SessionInfo(session_name, session_path)
        await self.eye_tracker.start_session(self.session)
        self.logger.info("Session %s started", session_name)

    async def stop_session(self) -> None:
        if self.session is None:
            return
        await self.eye_tracker.stop_session()
        self.logger.info("Session %s stopped", self.session.name)
        self.session = None

    # ------------------------------------------------------------------
    # CLI helpers
    # ------------------------------------------------------------------

    async def run_cli(self) -> None:
        self.logger.info("Entering interactive mode. Type 'help' for commands.")
        while self.running:
            try:
                prompt = self._prompt()
                command_line = await asyncio.to_thread(input, prompt)
            except (EOFError, KeyboardInterrupt):
                command_line = "quit"

            command_line = command_line.strip()
            if not command_line:
                continue

            cmd, *args = command_line.split()
            cmd = cmd.lower()

            try:
                if cmd in {"help", "h"}:
                    self._print_help()
                elif cmd in {"status", "s"}:
                    self._print_status()
                elif cmd in {"connect", "c"}:
                    await self._cmd_connect()
                elif cmd in {"start", "record", "1"}:
                    name = args[0] if args else None
                    await self.start_session(name)
                elif cmd in {"stop", "0", "2"}:
                    await self.stop_session()
                elif cmd in {"quit", "q", "exit"}:
                    await self.shutdown()
                else:
                    self.logger.warning("Unknown command: %s", cmd)
            except Exception as exc:  # pragma: no cover - user feedback
                self.logger.error("Command '%s' failed: %s", cmd, exc)

    async def run_headless(
        self,
        *,
        auto_start: bool,
        session_name: Optional[str],
        status_interval: float,
    ) -> None:
        """Run without interactive CLI, optionally auto-starting a session."""

        if auto_start and self.session is None:
            await self.start_session(session_name)

        self.logger.info("Headless mode active; awaiting termination signal")
        try:
            while self.running:
                await asyncio.sleep(status_interval)
                self._log_status()
        finally:
            await self.shutdown()

    def _ensure_auto_reconnect_task(self) -> None:
        if self._auto_reconnect_task and not self._auto_reconnect_task.done():
            return
        self._auto_reconnect_task = asyncio.create_task(
            self._auto_reconnect_loop(), name="eye-auto-reconnect"
        )

    async def _stop_auto_reconnect(self) -> None:
        task = self._auto_reconnect_task
        if not task:
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        self._auto_reconnect_task = None

    async def _cmd_connect(self) -> None:
        connected = await self.eye_tracker.connect(timeout_seconds=self.discovery_timeout)
        if connected:
            await self.eye_tracker.start_streams()
        else:
            self.logger.error("Device discovery failed. Check the connection and retry.")

    def _prompt(self) -> str:
        session_part = f"[{self.session.name}]" if self.session else ""
        return f"eye-logger{session_part}> "

    def _print_help(self) -> None:
        print(
            "\nCommands:\n"
            "  help (h)        Show this help message\n"
            "  status (s)      Show module status\n"
            "  connect (c)     Retry device discovery\n"
            "  start           Start a recording session\n"
            "  stop            Stop the active session\n"
            "  quit (q)        Exit the program\n"
        )

    def _print_status(self) -> None:
        status = self.eye_tracker.snapshot()
        details = status.details
        print("\nEYE TRACKER STATUS")
        print("  State:        ", status.state)
        print("  Connected:    ", details.get("connected"))
        print("  Running:      ", details.get("running"))
        print("  Session:      ", details.get("session"))
        print("  Frames:       ", details.get("frames"))
        print("  Gaze samples: ", details.get("gaze_samples"))
        print("  Frame shape:  ", details.get("frame_shape"))
        print("  Frame rate:   ", details.get("frame_rate"))
        print("  Gaze rate:    ", details.get("gaze_rate"))
        print("  Last frame age:", details.get("last_frame_age"))
        print("  Last gaze age: ", details.get("last_gaze_age"))
        print()

    def _log_status(self) -> None:
        status = self.eye_tracker.snapshot()
        details = status.details
        self.logger.debug(
            "status=%s connected=%s running=%s session=%s frames=%s gaze=%s",
            status.state,
            details.get("connected"),
            details.get("running"),
            details.get("session"),
            details.get("frames"),
            details.get("gaze_samples"),
        )

    async def _auto_reconnect_loop(self) -> None:
        while self.running:
            try:
                if not self.eye_tracker.is_connected():
                    self.logger.debug("Auto-reconnect attempting device discovery")
                    connected = await self.eye_tracker.connect(
                        timeout_seconds=self.discovery_timeout
                    )
                    if connected:
                        await self.eye_tracker.start_streams()
                        self.logger.info("Eye tracker connected and streaming")
                await asyncio.sleep(self.auto_reconnect_interval)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # pragma: no cover - defensive
                self.logger.exception("Auto-reconnect loop error: %s", exc)
                await asyncio.sleep(self.auto_reconnect_interval)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Async eye tracker controller")
    add_common_cli_arguments(
        parser,
        default_output=Path("recordings"),
        allowed_modes=("interactive", "headless"),
        default_mode="interactive",
    )

    parser.add_argument(
        "--discovery-timeout",
        type=positive_float,
        default=10.0,
        help="Seconds to wait for device discovery attempts",
    )
    parser.add_argument(
        "--status-interval",
        type=positive_float,
        default=5.0,
        help="Seconds between status log messages in headless mode",
    )
    parser.add_argument(
        "--reconnect-interval",
        type=positive_float,
        default=5.0,
        help="Seconds between auto-reconnect attempts when device is absent",
    )
    parser.add_argument(
        "--auto-start",
        action="store_true",
        help="Automatically start a recording session in headless mode",
    )
    parser.add_argument(
        "--session-name",
        type=str,
        default=None,
        help="Explicit session name to use when auto-starting",
    )
    parser.add_argument(
        "--session-prefix",
        type=str,
        default="session",
        help="Prefix for generated session directories",
    )
    parser.add_argument(
        "--no-auto-connect",
        dest="auto_connect",
        action="store_false",
        help="Skip automatic device discovery on startup",
    )
    parser.set_defaults(auto_connect=True)

    return parser


async def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    configure_logging(args.log_level, args.log_file)
    controller = AsyncController(args.output_dir, session_prefix=args.session_prefix)
    await controller.initialize(
        auto_connect=args.auto_connect,
        discovery_timeout=args.discovery_timeout,
        reconnect_interval=args.reconnect_interval,
    )

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, lambda s=sig: asyncio.create_task(controller.shutdown()))

    if args.mode == "interactive":
        await controller.run_cli()
    else:
        await controller.run_headless(
            auto_start=args.auto_start,
            session_name=args.session_name,
            status_interval=args.status_interval,
        )

    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        print("\nInterrupted")
        sys.exit(130)
