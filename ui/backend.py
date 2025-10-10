"""Backend orchestration helpers for the Textual dashboard."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import shutil
import threading
import time
import wave
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np
import sounddevice as sd

from cli_utils import ensure_directory
from main import AsyncController as EyeTrackerController


REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_UV = shutil.which("uv") or "/home/rs-pi-2/.local/bin/uv"


class ModuleState(str, Enum):
    """High-level lifecycle states exposed to the UI."""

    OFFLINE = "offline"
    STARTING = "starting"
    READY = "ready"
    RECONNECTING = "reconnecting"
    RECORDING = "recording"
    ERROR = "error"


@dataclass(slots=True)
class ModuleStatus:
    """Immutable status payloads emitted by module supervisors."""

    name: str
    state: ModuleState
    summary: str = ""
    details: Dict[str, Any] = field(default_factory=dict)
    recording: bool = False
    last_update: float = field(default_factory=time.time)


@dataclass(slots=True)
class ModuleLog:
    """Log line emitted by a module."""

    name: str
    message: str
    level: str = "info"
    timestamp: float = field(default_factory=time.time)


class BaseModuleService:
    """Common helper for module backends."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.status_queue: asyncio.Queue[ModuleStatus] = asyncio.Queue()
        self.log_queue: asyncio.Queue[ModuleLog] = asyncio.Queue()
        self._state = ModuleState.OFFLINE
        self._recording = False
        self._details: Dict[str, Any] = {}
        self._summary = ""
        self._lock = asyncio.Lock()

    @property
    def is_recording(self) -> bool:
        return self._recording

    def _make_status(self, *, state: ModuleState, summary: str, details: Optional[Dict[str, Any]] = None, recording: Optional[bool] = None) -> ModuleStatus:
        status = ModuleStatus(
            name=self.name,
            state=state,
            summary=summary,
            details=details or {},
            recording=self._recording if recording is None else recording,
        )
        self._state = status.state
        self._summary = status.summary
        self._details = dict(status.details)
        self._recording = status.recording
        return status

    async def _emit_status(
        self,
        *,
        state: ModuleState,
        summary: str,
        details: Optional[Dict[str, Any]] = None,
        recording: Optional[bool] = None,
    ) -> None:
        status = self._make_status(state=state, summary=summary, details=details, recording=recording)
        await self.status_queue.put(status)

    def _publish_log(self, message: str, *, level: str = "info") -> None:
        self.log_queue.put_nowait(ModuleLog(name=self.name, message=message, level=level))

    async def start(self) -> None:  # pragma: no cover - abstract
        raise NotImplementedError

    async def stop(self) -> None:  # pragma: no cover - abstract
        raise NotImplementedError

    async def start_recording(self) -> None:  # pragma: no cover - abstract
        raise NotImplementedError

    async def stop_recording(self) -> None:  # pragma: no cover - abstract
        raise NotImplementedError


class ModuleSupervisor:
    """Aggregate module status and log streams."""

    def __init__(self) -> None:
        self.modules: Dict[str, BaseModuleService] = {}
        self.status_queue: asyncio.Queue[ModuleStatus] = asyncio.Queue()
        self.log_queue: asyncio.Queue[ModuleLog] = asyncio.Queue()
        self._forward_tasks: list[asyncio.Task[Any]] = []
        self._closed = False

    async def register(self, module: BaseModuleService) -> None:
        if self._closed:
            raise RuntimeError("Supervisor already closed")
        if module.name in self.modules:
            raise ValueError(f"Module '{module.name}' already registered")
        self.modules[module.name] = module
        self._forward_tasks.append(asyncio.create_task(self._forward_status(module)))
        self._forward_tasks.append(asyncio.create_task(self._forward_logs(module)))

    async def _forward_status(self, module: BaseModuleService) -> None:
        while True:
            try:
                status = await module.status_queue.get()
            except asyncio.CancelledError:
                break
            await self.status_queue.put(status)

    async def _forward_logs(self, module: BaseModuleService) -> None:
        while True:
            try:
                log = await module.log_queue.get()
            except asyncio.CancelledError:
                break
            await self.log_queue.put(log)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for task in self._forward_tasks:
            task.cancel()
        for task in self._forward_tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._forward_tasks.clear()
        self.modules.clear()

    def get(self, name: str) -> BaseModuleService:
        return self.modules[name]


