# Cameras_CSI2 Task Tracker

> **Implementation Complete** - Elm/Redux architecture with StubCodexSupervisor

## Current Status

| Metric | Value |
|--------|-------|
| Tests Passing | 73/73 |
| Core Complete | Yes |
| UI Complete | Yes (StubCodexSupervisor) |
| GUI Tests | Comprehensive (52 widget tests) |
| Recording | Basic (needs encoder work) |

---

## Quick Start

```bash
cd /home/rs-pi-2/Development/Logger/rpi_logger/modules/Cameras_CSI2

# Basic: open camera 0
python3 main.py --camera-index 0

# Auto-record to session directory
python3 main.py --camera-index 0 --record --output-dir /data/session_001

# Run tests (73 tests)
cd /home/rs-pi-2/Development/Logger
uv run pytest rpi_logger/modules/Cameras_CSI2/tests/ -v
```

---

## Completed Phases

### Phase 0: Project Setup ✓

| ID | Task | Status | File(s) |
|----|------|--------|---------|
| P0.1 | Directory structure | completed | `core/`, `infra/`, `ui/`, `capture/`, `recording/`, `tests/` |
| P0.2 | Init files | completed | `__init__.py` in each directory |
| P0.3 | Test fixtures | completed | `tests/conftest.py` |

### Phase 1: Core State Machine ✓

| ID | Task | Status | File |
|----|------|--------|------|
| P1.1 | State dataclasses | completed | `core/state.py` |
| P1.2 | Action types | completed | `core/actions.py` |
| P1.3 | Effect descriptions | completed | `core/effects.py` |
| P1.4 | Update reducer | completed | `core/update.py` |
| P1.5 | Store implementation | completed | `core/store.py` |

### Phase 2: Capture Layer ✓

| ID | Task | Status | File |
|----|------|--------|------|
| P2.1 | Frame dataclass | completed | `capture/frame.py` |
| P2.2 | Source protocol | completed | `capture/source.py` |
| P2.3 | Frame buffer | completed | `capture/frame_buffer.py` |
| P2.4 | Picamera2 source | completed | `capture/picam_source.py` |

### Phase 3: Recording Layer ✓

| ID | Task | Status | File |
|----|------|--------|------|
| P3.1 | Timing CSV writer | completed | `recording/timing_writer.py` |
| P3.2 | Video encoder | completed | `recording/encoder.py` |
| P3.3 | Session manager | completed | `recording/session.py` |

### Phase 4: Infrastructure ✓

| ID | Task | Status | File |
|----|------|--------|------|
| P4.1 | Effect executor | completed | `infra/effect_executor.py` |
| P4.2 | Command handler | completed | `infra/command_handler.py` |

### Phase 5: UI Layer ✓

| ID | Task | Status | File |
|----|------|--------|------|
| P5.1 | CSI2CameraView | completed | `ui/view.py` |
| P5.2 | Standalone renderer | completed | `ui/renderer.py` |
| P5.3 | Settings window | completed | `ui/widgets/settings_window.py` |

### Phase 6: Entry Point ✓

| ID | Task | Status | File |
|----|------|--------|------|
| P6.1 | Main (StubCodexSupervisor) | completed | `main.py` |
| P6.2 | Bridge (ModuleRuntime) | completed | `bridge.py` |
| P6.3 | Module exports | completed | `__init__.py` |

### Testing ✓

| ID | Task | Status | Files |
|----|------|--------|-------|
| T1 | Unit tests | completed | `tests/unit/test_update.py` (10 tests) |
| T2 | Integration tests | completed | `tests/integration/test_store.py` (11 tests) |
| T3 | Widget tests | completed | `tests/widget/test_renderer.py`, `test_settings.py`, `test_view.py` (52 tests) |

**Widget test coverage** (`test_view.py`):
- View attachment and menu wiring
- Settings window open/apply/cancel
- All settings fields (preview_scale, preview_fps, record_fps)
- Metrics rendering during streaming/recording
- Frame rendering pipeline
- End-to-end workflows

**Note**: Resolution is NOT user-configurable - always uses sensor native (1456×1088 for IMX296)

---

## Architecture Summary

```
StubCodexSupervisor (UI shell)
    │
    ▼
CSI2CamerasRuntime (ModuleRuntime)
    │
    ├── Store (Elm/Redux)
    │   ├── state.py (frozen dataclasses)
    │   ├── actions.py (user intents)
    │   ├── effects.py (side-effect descriptions)
    │   ├── update.py (pure reducer)
    │   └── store.py (dispatch/subscribe)
    │
    ├── EffectExecutor (I/O boundary)
    │   ├── Camera probing/opening
    │   ├── Capture loop
    │   └── Recording control
    │
    └── CSI2CameraView (attaches to stub_view)
        ├── build_stub_content()
        ├── build_io_stub_content()
        └── render(state)
```

---

## Future Work

| Task | Priority | Notes |
|------|----------|-------|
| Hardware encoder | High | Use picamera2 native H.264 |
| Settings persistence | Medium | Cache to known_cameras.json |
| Live camera controls | Medium | Exposure, gain sliders |
| Multi-camera support | Low | Multiple instances via parent |

---

## Preview Settings

Default preview configuration (optimized for low overhead):
- **Scale**: 0.25 (1/4 of capture resolution)
- **FPS**: 10 fps
- **Never upscales**: Preview is always native or smaller

## CLI Arguments

| Argument | Description |
|----------|-------------|
| `--camera-index N` | CSI camera index (default: 0) |
| `--record` | Start recording immediately on camera ready |
| `--output-dir PATH` | Session directory for recordings |

---

## Coding Standards

| Requirement | Rationale |
|-------------|-----------|
| Modern asyncio | `async/await`, not threads (except capture) |
| Non-blocking I/O | All I/O via `asyncio.to_thread()` |
| No docstrings | Skip docstrings and obvious comments |
| Type hints | Self-documenting code |
| Max 200 lines/file | AI context efficiency |
| Frozen dataclasses | Immutable state for testability |

---

*Last updated: 2026-01-07*
