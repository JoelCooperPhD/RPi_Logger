# Phase 4: Runtime Bridge

## Quick Reference

| Task | Status | Dependencies | Effort | Spec |
|------|--------|--------------|--------|------|
| P4.1 CamerasRuntime skeleton | available | P1.1, P1.2 | Medium | `specs/components.md` |
| P4.2 Device assignment | available | P4.1, P1.4 | Medium | `specs/commands.md` |
| P4.3 Command handlers | available | P4.1, P3.2 | Medium | `specs/commands.md` |
| P4.4 Status reporting | available | P4.3 | Small | `specs/commands.md` |

## Goal

Build the orchestration layer that ties capture, recording, and UI together.

---

## P4.1: CamerasRuntime Skeleton

### Deliverables

| File | Contents |
|------|----------|
| `bridge.py` | CamerasRuntime class skeleton |

### Implementation

```python
# bridge.py
import asyncio
from dataclasses import dataclass
from typing import Callable, Awaitable
from .config import CamerasConfig
from .camera_core.types import CameraId, CameraDescriptor, CameraCapabilities

@dataclass
class RuntimeState:
    camera_id: CameraId | None = None
    descriptor: CameraDescriptor | None = None
    capabilities: CameraCapabilities | None = None
    capturing: bool = False
    recording: bool = False

class CamerasRuntime:
    def __init__(
        self,
        config: CamerasConfig,
        view = None,
        status_callback: Callable[[str, dict], Awaitable[None]] | None = None
    ):
        self._config = config
        self._view = view
        self._status_callback = status_callback

        # State
        self._state = RuntimeState()
        self._capture = None
        self._encoder = None
        self._timing_writer = None
        self._disk_guard = None

        # Control
        self._capture_task: asyncio.Task | None = None
        self._stop_capture = asyncio.Event()

        # Metrics
        self._capture_fps = 0.0
        self._record_fps = 0.0
        self._queue_depth = 0
        self._frames_recorded = 0

    async def initialize(self) -> None:
        await self._init_disk_guard()
        await self._report_status("ready", {})

    async def shutdown(self) -> None:
        await self.unassign_device()
        await self._shutdown_disk_guard()

    async def _report_status(self, status: str, payload: dict) -> None:
        if self._status_callback:
            await self._status_callback(status, payload)

    # Placeholder methods to be implemented
    async def assign_device(self, camera_id: CameraId, descriptor: CameraDescriptor) -> None:
        raise NotImplementedError

    async def unassign_device(self) -> None:
        raise NotImplementedError

    async def start_recording(self, session_prefix: str, trial_number: int) -> None:
        raise NotImplementedError

    async def stop_recording(self) -> None:
        raise NotImplementedError

    async def handle_command(self, command: str, payload: dict) -> None:
        raise NotImplementedError
```

### Validation

- [ ] Class instantiates with config
- [ ] `initialize()` sends "ready" status
- [ ] `shutdown()` cleans up resources
- [ ] State tracking works

---

## P4.2: Device Assignment

### Deliverables

Complete `assign_device()` and `unassign_device()` in `bridge.py`.

### Implementation

```python
# In CamerasRuntime (bridge.py)

async def assign_device(
    self,
    camera_id: CameraId,
    descriptor: CameraDescriptor
) -> None:
    # Unassign existing device first
    if self._state.camera_id:
        await self.unassign_device()

    try:
        # Probe camera capabilities
        from .camera_core.backends import usb_backend
        capabilities = await usb_backend.probe(descriptor.device_path)

        # Normalize and select defaults
        from .camera_core.capabilities import build_capabilities
        capabilities = build_capabilities(capabilities.modes)
        capabilities.controls = (await usb_backend.probe(descriptor.device_path)).controls

        # Update state
        self._state.camera_id = camera_id
        self._state.descriptor = descriptor
        self._state.capabilities = capabilities

        # Determine capture settings
        preview = capabilities.default_preview or capabilities.modes[0]
        self._preview_width = preview.width
        self._preview_height = preview.height
        self._preview_fps = preview.fps

        record = capabilities.default_record or capabilities.modes[0]
        self._record_width = record.width
        self._record_height = record.height
        self._record_fps = record.fps
        self._capture_fps = record.fps

        # Start capture
        from .camera_core.capture import USBCapture
        self._capture = USBCapture(
            device_path=descriptor.device_path,
            width=self._record_width,
            height=self._record_height,
            fps=self._capture_fps
        )
        await self._capture.start()

        # Start capture loop
        self._stop_capture.clear()
        self._capture_task = asyncio.create_task(self._capture_loop())
        self._state.capturing = True

        await self._report_status("device_ready", {
            "camera_id": str(camera_id),
            "name": descriptor.name,
            "resolution": f"{self._record_width}x{self._record_height}",
            "fps": self._capture_fps
        })

    except Exception as e:
        await self._report_status("device_error", {
            "camera_id": str(camera_id),
            "error": str(e)
        })
        raise

async def unassign_device(self) -> None:
    if not self._state.camera_id:
        return

    # Stop recording if active
    if self._state.recording:
        await self.stop_recording()

    # Stop capture loop
    self._stop_capture.set()
    if self._capture_task:
        try:
            await asyncio.wait_for(self._capture_task, timeout=2.0)
        except asyncio.TimeoutError:
            self._capture_task.cancel()
        self._capture_task = None

    # Stop capture
    if self._capture:
        await self._capture.stop()
        self._capture = None

    # Reset state
    self._state = RuntimeState()

    await self._report_status("device_released", {})
```