# ---------------------------------------------------------------------------
# Camera process supervisor
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class CameraConfig:
    resolution: tuple[int, int] = (1280, 720)
    target_fps: float = 25.0
    discovery_timeout: float = 5.0
    discovery_retry: float = 3.0
    min_cameras: int = 2
    allow_partial: bool = True
    session_prefix: str = "session"
    output_dir: Path = Path("recordings/camera")
    log_level: str = "info"
    extra_args: tuple[str, ...] = ()


class CameraProcessService(BaseModuleService):
    """Manage the camera module as an asyncio subprocess."""

    def __init__(
        self,
        config: CameraConfig,
        *,
        uv_executable: str | None = None,
        workdir: Path | None = None,
    ) -> None:
        super().__init__(name="camera")
        self.config = config
        self.uv_executable = uv_executable or _DEFAULT_UV
        self.workdir = workdir or REPO_ROOT
        self.script_path = REPO_ROOT / "Modules" / "Cameras" / "main_camera.py"
        self._process: Optional[asyncio.subprocess.Process] = None
        self._stdout_task: Optional[asyncio.Task[Any]] = None
        self._stderr_task: Optional[asyncio.Task[Any]] = None
        self._wait_task: Optional[asyncio.Task[Any]] = None
        self._status_details: Dict[str, Any] = {}

        # Store latest preview frames for each camera
        self._preview_frames: Dict[int, bytes] = {}  # camera_id -> JPEG bytes
        self._frame_lock = asyncio.Lock()

    def _build_args(self) -> list[str]:
        resolution = f"{self.config.resolution[0]}x{self.config.resolution[1]}"
        args: list[str] = [
            self.uv_executable,
            "run",
            str(self.script_path),
            "--mode",
            "slave",
            "--resolution",
            resolution,
            "--target-fps",
            str(self.config.target_fps),
            "--discovery-timeout",
            str(self.config.discovery_timeout),
            "--discovery-retry",
            str(self.config.discovery_retry),
            "--min-cameras",
            str(self.config.min_cameras),
            "--output-dir",
            str((self.workdir / self.config.output_dir).resolve()),
            "--session-prefix",
            self.config.session_prefix,
            "--log-level",
            self.config.log_level,
        ]
        if self.config.allow_partial:
            args.append("--allow-partial")
        args.extend(self.config.extra_args)
        return args

    async def start(self) -> None:
        async with self._lock:
            if self._process and self._process.returncode is None:
                return
            ensure_path = (self.workdir / self.config.output_dir).resolve()
            ensure_path.mkdir(parents=True, exist_ok=True)
            cmd = self._build_args()
            await self._emit_status(state=ModuleState.STARTING, summary="Launching camera module")
            self._publish_log("Starting camera module", level="debug")
            self._process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.workdir),
            )
            self._stdout_task = asyncio.create_task(self._consume_stdout())
            self._stderr_task = asyncio.create_task(self._consume_stderr())
            self._wait_task = asyncio.create_task(self._monitor_exit())

    async def stop(self) -> None:
        async with self._lock:
            if not self._process:
                return
            proc = self._process
            if proc.returncode is None and proc.stdin:
                try:
                    await self._send_command({"command": "quit"})
                    await asyncio.wait_for(proc.wait(), timeout=5)
                except asyncio.TimeoutError:
                    self._publish_log("Camera module did not shutdown gracefully; terminating", level="warning")
                    proc.terminate()
                    try:
                        await asyncio.wait_for(proc.wait(), timeout=3)
                    except asyncio.TimeoutError:
                        self._publish_log("Force killing camera module", level="error")
                        proc.kill()
                        await proc.wait()
            self._cleanup_tasks()
            self._process = None
            await self._emit_status(state=ModuleState.OFFLINE, summary="Camera module stopped", recording=False)

    def _cleanup_tasks(self) -> None:
        for task in (self._stdout_task, self._stderr_task, self._wait_task):
            if task:
                task.cancel()
        self._stdout_task = None
        self._stderr_task = None
        self._wait_task = None

    async def _consume_stdout(self) -> None:
        assert self._process and self._process.stdout
        stream = self._process.stdout
        while True:
            line = await stream.readline()
            if not line:
                break
            text = line.decode().strip()
            if not text:
                continue
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                self._publish_log(f"{text}", level="debug")
                continue
            await self._handle_message(payload)

    async def _consume_stderr(self) -> None:
        assert self._process and self._process.stderr
        stream = self._process.stderr
        while True:
            line = await stream.readline()
            if not line:
                break
            text = line.decode().rstrip()
            if text:
                self._publish_log(text, level="debug")

    async def _monitor_exit(self) -> None:
        assert self._process
        await self._process.wait()
        self._publish_log("Camera module exited", level="warning")
        await self._emit_status(state=ModuleState.OFFLINE, summary="Camera process exited", recording=False)

    async def _handle_message(self, message: Dict[str, Any]) -> None:
        status = message.get("status")
        data = message.get("data", {})
        if status == "initialized":
            cameras = data.get("cameras", 0)
            summary = f"Ready ({cameras} camera{'s' if cameras != 1 else ''})"
            await self._emit_status(state=ModuleState.READY, summary=summary, details=data, recording=False)
        elif status == "recording_started":
            files = data.get("files", [])
            summary = f"Recording ({len(files)} file target)"
            await self._emit_status(state=ModuleState.RECORDING, summary=summary, details=data, recording=True)
        elif status == "recording_stopped":
            files = data.get("files", [])
            summary = f"Recording stopped ({len(files)} file{'s' if len(files) != 1 else ''})"
            await self._emit_status(state=ModuleState.READY, summary=summary, details=data, recording=False)
        elif status == "status_report":
            summary = self._summary or "Camera status"
            merged = dict(self._details)
            merged.update(data)
            recording = merged.get("recording", self._recording)
            state = ModuleState.RECORDING if recording else (ModuleState.READY if self._state != ModuleState.ERROR else ModuleState.ERROR)
            await self._emit_status(state=state, summary=summary, details=merged, recording=recording)
        elif status == "preview_frame":
            # Store the latest preview frame for this camera
            camera_id = data.get("camera_id", 0)
            frame_b64 = data.get("frame")
            if frame_b64:
                async with self._frame_lock:
                    # Decode base64 to bytes for storage
                    self._preview_frames[camera_id] = base64.b64decode(frame_b64)
                    self._publish_log(f"Received preview frame from camera {camera_id}, size: {len(self._preview_frames[camera_id])} bytes", level="debug")
        elif status == "warning":
            message_text = data.get("message", "Camera warning")
            self._publish_log(message_text, level="warning")
            await self._emit_status(state=self._state, summary=message_text, details=data)
        elif status == "error":
            message_text = data.get("message", "Camera error")
            self._publish_log(message_text, level="error")
            await self._emit_status(state=ModuleState.ERROR, summary=message_text, details=data, recording=False)
        elif status in {"quitting", "shutdown"}:
            await self._emit_status(state=ModuleState.OFFLINE, summary="Camera shutting down", details=data, recording=False)
        elif status == "initializing":
            await self._emit_status(state=ModuleState.STARTING, summary="Initializing cameras", details=data, recording=False)
        else:
            self._publish_log(f"Unhandled camera status: {status}", level="debug")

    async def _send_command(self, payload: Dict[str, Any]) -> None:
        if not self._process or not self._process.stdin:
            raise RuntimeError("Camera process is not running")
        message = json.dumps(payload) + "\n"
        self._process.stdin.write(message.encode())
        await self._process.stdin.drain()

    async def start_recording(self) -> None:
        await self._send_command({"command": "start_recording"})

    async def stop_recording(self) -> None:
        await self._send_command({"command": "stop_recording"})

    async def request_status(self) -> None:
        await self._send_command({"command": "get_status"})

    async def take_snapshot(self) -> None:
        await self._send_command({"command": "take_snapshot"})

    async def refresh(self) -> None:
        await self.request_status()

    async def get_preview_frame(self, camera_id: int) -> Optional[bytes]:
        """Get the latest preview frame for a camera as JPEG bytes."""
        async with self._frame_lock:
            return self._preview_frames.get(camera_id)

    async def toggle_preview(self, camera_id: int, enabled: bool) -> None:
        """Toggle preview streaming for a specific camera."""
        await self._send_command({
            "command": "toggle_preview",
            "camera_id": camera_id,
            "enabled": enabled,
        })


