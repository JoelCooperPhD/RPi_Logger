# Phase 6: Runtime

> Orchestration and entry point

## Quick Reference

| | |
|-|-|
| **Status** | See [TASKS.md](../TASKS.md) |
| **Sub-tasks** | P6.1, P6.2, P6.3 |
| **Dependencies** | P1-P5 |
| **Effort** | Medium |
| **Key Specs** | [commands.md](../specs/commands.md) |

## Goal

Complete runtime integration with command handling and module entry point.

---

## Sub-Tasks

### P6.1: CSICameraRuntime

**File**: `runtime.py` (~300 lines)

Main orchestrator - coordinates all components.

```python
class CSICameraRuntime:
    def __init__(self, config: RuntimeConfig): ...

    async def start(self) -> None: ...
    async def stop(self) -> None: ...

    async def handle_command(self, command: dict) -> None: ...

    # Command handlers
    async def _handle_assign_device(self, cmd: dict) -> None: ...
    async def _handle_unassign_device(self, cmd: dict) -> None: ...
    async def _handle_start_recording(self, cmd: dict) -> None: ...
    async def _handle_stop_recording(self, cmd: dict) -> None: ...
    async def _handle_start_session(self, cmd: dict) -> None: ...
    async def _handle_stop_session(self, cmd: dict) -> None: ...

    @property
    def is_recording(self) -> bool: ...
```

**Key principle**: Runtime does ONLY orchestration, no frame handling.

---

### P6.2: Entry Point & Factory

**File**: `main.py` (~80 lines)

```python
async def main():
    config = RuntimeConfig.from_args()
    runtime = CSICameraRuntime(config)
    await runtime.start()

    async for line in stdin_reader():
        command = json.loads(line)
        await runtime.handle_command(command)

if __name__ == "__main__":
    asyncio.run(main())
```

**File**: `__init__.py` (~30 lines)

```python
from .runtime import CSICameraRuntime
from .config import RuntimeConfig
from .capture import CapturedFrame, FrameSource, PicamSource

__all__ = [
    "CSICameraRuntime",
    "RuntimeConfig",
    "CapturedFrame",
    "FrameSource",
    "PicamSource",
]
```

---

### P6.3: Configuration

**File**: `config.py` (~60 lines)

```python
@dataclass
class RuntimeConfig:
    camera_index: int = 0
    console_logging: bool = False
    debug_socket: Optional[str] = None
    metrics_port: Optional[int] = None

    @classmethod
    def from_args(cls) -> 'RuntimeConfig': ...

@dataclass
class CameraConfig:
    record_fps: float = 30.0
    preview_fps: float = 5.0
    preview_scale: str = "1/4"
    jpeg_quality: int = 85
```

---

## Command Protocol

### Inbound Commands

| Command | Parameters | Action |
|---------|------------|--------|
| `assign_device` | `device_id`, `camera_type`, `camera_stable_id`, etc. | Initialize camera |
| `unassign_device` | - | Release camera |
| `start_recording` | `session_dir`, `trial_number`, `trial_label` | Begin recording |
| `stop_recording` | - | End recording |
| `start_session` | `session_dir` | Set session directory |
| `stop_session` | - | Stop any recording |

### Outbound Status Messages

| Status | Payload | When |
|--------|---------|------|
| `ready` | - | Runtime initialized |
| `device_ready` | `device_id` | Camera assigned and first frame captured |
| `device_error` | `device_id`, `error` | Assignment failed |
| `recording_started` | `video_path`, `camera_id` | Recording begun |
| `recording_stopped` | `camera_id` | Recording ended |

### Deferred Device Ready

**Critical**: `device_ready` is sent AFTER first frame is successfully captured, not immediately after camera initialization.

---

## Validation Checklist

- [ ] All 3 files created
- [ ] `__init__.py` exports all public classes
- [ ] Integration test: Full startup/assign/record/stop/shutdown cycle
- [ ] Command test: All commands from parent work correctly
- [ ] Stress test: 1-hour continuous recording without drops

---

## Completion Criteria

When all validation items pass, update [TASKS.md](../TASKS.md).
