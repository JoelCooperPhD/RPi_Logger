# Cameras_CSI2 Architecture

> Elm/Redux architecture with StubCodexSupervisor for consistent UI

## Quick Start

```bash
cd /home/rs-pi-2/Development/Logger/rpi_logger/modules/Cameras_CSI2

# Basic: open camera 0
python3 main.py --camera-index 0

# Auto-record to session directory
python3 main.py --camera-index 0 --record --output-dir /data/session_001
```

Or run tests:
```bash
cd /home/rs-pi-2/Development/Logger
uv run pytest rpi_logger/modules/Cameras_CSI2/tests/ -v
```

---

## Architecture Overview

**StubCodexSupervisor** provides the UI shell (menus, logging panel, metrics).
**Elm/Redux Store** manages all business logic internally.

```
┌─────────────────────────────────────────────────────────────────┐
│                    StubCodexSupervisor                          │
│  (UI shell: menus, logging panel, metrics, window management)   │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                    CSI2CamerasRuntime                           │
│             (implements ModuleRuntime interface)                │
│                                                                 │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │                         Store                             │  │
│  │              (single source of truth)                     │  │
│  │                                                           │  │
│  │   state: AppState (frozen dataclass)                      │  │
│  │   dispatch(action) -> update() -> new_state + effects     │  │
│  │   subscribe(callback) -> UI updates                       │  │
│  └─────────────────────────┬─────────────────────────────────┘  │
│                            │                                    │
│              ┌─────────────┴─────────────┐                      │
│              ▼                           ▼                      │
│  ┌─────────────────────┐    ┌─────────────────────────────┐     │
│  │   EffectExecutor    │    │     CSI2CameraView          │     │
│  │   (I/O boundary)    │    │  (attaches to stub_view)    │     │
│  │                     │    │                             │     │
│  │  - ProbeCamera      │    │  - build_stub_content()     │     │
│  │  - OpenCamera       │    │  - build_io_stub_content()  │     │
│  │  - StartEncoder     │    │  - render(state)            │     │
│  │  - ...              │    │  - push_frame(ppm)          │     │
│  └─────────────────────┘    └─────────────────────────────┘     │
└─────────────────────────────────────────────────────────────────┘
```

### Data Flow

```
User Action (button click, menu select, command)
    │
    ▼
dispatch(Action)              ◄── Pure data describing intent
    │
    ▼
update(state, action)         ◄── Pure function, no I/O
    │
    ├─► new_state             ◄── Immutable (frozen dataclass)
    │       │
    │       ▼
    │   CSI2CameraView.render(state)  ◄── UI updates
    │
    └─► effects[]             ◄── Side-effect descriptions
            │
            ▼
    EffectExecutor            ◄── I/O boundary
            │
            ├─► Hardware (camera, encoder)
            │
            └─► dispatch(ResultAction)  ◄── Feedback loop
```

---

## Key Files

| File | Purpose |
|------|---------|
| `main.py` | Entry point using StubCodexSupervisor |
| `bridge.py` | CSI2CamerasRuntime (ModuleRuntime interface) |
| `core/state.py` | Frozen dataclasses: AppState, CameraStatus, etc. |
| `core/actions.py` | Action types: AssignCamera, StartRecording, etc. |
| `core/effects.py` | Effect descriptions: ProbeCamera, StartEncoder, etc. |
| `core/update.py` | Pure reducer: (state, action) -> (new_state, effects) |
| `core/store.py` | Single source of truth with dispatch/subscribe |
| `infra/effect_executor.py` | Executes effects, dispatches result actions |
| `infra/command_handler.py` | Stdin/stdout protocol for logger integration |
| `ui/view.py` | CSI2CameraView that attaches to stub_view |
| `capture/picam_source.py` | Picamera2 implementation |
| `recording/session.py` | Video/CSV output |

---

## Folder Structure