# ---------------------------------------------------------------------------
# Eye tracker supervisor
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class EyeTrackerConfig:
    output_dir: Path = Path("eye_tracking_data")
    session_prefix: str = "session"
    auto_connect: bool = True
    discovery_timeout: float = 10.0
    reconnect_interval: float = 5.0
    status_interval: float = 2.0
    log_level: str = "info"


class EyeTrackerService(BaseModuleService):
    """Manage the async eye tracker controller inside the dashboard."""

    def __init__(
        self,
        config: EyeTrackerConfig,
        *,
        workdir: Path | None = None,
    ) -> None:
        super().__init__(name="eye_tracker")
        self.config = config
        self.workdir = workdir or REPO_ROOT
        self._controller: EyeTrackerController | None = None
        self._poll_task: Optional[asyncio.Task[Any]] = None
        self._status_interval = config.status_interval
        self._connect_lock = asyncio.Lock()

    async def start(self) -> None:
        async with self._lock:
            if self._controller is not None:
                return
            output_dir = ensure_directory((self.workdir / self.config.output_dir).resolve())
            self._controller = EyeTrackerController(
                output_dir,
                session_prefix=self.config.session_prefix,
            )
            await self._controller.initialize(
                auto_connect=self.config.auto_connect,
                discovery_timeout=self.config.discovery_timeout,
                reconnect_interval=self.config.reconnect_interval,
            )
            await self._emit_status(
                state=ModuleState.STARTING,
                summary="Eye tracker controller initialised",
                recording=False,
            )
            self._poll_task = asyncio.create_task(self._status_loop(), name="eye-status-loop")
            await self._sync_status(force=True)

    async def stop(self) -> None:
        async with self._lock:
            if not self._controller:
                return
            if self._poll_task:
                self._poll_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._poll_task
                self._poll_task = None
            await self._controller.shutdown()
            self._controller = None
            await self._emit_status(
                state=ModuleState.OFFLINE,
                summary="Eye tracker stopped",
                recording=False,
            )

    async def _status_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(self._status_interval)
                await self._sync_status()
            except asyncio.CancelledError:
                break
            except Exception as exc:  # pragma: no cover - defensive logging
                self._publish_log(f"Eye tracker status loop error: {exc}", level="error")

    async def _sync_status(self, *, force: bool = False) -> None:
        if not self._controller:
            return

        if force:
            # Parameter reserved for future diff-aware updates
            pass

        tracker = self._controller.eye_tracker
        raw_status = tracker.snapshot()
        details = dict(raw_status.details)
        session_name = self._controller.session.name if self._controller.session else details.get("session")
        details["session"] = session_name
        details["connected"] = tracker.is_connected()
        details["streaming"] = tracker.is_streaming()
        recording = self._controller.session is not None

        if recording and session_name:
            summary = f"Recording ({session_name})"
            state = ModuleState.RECORDING
        elif tracker.is_streaming():
            summary = "Streaming"
            state = ModuleState.READY
        elif tracker.is_connected():
            summary = "Connected"
            state = ModuleState.READY
        else:
            summary = "Searching for eye tracker"
            state = ModuleState.RECONNECTING if self.config.auto_connect else ModuleState.STARTING

        await self._emit_status(
            state=state,
            summary=summary,
            details=details,
            recording=recording,
        )

    async def ensure_ready(self) -> bool:
        if not self._controller:
            return False

        tracker = self._controller.eye_tracker
        if tracker.is_connected() and tracker.is_streaming():
            return True

        async with self._connect_lock:
            if tracker.is_connected() and tracker.is_streaming():
                return True
            try:
                connected = await tracker.connect(timeout_seconds=self.config.discovery_timeout)
                if connected:
                    await tracker.start_streams()
                    await self._sync_status(force=True)
                else:
                    self._publish_log("Eye tracker not found", level="warning")
                return connected
            except Exception as exc:  # pragma: no cover - defensive logging
                self._publish_log(f"Eye tracker connect failed: {exc}", level="error")
                await self._emit_status(
                    state=ModuleState.ERROR,
                    summary="Eye tracker connection failed",
                    details={"error": str(exc)},
                    recording=False,
                )
                return False

    async def start_recording(self, session_name: Optional[str] = None) -> None:
        if not self._controller:
            raise RuntimeError("Eye tracker controller not started")
        ready = await self.ensure_ready()
        if not ready:
            raise RuntimeError("Eye tracker not available")
        await self._controller.start_session(session_name)
        await self._sync_status(force=True)

    async def stop_recording(self) -> None:
        if not self._controller:
            return
        await self._controller.stop_session()
        await self._sync_status(force=True)

    async def refresh(self) -> None:
        await self._sync_status(force=True)


