# Cameras-USB2 Module

USB webcam capture module for the RPi Logger system.

## Quick Start

```bash
cd /home/rs-pi-2/Development/Logger
python -m rpi_logger.modules.Cameras-USB2.main_cameras
```

## Documentation Structure

```
docs/
├── TASKS.md                    # Master task tracker (start here)
├── README.md                   # This file
├── reference/
│   ├── mission.md              # Goals and non-goals
│   ├── design.md               # Principles and coding standards
│   └── architecture.md         # System overview
├── specs/
│   ├── components.md           # Interface definitions
│   ├── commands.md             # Protocol definitions
│   ├── output_formats.md       # File format specifications
│   └── gui.md                  # UI requirements
└── tasks/
    ├── phase1_foundation.md    # Core types and config
    ├── phase2_capture.md       # Capture pipeline
    ├── phase3_recording.md     # Recording system
    ├── phase4_runtime.md       # Runtime bridge
    ├── phase5_preview.md       # Preview system
    ├── phase6_settings.md      # Settings UI
    ├── phase7_integration.md   # Final integration
    ├── testing_unit.md         # Unit test requirements
    ├── testing_integration.md  # Integration test scenarios
    └── testing_stress.md       # Stress test criteria
```

## Agent Workflow

1. Read `TASKS.md` - find available task
2. Update task status to `in_progress`
3. Read task file in `tasks/`
4. Read relevant specs in `specs/`
5. Implement deliverables
6. Run validation checklist
7. Update `TASKS.md` status to `completed`

## Module Layout

```
Cameras-USB2/
├── main_cameras.py         # Entry point
├── bridge.py               # CamerasRuntime
├── config.py               # Configuration system
├── camera_core/
│   ├── __init__.py
│   ├── capture.py          # USBCapture class
│   ├── capabilities.py     # Capability normalization
│   └── backends/
│       └── usb_backend.py  # USB device probing
├── storage/
│   ├── __init__.py
│   └── session_paths.py    # Path resolution
├── app/
│   ├── view.py             # CameraView
│   └── widgets/
│       └── camera_settings_window.py
└── docs/                   # This documentation
```