```
Cameras_CSI2/
├── ARCHITECTURE.md       ← This file
├── config.txt            ← Module configuration
├── main.py               ← Entry point (StubCodexSupervisor)
├── bridge.py             ← CSI2CamerasRuntime (ModuleRuntime)
├── __init__.py           ← Module exports
│
├── core/                 ← Pure state management (100% testable)
│   ├── state.py          ← Frozen dataclasses
│   ├── actions.py        ← Action types
│   ├── effects.py        ← Effect descriptions
│   ├── update.py         ← Pure reducer
│   └── store.py          ← Single source of truth
│
├── infra/                ← I/O boundary
│   ├── effect_executor.py   ← Executes effects
│   └── command_handler.py   ← Stdin/stdout protocol
│
├── capture/              ← Frame acquisition
│   ├── frame.py          ← CapturedFrame dataclass
│   ├── source.py         ← FrameSource protocol
│   ├── picam_source.py   ← Picamera2 implementation
│   └── frame_buffer.py   ← Lock-free buffer
│
├── recording/            ← Video/CSV output
│   ├── encoder.py        ← VideoEncoder wrapper
│   ├── timing_writer.py  ← CSV timing writer
│   └── session.py        ← Session management
│
├── ui/                   ← UI (attaches to stub_view)
│   ├── view.py           ← CSI2CameraView
│   ├── renderer.py       ← Standalone renderer (for tests)
│   └── widgets/
│       └── settings_window.py
│
└── tests/                ← Full test coverage
    ├── conftest.py       ← Shared fixtures
    ├── unit/             ← Pure function tests
    ├── integration/      ← Store + executor tests
    └── widget/           ← Programmatic Tkinter tests
```

---

## StubCodexSupervisor Integration

The module uses StubCodexSupervisor for:
- Window management and geometry
- Menu bar (File, View)
- IO stub content area (metrics display)
- Logging panel
- Status messages to parent process

**Key integration points in CSI2CamerasRuntime:**

```python
# Attach view to stub_view
self.view = CSI2CameraView(ctx.view, logger=self.logger)
self.view.attach()  # calls stub_view.build_stub_content()

# Subscribe view to store updates
self.store.subscribe(self.view.render)

# Set preview callback for frames
self.executor.set_preview_callback(self.view.push_frame)
```

**Key integration points in CSI2CameraView:**

```python
def attach(self):
    # Main content area
    self._stub_view.build_stub_content(builder)

    # IO metrics area
    self._stub_view.build_io_stub_content(_builder)

    # Menus
    self._stub_view.view_menu.add_command(...)
    self._stub_view.finalize_view_menu()
    self._stub_view.finalize_file_menu()
```

---

## Testing

**73 tests pass** (10 unit + 11 integration + 52 widget)

### Unit Tests (Pure, No GUI)
```python
def test_start_recording():
    state = AppState(camera_status=CameraStatus.STREAMING)
    action = StartRecording(session_dir=Path("/data"), trial=1)
    new_state, effects = update(state, action)
    assert new_state.recording_status == RecordingStatus.RECORDING
```

### Widget Tests (Comprehensive GUI Coverage)
All GUI interactions are tested programmatically:
```python
def test_settings_apply(view_with_dispatch, tk_root):
    view, actions = view_with_dispatch
    view._on_settings_click()
    view._settings_window.preview_scale_var.set("1/2")
    view._settings_window.apply_button.invoke()
    tk_root.update()
    assert actions[0].settings.preview_scale == 0.5
```

### Integration Tests (Store + Mock Executor)
```python
async def test_camera_assignment():
    store = Store(initial_state())
    store.set_effect_handler(MockEffectExecutor())
    await store.dispatch(AssignCamera(0))
    assert store.state.camera_status == CameraStatus.STREAMING
```

Run tests:
```bash
uv run pytest rpi_logger/modules/Cameras_CSI2/tests/ -v
```

---

## Preview Settings

Default preview configuration (optimized for low overhead):
- **Scale**: 0.25 (1/4 of capture resolution)
- **FPS**: 10 fps
- **Never upscales**: Preview is always native or smaller

Configured via `CameraSettings`:
```python
@dataclass(frozen=True)
class CameraSettings:
    resolution: tuple[int, int] = (1456, 1088)  # IMX296 native
    capture_fps: int = 60  # IMX296 max at native res
    preview_fps: int = 10
    preview_scale: float = 0.25  # 1/4 scale default
    record_fps: int = 5
```

---

## CLI Arguments

| Argument | Description |
|----------|-------------|
| `--camera-index N` | CSI camera index (default: 0) |
| `--record` | Start recording immediately on camera ready |
| `--output-dir PATH` | Session directory for recordings |

---

## Status Messages

The runtime sends JSON status messages to stdout:

| Message | When |
|---------|------|
| `ready` | Runtime initialized, waiting for commands |
| `device_ready` | Camera assigned and streaming |
| `device_error` | Camera assignment failed |
| `recording_started` | Recording begun |
| `recording_stopped` | Recording ended |

---

*Last updated: 2026-01-07*
