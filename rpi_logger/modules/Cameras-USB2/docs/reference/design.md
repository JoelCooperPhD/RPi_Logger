# Design Principles: Cameras-USB2

## Coding Standards (MANDATORY)

| Requirement | Rationale |
|-------------|-----------|
| Modern asyncio patterns | Use async/await, not threads |
| Non-blocking I/O | All I/O via `asyncio.to_thread()` |
| No docstrings | Skip docstrings and obvious comments |
| Concise code | Optimize for AI readability |
| Type hints | Use type hints for self-documentation |
| Max 200 lines/file | Keep files small and focused |

## Architectural Principles

### 1. Separation of Concerns

```
bridge.py       → Orchestration, command handling
capture.py      → Frame acquisition only
capabilities.py → Camera introspection only
view.py         → Display only
config.py       → Configuration only
```

### 2. Async-First Design

```python
# CORRECT: Non-blocking subprocess
result = await asyncio.to_thread(subprocess.run, cmd, capture_output=True)

# WRONG: Blocking call
result = subprocess.run(cmd, capture_output=True)
```

### 3. Queue-Based Decoupling

```
Capture Thread → Frame Queue → Async Consumer → Preview/Encoder
     ↓              ↓               ↓
  Blocking      Bounded         Non-blocking
```

### 4. Fail-Fast with Recovery

```python
# Detect failure immediately
if not frame:
    raise DeviceLost(camera_id)

# Recover at orchestration layer
try:
    await capture_loop()
except DeviceLost:
    await attempt_reconnect()
```

## Naming Conventions

| Type | Convention | Example |
|------|------------|---------|
| Classes | PascalCase | `USBCapture`, `CameraView` |
| Functions | snake_case | `probe_camera`, `start_recording` |
| Constants | UPPER_SNAKE | `DEFAULT_FPS`, `MAX_QUEUE_SIZE` |
| Private | _prefix | `_capture_thread`, `_frame_queue` |
| Type aliases | PascalCase | `FrameData`, `ControlValue` |

## Error Handling

| Layer | Strategy |
|-------|----------|
| Backend | Raise specific exceptions (`DeviceLost`, `ProbeError`) |
| Capture | Propagate with context |
| Runtime | Catch, log, report status, attempt recovery |
| UI | Display user-friendly message |

## Configuration Hierarchy

```
CLI args → config.txt → ModulePreferences → Defaults
   ↓           ↓              ↓                ↓
 Highest    Medium          Lower           Lowest
```
