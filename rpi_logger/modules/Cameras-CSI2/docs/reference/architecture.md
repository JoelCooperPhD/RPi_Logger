# Architecture Overview

> System structure and data flow

## Layer Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              ENTRY LAYER                                     │
│  main.py - CLI parsing, supervisor setup, factory function                  │
└─────────────────────────────────────────────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                             RUNTIME LAYER                                    │
│  runtime.py - CSICameraRuntime                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  Orchestrates lifecycle, handles commands, coordinates components    │   │
│  │  DOES NOT touch frames directly                                      │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
                                     │
           ┌─────────────────────────┼─────────────────────────┐
           ▼                         ▼                         ▼
┌─────────────────────┐   ┌─────────────────────┐   ┌─────────────────────┐
│   CAPTURE LAYER     │   │   ROUTING LAYER     │   │    VIEW LAYER       │
│                     │   │                     │   │                     │
│  capture/           │   │  pipeline/          │   │  view/              │
│  ├─ source.py       │──▶│  ├─ router.py       │──▶│  ├─ view.py         │
│  ├─ picam.py        │   │  ├─ timing_gate.py  │   │  ├─ settings.py     │
│  └─ frame.py        │   │  └─ metrics.py      │   │  └─ dialogs/        │
│                     │   │                     │   │                     │
│  Ultra-tight loop   │   │  Frame distribution │   │  UI components      │
│  No business logic  │   │  Time-based gating  │   │  Theme integration  │
└─────────────────────┘   └─────────────────────┘   └─────────────────────┘
           │                         │
           │              ┌──────────┴──────────┐
           │              ▼                     ▼
           │   ┌─────────────────────┐   ┌─────────────────────┐
           │   │   RECORDING LAYER   │   │   PREVIEW LAYER     │
           │   │                     │   │                     │
           │   │  recording/         │   │  preview/           │
           │   │  ├─ recorder.py     │   │  ├─ processor.py    │
           │   │  ├─ encoder.py      │   │  └─ scaler.py       │
           │   │  └─ timing_csv.py   │   │                     │
           │   │                     │   │  Resize/convert     │
           │   │  Video + CSV output │   │  for display        │
           │   └─────────────────────┘   └─────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                            HARDWARE LAYER                                    │
│  Picamera2 library → libcamera → CSI Camera Hardware                        │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Folder Structure

```
Cameras-CSI2/
│
├── ARCHITECTURE.md          # Overview document
├── docs/                    # Detailed documentation
│
├── __init__.py              # Module entry point
├── main.py                  # CLI parsing, supervisor setup
├── runtime.py               # CSICameraRuntime - orchestration only
├── config.py                # Typed configuration dataclasses
│
├── capture/                 # SACRED - Frame acquisition only
│   ├── frame.py             # CapturedFrame dataclass
│   ├── source.py            # FrameSource protocol
│   └── picam_source.py      # Picamera2 implementation
│
├── pipeline/                # Frame routing and timing
│   ├── router.py            # FrameRouter
│   ├── timing_gate.py       # TimingGate
│   ├── frame_buffer.py      # Lock-free ring buffer
│   └── metrics.py           # FrameMetrics
│
├── recording/               # Video output
│   ├── recorder.py          # RecordingSession
│   ├── encoder.py           # VideoEncoder
│   ├── timing_csv.py        # TimingCSVWriter
│   └── session_paths.py     # Path resolution
│
├── preview/                 # Display output
│   ├── processor.py         # PreviewProcessor
│   └── scaler.py            # Frame scaling
│
├── view/                    # GUI layer
│   ├── view.py              # CSICameraView
│   ├── settings_window.py   # Settings window
│   └── dialogs/             # Dialogs
│
├── storage/                 # Persistence
│   └── known_cameras.json   # Settings cache
│
└── logs/                    # Module-specific logs
```

---

## Data Flow

```
Camera Sensor
    │
    ▼ (hardware frame buffer)
Picamera2 capture_request()
    │
    ├── SensorTimestamp extracted
    ├── monotonic_ns captured
    ├── wall_time captured
    │
    ▼
CapturedFrame created
    │
    ▼ (lock-free ring buffer, size=8)
FrameRouter
    │
    ├──► TimingGate (record) ──► Encoder ──► video.avi
    │                       └──► TimingCSVWriter ──► timing.csv
    │
    └──► TimingGate (preview) ──► PreviewProcessor ──► View
```

---

## Layer Responsibilities

| Layer | Purpose | Key Constraint |
|-------|---------|----------------|
| Entry | CLI, startup | Parse args, create runtime |
| Runtime | Orchestration | No frame handling |
| Capture | Frame acquisition | NO business logic, NO I/O |
| Pipeline | Frame distribution | Time-based decisions only |
| Recording | Disk output | Never blocks capture |
| Preview | Display output | Lowest priority, can drop |
| View | UI components | Inherits from base |
