# Cameras_CSI2 Documentation

> CSI camera module with Elm/Redux architecture and StubCodexSupervisor UI

## Quick Start

```bash
cd /home/rs-pi-2/Development/Logger/rpi_logger/modules/Cameras_CSI2

# Basic: open camera 0
python3 main.py --camera-index 0

# Auto-record to session directory
python3 main.py --camera-index 0 --record --output-dir /data/session_001

# Run tests (74 tests)
cd /home/rs-pi-2/Development/Logger
uv run pytest rpi_logger/modules/Cameras_CSI2/tests/ -v
```

---

## Documentation Structure

```
docs/
├── TASKS.md              ← Implementation status (all phases complete)
├── README.md             ← You are here
│
├── reference/            ← Background context
│   ├── mission.md        Goals, non-goals, scope
│   ├── hardware.md       Pi 5, sensors, constraints
│   ├── design.md         Principles and philosophy
│   ├── architecture.md   Legacy diagrams (pre-StubCodexSupervisor)
│   ├── current_system.md Analysis of CSICameras issues
│   └── picamera2_api.md  Key APIs and gotchas
│
├── specs/                ← Technical specifications
│   ├── components.md     CapturedFrame, FrameSource, etc.
│   ├── output_formats.md CSV columns, video format
│   ├── commands.md       Command protocol
│   ├── gui.md            UI requirements
│   └── debugging.md      Logging, traces
│
└── tasks/                ← Legacy task files (reference only)
```

---

## Architecture

See [../ARCHITECTURE.md](../ARCHITECTURE.md) for full details.

```
StubCodexSupervisor (UI shell)
    │
    ▼
CSI2CamerasRuntime (ModuleRuntime)
    │
    ├── Store (Elm/Redux)
    │   └── Pure state machine: (state, action) -> (new_state, effects)
    │
    ├── EffectExecutor (I/O boundary)
    │   └── Camera, encoder, timing CSV
    │
    └── CSI2CameraView (attaches to stub_view)
        └── Stateless rendering from state
```

---

## Key Files

| File | Purpose |
|------|---------|
| `main.py` | Entry point (StubCodexSupervisor) |
| `bridge.py` | CSI2CamerasRuntime (ModuleRuntime) |
| `core/` | Pure state machine (100% testable) |
| `infra/` | I/O boundary (effect executor) |
| `ui/view.py` | View that attaches to stub |
| `capture/` | Frame acquisition |
| `recording/` | Video/CSV output |

---

## Test Coverage

| Category | Tests | Notes |
|----------|-------|-------|
| Unit | 10 | Pure state machine |
| Integration | 11 | Store + mock executor |
| Widget | 53 | Comprehensive GUI coverage |
| **Total** | **74** | All passing |

### GUI Test Coverage
Widget tests cover all user interactions:
- View attachment and menu wiring
- Settings window open/apply/cancel
- All settings fields (resolution, fps, preview, record)
- Metrics rendering during streaming
- Recording state changes
- Frame rendering pipeline

---

*Last updated: 2026-01-07*
