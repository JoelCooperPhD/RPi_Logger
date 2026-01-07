# Cameras-CSI2 Documentation

> Scientific-grade CSI camera capture for Raspberry Pi 5

## Quick Start for AI Agents

1. **Check available tasks**: [TASKS.md](TASKS.md)
2. **Read task instructions**: `tasks/phase{N}_{name}.md`
3. **Reference specs as needed**: `specs/*.md`
4. **Mark complete when done**: Update TASKS.md

---

## Documentation Structure

```
docs/
├── TASKS.md              ← START HERE (master task tracker)
├── README.md             ← You are here
│
├── reference/            ← Background context (read-only)
│   ├── mission.md        Goals, non-goals, scope
│   ├── hardware.md       Pi 5, sensors, constraints
│   ├── design.md         Principles and philosophy
│   ├── architecture.md   Diagrams, component overview
│   ├── current_system.md Analysis of what's broken
│   └── picamera2_api.md  Key APIs and gotchas
│
├── specs/                ← Technical specifications
│   ├── components.md     CapturedFrame, FrameSource, etc.
│   ├── output_formats.md CSV columns, video format
│   ├── commands.md       Command protocol
│   ├── gui.md            UI requirements
│   └── debugging.md      Logging, trace IDs, metrics
│
└── tasks/                ← Actionable task files
    ├── phase1_foundation.md
    ├── phase2_pipeline.md
    ├── phase3_recording.md
    ├── phase4_preview.md
    ├── phase5_view.md
    ├── phase6_runtime.md
    ├── phase7_hardening.md
    ├── testing_unit.md
    ├── testing_integration.md
    ├── testing_stress.md
    └── migration.md
```

---

## Task Dependency Graph

```
NO DEPENDENCIES (can start immediately):
  P1.1, P1.4, P2.3, P3.2, P3.4, P6.3

AFTER P1.1:
  P1.2, P2.1, P3.1

AFTER P1.2:
  P1.3

AFTER P1.4 + P2.1:
  P2.2 (FrameRouter)

AFTER P2.1:
  P4 (Preview)

AFTER P3.1 + P3.2 + P2.1:
  P3.3 (RecordingSession)

AFTER P4:
  P5 (View)

AFTER P1-P5:
  P6.1 (Runtime)

AFTER P6.1:
  P6.2 (Entry point)

AFTER P6:
  P7, T2, T3

AFTER P1 + P2:
  T1 (Unit tests)

AFTER P7 + T1-T3:
  M1 (Migration)
```

---

## What Can Be Parallelized

**Immediate (no dependencies)**:
- P1.1 + P1.4 + P2.3 + P3.2 + P3.4 + P6.3

**After P1.1**:
- P1.2 + P2.1 + P3.1

**After P1.2**:
- P1.3

---

## IMPORTANT: Folder Naming

The folder `Cameras-CSI2` has a hyphen which breaks Python imports. **Before starting implementation**, rename the folder:

```bash
cd /home/rs-pi-2/Development/Logger/rpi_logger/modules
mv Cameras-CSI2 Cameras_CSI2
```

All documentation references to `Cameras-CSI2` should use `Cameras_CSI2` in code imports.

---

## Project Setup (Before Starting)

Create these directories and `__init__.py` files before implementing tasks:

```bash
# Create directory structure
mkdir -p capture pipeline recording preview view/dialogs storage logs tests/{unit,integration,stress}

# Create __init__.py files
touch capture/__init__.py pipeline/__init__.py recording/__init__.py preview/__init__.py view/__init__.py view/dialogs/__init__.py

# Create empty test conftest
touch tests/conftest.py
```

Each phase's validation checklist includes exporting from `__init__.py`.

---

## Key References

| Topic | File | When to Read |
|-------|------|--------------|
| Hardware constraints | [reference/hardware.md](reference/hardware.md) | Before capture work |
| Component interfaces | [specs/components.md](specs/components.md) | Before any implementation |
| CSV/video formats | [specs/output_formats.md](specs/output_formats.md) | Before recording work |
| Picamera2 gotchas | [reference/picamera2_api.md](reference/picamera2_api.md) | Before PicamSource |
| Current system issues | [reference/current_system.md](reference/current_system.md) | To understand what we're fixing |

---

## Agent Workflow

```
1. Read TASKS.md
   └─► Find task with status=available, deps=completed

2. Update TASKS.md
   └─► Set status=in_progress, add agent ID

3. Read task file
   └─► tasks/phase{N}_{name}.md

4. Read relevant specs
   └─► specs/*.md (linked in task file)

5. Implement deliverables
   └─► Create files listed in task

6. Run validation checklist
   └─► Tests, benchmarks from task file

7. Update TASKS.md
   └─► Set status=completed, add date and notes
```

---

## Architecture Overview

See [reference/architecture.md](reference/architecture.md) for full diagrams.

```
Entry (main.py)
    │
    ▼
Runtime (runtime.py)
    │
    ├──► Capture (capture/) ──► Pipeline (pipeline/)
    │         │                       │
    │         ▼                       ├──► Recording (recording/)
    │    FrameSource                  └──► Preview (preview/)
    │         │
    └──► View (view/)
```

---

## Project Goals

1. **Frame-perfect timing**: If you request 5 FPS, you get exactly 5 FPS
2. **Hardware-accurate timestamps**: Sensor timestamps, not software timestamps
3. **Zero-compromise capture**: Tight loop, no allocations, no business logic
4. **Complete audit trail**: Every frame traceable via timing CSV
5. **Drop transparency**: Every drop logged with reason

See [reference/mission.md](reference/mission.md) for full context.