### Validation

- [ ] Camera probed on assignment
- [ ] Capture starts automatically
- [ ] Existing device unassigned first
- [ ] Clean unassignment stops everything
- [ ] Error handling reports status

---

## P4.3: Command Handlers

### Deliverables

Complete `handle_command()` dispatcher in `bridge.py`.

### Implementation

```python
# In CamerasRuntime (bridge.py)

async def handle_command(self, command: str, payload: dict) -> None:
    handlers = {
        "assign_device": self._cmd_assign_device,
        "unassign_device": self._cmd_unassign_device,
        "unassign_all_devices": self._cmd_unassign_device,
        "start_recording": self._cmd_start_recording,
        "record": self._cmd_start_recording,
        "stop_recording": self._cmd_stop_recording,
        "pause": self._cmd_stop_recording,
        "pause_recording": self._cmd_stop_recording,
        "resume_recording": self._cmd_resume_recording,
        "start_session": self._cmd_start_session,
        "stop_session": self._cmd_stop_session,
        "apply_config": self._cmd_apply_config,
        "control_change": self._cmd_control_change,
        "reprobe": self._cmd_reprobe,
    }

    handler = handlers.get(command)
    if handler:
        try:
            await handler(payload)
        except Exception as e:
            await self._report_status("error", {
                "command": command,
                "error": str(e),
                "recoverable": True
            })
    else:
        await self._report_status("error", {
            "command": command,
            "error": f"Unknown command: {command}",
            "recoverable": True
        })

async def _cmd_assign_device(self, payload: dict) -> None:
    camera_id = CameraId(
        backend=payload["camera_id"]["backend"],
        stable_id=payload["camera_id"]["stable_id"]
    )
    descriptor = CameraDescriptor(
        camera_id=camera_id,
        name=payload["descriptor"]["name"],
        device_path=payload["descriptor"]["device_path"],
        usb_path=payload["descriptor"].get("usb_path")
    )
    await self.assign_device(camera_id, descriptor)

async def _cmd_unassign_device(self, payload: dict) -> None:
    await self.unassign_device()

async def _cmd_start_recording(self, payload: dict) -> None:
    await self.start_recording(
        session_prefix=payload.get("session_prefix", "recording"),
        trial_number=payload.get("trial_number", 1),
        output_dir=payload.get("output_dir")
    )

async def _cmd_stop_recording(self, payload: dict) -> None:
    await self.stop_recording()

async def _cmd_resume_recording(self, payload: dict) -> None:
    # Resume uses same session
    if hasattr(self, '_paused_paths'):
        self._recording = True
        await self._report_status("recording_resumed", {})

async def _cmd_start_session(self, payload: dict) -> None:
    self._session_id = payload.get("session_id")

async def _cmd_stop_session(self, payload: dict) -> None:
    self._session_id = None

async def _cmd_apply_config(self, payload: dict) -> None:
    # Apply new settings, may require capture restart
    await self._apply_config_changes(payload)

async def _cmd_control_change(self, payload: dict) -> None:
    from .camera_core.backends import usb_backend
    if self._state.descriptor:
        await usb_backend.set_control(
            self._state.descriptor.device_path,
            payload["control"],
            payload["value"]
        )

async def _cmd_reprobe(self, payload: dict) -> None:
    if self._state.descriptor:
        from .camera_core.backends import usb_backend
        self._state.capabilities = await usb_backend.probe(
            self._state.descriptor.device_path
        )
```

### Validation

- [ ] All commands in spec handled
- [ ] Unknown commands report error
- [ ] Exceptions caught and reported
- [ ] Aliases work (record = start_recording)

---

## P4.4: Status Reporting

### Deliverables

Status callback integration and metrics emission.

### Implementation

```python
# In CamerasRuntime (bridge.py)

def _update_metrics(self) -> None:
    if not self._view:
        return

    # Calculate current FPS from recent frames
    # (Implementation depends on frame timing tracking)

    self._view.update_metrics(
        capture_fps=self._capture_fps,
        record_fps=self._record_fps if self._state.recording else 0,
        queue_depth=self._queue_depth
    )

async def _emit_telemetry(self) -> None:
    while True:
        await asyncio.sleep(self._config.telemetry.emit_interval_ms / 1000)

        if self._state.capturing:
            await self._report_status("telemetry", {
                "capture_fps": round(self._capture_fps, 1),
                "record_fps": round(self._record_fps, 1) if self._state.recording else None,
                "queue_depth": self._queue_depth,
                "frames_recorded": self._frames_recorded if self._state.recording else None
            })
```

### Validation

- [ ] Metrics updated every 5 frames
- [ ] Telemetry emitted at configured interval
- [ ] View receives metric updates
- [ ] Status callback invoked correctly