# ---------------------------------------------------------------------------
# Audio recorder supervisor
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class AudioConfig:
    sample_rate: int = 48_000
    session_prefix: str = "experiment"
    output_dir: Path = Path("recordings/audio")
    auto_select_new: bool = True
    auto_record_on_attach: bool = False
    status_interval: float = 2.0


class AudioRecorderService(BaseModuleService):
    """Manage multi-microphone recordings within the dashboard."""

    def __init__(
        self,
        config: AudioConfig,
        *,
        workdir: Path | None = None,
    ) -> None:
        super().__init__(name="audio")
        self.config = config
        self.workdir = workdir or REPO_ROOT
        self.available_devices: Dict[int, Dict[str, Any]] = {}
        self.selected_devices: set[int] = set()
        self.active_streams: Dict[int, sd.InputStream] = {}
        self._recording_buffers: Dict[int, list[np.ndarray]] = {}
        self._frames_recorded: Dict[int, int] = {}
        self._last_saved_files: list[Path] = []
        self._session_dir: Optional[Path] = None
        self._recording_start: Optional[float] = None
        self._recording_count = 0
        self._monitor_task: Optional[asyncio.Task[Any]] = None
        self._status_task: Optional[asyncio.Task[Any]] = None
        self._buffer_lock = threading.Lock()
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    async def start(self) -> None:
        async with self._lock:
            if self._monitor_task is not None:
                return
            self._loop = asyncio.get_running_loop()
            ensure_directory((self.workdir / self.config.output_dir).resolve())
            await self._refresh_devices_locked()
            self._monitor_task = asyncio.create_task(self._monitor_loop(), name="audio-monitor")
            self._status_task = asyncio.create_task(self._status_loop(), name="audio-status")

    async def stop(self) -> None:
        async with self._lock:
            await self._stop_background_tasks()
            await self._stop_streams()
            self.available_devices.clear()
            self.selected_devices.clear()
            self._recording_buffers.clear()
            self._frames_recorded.clear()
            self._last_saved_files.clear()
            self._session_dir = None
            self._recording_start = None
            self._recording = False
            self._loop = None
            await self._emit_status(
                state=ModuleState.OFFLINE,
                summary="Audio monitor stopped",
                details={},
                recording=False,
            )

    async def _stop_background_tasks(self) -> None:
        for task in (self._monitor_task, self._status_task):
            if task:
                task.cancel()
        for task in (self._monitor_task, self._status_task):
            if task:
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        self._monitor_task = None
        self._status_task = None

    async def _monitor_loop(self) -> None:
        while True:
            try:
                added, removed, removed_selected = await self.refresh_devices()

                if removed_selected and self._recording:
                    self._publish_log(
                        "Stopping audio recording after device removal",
                        level="warning",
                    )
                    await self.stop_recording()

                if (
                    self.config.auto_record_on_attach
                    and added
                    and self.selected_devices
                    and not self._recording
                ):
                    with contextlib.suppress(Exception):
                        await self.start_recording()
                        self._publish_log("Auto-started audio recording", level="info")

                await asyncio.sleep(self.config.status_interval)
            except asyncio.CancelledError:
                break
            except Exception as exc:  # pragma: no cover - defensive logging
                self._publish_log(f"Audio monitor error: {exc}", level="error")
                await asyncio.sleep(self.config.status_interval)

    async def _status_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(self.config.status_interval)
                if self._recording or self.available_devices:
                    await self._emit_audio_status()
            except asyncio.CancelledError:
                break
            except Exception as exc:  # pragma: no cover - defensive logging
                self._publish_log(f"Audio status loop error: {exc}", level="error")

    async def refresh_devices(self) -> tuple[set[int], set[int], set[int]]:
        async with self._lock:
            return await self._refresh_devices_locked()

    async def _refresh_devices_locked(self) -> tuple[set[int], set[int], set[int]]:
        try:
            devices = await asyncio.to_thread(sd.query_devices)
        except Exception as exc:  # pragma: no cover - defensive logging
            self._publish_log(f"Audio device discovery failed: {exc}", level="error")
            await self._emit_audio_status(summary_override="Audio discovery failed")
            return set(), set(), set()

        discovered: Dict[int, Dict[str, Any]] = {}
        for idx, device in enumerate(devices):
            if device.get("max_input_channels", 0) > 0:
                discovered[idx] = {
                    "name": device.get("name", f"Device {idx}"),
                    "channels": device.get("max_input_channels", 1),
                    "sample_rate": device.get("default_samplerate", self.config.sample_rate),
                }

        previous = set(self.available_devices)
        current = set(discovered)
        added = current - previous
        removed = previous - current
        removed_selected = removed & self.selected_devices

        self.available_devices = discovered
        if removed_selected:
            self.selected_devices.difference_update(removed_selected)

        if self.config.auto_select_new and added and not self.selected_devices:
            self.selected_devices.update(added)

        await self._emit_audio_status()

        return added, removed, removed_selected

    async def toggle_device(self, device_id: int) -> bool:
        async with self._lock:
            if device_id not in self.available_devices:
                self._publish_log(f"Audio device {device_id} not available", level="warning")
                return False

            if device_id in self.selected_devices:
                self.selected_devices.remove(device_id)
                self._publish_log(f"Deselected microphone {device_id}")
            else:
                self.selected_devices.add(device_id)
                self._publish_log(f"Selected microphone {device_id}")

            await self._emit_audio_status()
            return True

    async def start_recording(self, session_name: Optional[str] = None) -> None:
        async with self._lock:
            if self._recording:
                return
            if not self.selected_devices:
                raise RuntimeError("No microphones selected for recording")

            base_dir = ensure_directory((self.workdir / self.config.output_dir).resolve())
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            prefix = self.config.session_prefix.rstrip("_")
            session_label = session_name or (f"{prefix}_{timestamp}" if prefix else timestamp)
            self._session_dir = ensure_directory(base_dir / session_label)
            self._recording_start = time.time()
            self._recording_count += 1
            self._recording_buffers = {device_id: [] for device_id in self.selected_devices}
            self._frames_recorded = {device_id: 0 for device_id in self.selected_devices}
            self._last_saved_files.clear()

            for device_id in self.selected_devices:
                await self._start_stream_for_device(device_id)

            self._recording = True
            await self._emit_audio_status(summary_override="Recording microphones")

    async def _start_stream_for_device(self, device_id: int) -> None:
        device_info = self.available_devices.get(device_id)
        if not device_info:
            raise RuntimeError(f"Device {device_id} not available")

        stream = sd.InputStream(
            device=device_id,
            callback=self._make_callback(device_id),
            channels=1,
            samplerate=self.config.sample_rate,
            dtype=np.float32,
            blocksize=1024,
        )
        stream.start()
        self.active_streams[device_id] = stream

    def _make_callback(self, device_id: int):
        loop = self._loop

        def _callback(indata, frames, _time_info, status):
            if not self._recording:
                return
            with self._buffer_lock:
                buffer = self._recording_buffers.setdefault(device_id, [])
                buffer.append(indata.copy())
                self._frames_recorded[device_id] = self._frames_recorded.get(device_id, 0) + frames
            if status and loop:
                loop.call_soon_threadsafe(
                    self._publish_log,
                    f"Audio device {device_id} status: {status}",
                )

        return _callback

    async def stop_recording(self) -> None:
        async with self._lock:
            if not self._recording:
                return
            await self._stop_streams()
            await self._save_all_recordings()
            self._recording = False
            self._recording_start = None
            self._recording_buffers.clear()
            self._frames_recorded.clear()
            await self._emit_audio_status(summary_override="Recording stopped")

    async def _stop_streams(self) -> None:
        for stream in list(self.active_streams.values()):
            with contextlib.suppress(Exception):
                stream.stop()
                stream.close()
        self.active_streams.clear()

    async def _save_all_recordings(self) -> None:
        tasks = [self._save_device_recording(device_id) for device_id in list(self._recording_buffers)]
        if tasks:
            await asyncio.gather(*tasks)

    async def _save_device_recording(self, device_id: int) -> None:
        if not self._session_dir:
            return
        with self._buffer_lock:
            chunks = [chunk.copy() for chunk in self._recording_buffers.get(device_id, [])]
        if not chunks:
            return

        audio_array = np.concatenate(chunks)
        audio_array = np.clip(audio_array, -1.0, 1.0)
        audio_int16 = (audio_array * 32767).astype(np.int16)

        device_info = self.available_devices.get(device_id, {})
        safe_name = device_info.get("name", f"device{device_id}")
        safe_name = safe_name.replace(" ", "_").replace(":", "")
        timestamp = datetime.now().strftime("%H%M%S")
        filename = self._session_dir / (
            f"mic{device_id}_{safe_name}_rec{self._recording_count:03d}_{timestamp}.wav"
        )

        def _write_file() -> None:
            with wave.open(str(filename), "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(self.config.sample_rate)
                wf.writeframes(audio_int16.tobytes())

        await asyncio.to_thread(_write_file)

        self._last_saved_files.append(filename)
        # Keep only the most recent entries to prevent unbounded growth
        if len(self._last_saved_files) > 10:
            self._last_saved_files = self._last_saved_files[-10:]
        self._publish_log(f"Saved audio recording: {filename}")

    async def _emit_audio_status(self, summary_override: Optional[str] = None) -> None:
        summary, details, state, recording = self._snapshot()
        if summary_override:
            summary = summary_override
        await self._emit_status(state=state, summary=summary, details=details, recording=recording)

    def _snapshot(self) -> tuple[str, Dict[str, Any], ModuleState, bool]:
        device_count = len(self.available_devices)
        selected_count = len(self.selected_devices)
        recording = self._recording
        duration = int(time.time() - self._recording_start) if recording and self._recording_start else 0

        if recording:
            state = ModuleState.RECORDING
            summary = f"Recording {selected_count} mic{'s' if selected_count != 1 else ''} ({duration}s)"
        elif device_count:
            state = ModuleState.READY
            summary = f"{device_count} mic{'s' if device_count != 1 else ''} available"
        else:
            state = ModuleState.RECONNECTING
            summary = "Waiting for microphones"

        details = {
            "devices": self.available_devices,
            "selected": sorted(self.selected_devices),
            "recording": recording,
            "session_dir": str(self._session_dir) if self._session_dir else None,
            "duration": duration,
            "frames": dict(self._frames_recorded),
            "last_saved": [str(path) for path in self._last_saved_files],
        }
        return summary, details, state, recording

    async def refresh(self) -> None:
        await self.refresh_devices()


# ---------------------------------------------------------------------------
# Dashboard backend aggregator
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class DashboardConfig:
    camera: CameraConfig = field(default_factory=CameraConfig)
    eye_tracker: EyeTrackerConfig = field(default_factory=EyeTrackerConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)
    uv_executable: Optional[str] = None
    workdir: Path = REPO_ROOT


class DashboardBackend:
    """High-level convenience wrapper bundling module services."""

    def __init__(self, config: Optional[DashboardConfig] = None) -> None:
        self.config = config or DashboardConfig()
        self.workdir = self.config.workdir
        self.camera = CameraProcessService(
            self.config.camera,
            uv_executable=self.config.uv_executable,
            workdir=self.workdir,
        )
        self.eye_tracker = EyeTrackerService(
            self.config.eye_tracker,
            workdir=self.workdir,
        )
        self.audio = AudioRecorderService(
            self.config.audio,
            workdir=self.workdir,
        )
        self.modules: Dict[str, BaseModuleService] = {
            self.camera.name: self.camera,
            self.eye_tracker.name: self.eye_tracker,
            self.audio.name: self.audio,
        }
        self.supervisor = ModuleSupervisor()

    async def setup(self) -> None:
        for module in self.modules.values():
            await self.supervisor.register(module)

    async def start_all(self) -> None:
        await asyncio.gather(*(module.start() for module in self.modules.values()))

    async def stop_all(self) -> None:
        for module in self.modules.values():
            with contextlib.suppress(Exception):
                await module.stop()

    async def shutdown(self) -> None:
        await self.stop_all()
        await self.supervisor.close()

    def get(self, name: str) -> BaseModuleService:
        return self.modules[name]
