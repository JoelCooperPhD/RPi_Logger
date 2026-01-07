# Cameras_CSI2 Architecture

> Scientific-grade CSI camera capture for Raspberry Pi 5

## Quick Start for AI Agents

1. **Check available tasks**: [docs/TASKS.md](docs/TASKS.md)
2. **Read coding standards**: [docs/reference/design.md](docs/reference/design.md)
3. **Start implementing**: Pick an available task, mark it in progress

---

## Project Goals

- **Frame-perfect timing**: Request 5 FPS → get exactly 5 FPS
- **Hardware timestamps**: Sensor exposure time, not software receipt
- **Zero-compromise capture**: Tight loop, no allocations, no business logic
- **Complete audit trail**: Every frame traceable via timing CSV
- **Drop transparency**: Every drop logged with reason

---

## Architecture Overview

```
Entry (main.py)
    │
    ▼
Runtime (runtime.py) ─── orchestration only, no frame handling
    │
    ├──► Capture (capture/) ──► Pipeline (pipeline/)
    │         │                       │
    │         ▼                       ├──► Recording (recording/)
    │    FrameSource                  └──► Preview (preview/)
    │         │
    └──► View (view/)
```

**Data flow**:
```
Camera → capture_request() → CapturedFrame → FrameBuffer → FrameRouter
                                                               │
                                     ├── TimingGate(record) → Encoder → .avi
                                     │                     → CSV → .csv
                                     └── TimingGate(preview) → View
```

---

## Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| FPS control | Time-based gating | Frame counting drifts |
| Timestamps | Sensor + mono + wall | Full traceability |
| Capture | Dedicated thread | Lowest latency |
| Everything else | asyncio | Non-blocking, composable |
| Video format | MJPEG/AVI | No H.264 on Pi 5, frame-accurate |
| Preview scaling | Software | Pi 5 ISP lores broken |

---

## Coding Standards

**MANDATORY** - Read [docs/reference/design.md](docs/reference/design.md)

- Modern asyncio (not threads, except capture loop)
- Non-blocking I/O via `asyncio.to_thread()`
- No docstrings, skip obvious comments
- Type hints for self-documenting code
- Concise code for AI readability

---

## Documentation Structure

```
docs/
├── TASKS.md              ← START HERE (task tracker)
├── README.md             ← Navigation
│
├── reference/            ← Background (read-only)
│   ├── mission.md        ← Goals, non-goals
│   ├── hardware.md       ← Pi 5, sensor constraints
│   ├── design.md         ← Principles, coding standards
│   ├── architecture.md   ← Diagrams
│   ├── current_system.md ← What's broken
│   └── picamera2_api.md  ← API gotchas
│
├── specs/                ← Technical specs
│   ├── components.md     ← CapturedFrame, FrameSource, etc.
│   ├── output_formats.md ← CSV, video format
│   ├── commands.md       ← Command protocol
│   ├── gui.md            ← UI requirements
│   └── debugging.md      ← Logging, traces
│
└── tasks/                ← Actionable tasks
    ├── phase1_foundation.md
    ├── phase2_pipeline.md
    ├── phase3_recording.md
    ├── phase4_preview.md
    ├── phase5_view.md
    ├── phase6_runtime.md
    ├── phase7_hardening.md
    ├── testing_*.md
    └── migration.md
```

---

## Folder Structure

```
Cameras_CSI2/
├── ARCHITECTURE.md       ← This file
├── docs/                 ← Detailed documentation
│
├── __init__.py           ← Module entry
├── main.py               ← CLI, startup
├── runtime.py            ← Orchestration
├── config.py             ← Configuration
│
├── capture/              ← SACRED - frame acquisition only
│   ├── frame.py          ← CapturedFrame dataclass
│   ├── source.py         ← FrameSource protocol
│   └── picam_source.py   ← Picamera2 implementation
│
├── pipeline/             ← Frame routing
│   ├── router.py         ← FrameRouter
│   ├── timing_gate.py    ← TimingGate
│   ├── frame_buffer.py   ← Lock-free buffer
│   └── metrics.py        ← FrameMetrics
│
├── recording/            ← Video output
│   ├── recorder.py       ← RecordingSession
│   ├── encoder.py        ← VideoEncoder
│   ├── timing_csv.py     ← TimingCSVWriter
│   └── session_paths.py  ← Path resolution
│
├── preview/              ← Display
│   ├── processor.py      ← PreviewProcessor
│   └── scaler.py         ← Scaling
│
├── view/                 ← GUI
│   ├── view.py           ← CSICameraView
│   ├── settings_window.py
│   └── dialogs/
│
├── storage/              ← Persistence
└── logs/                 ← Runtime logs
```

---

## Task Summary

| Phase | Tasks | Focus |
|-------|-------|-------|
| P1: Foundation | 4 | CapturedFrame, FrameSource, PicamSource, FrameBuffer |
| P2: Pipeline | 3 | TimingGate, FrameRouter, FrameMetrics |
| P3: Recording | 4 | TimingCSV, Encoder, RecordingSession, Paths |
| P4: Preview | 1 | PreviewProcessor, Scaler |
| P5: View | 1 | GUI layer |
| P6: Runtime | 3 | CSICameraRuntime, Entry point, Config |
| P7: Hardening | 1 | Error handling, graceful degradation |
| Testing | 3 | Unit, Integration, Stress |
| Migration | 1 | Cutover from CSICameras |

**Total**: 21 tasks (18 sub-tasks + 3 testing + 1 migration)

See [docs/TASKS.md](docs/TASKS.md) for detailed status and dependencies.

---

*Last updated: 2026-01-07*
