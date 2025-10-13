# Camera Core Module

This directory contains the core camera system components with simplified 2-loop architecture.

## Component Architecture

The camera system uses a **simplified 2-loop architecture** for optimal performance:

```
Camera Hardware (configurable 1-60 FPS)
    ↓
Capture Loop → tight async capture at hardware FPS
    ↓
Processor Loop (polls capture directly) → orchestrates processing
    ├→ Overlay Renderer → adds text, FPS, counters
    ├→ Display Manager → thread-safe preview frames
    └→ Recording Module → modular recording subsystem
```

### Core Modules

**1. `camera_capture_loop.py`** - Tight async capture at camera native FPS
- Captures frames from picamera2 at hardware rate (configurable 1-60 FPS)
- Extracts hardware FPS from camera metadata (`FrameDuration`)
- Stores latest frame atomically for processor to poll
- Tracks capture FPS with rolling window

**2. `camera_processor.py`** - Processing orchestrator (direct polling)
- Polls capture loop directly for new frames (1ms intervals)
- Detects new frame arrivals via reference comparison
- Converts RGB to BGR for OpenCV
- Passes to overlay renderer
- Sends to display manager (thread-safe)
- Submits metadata to recorder (if recording)
- Tracks processing FPS independently

**3. `camera_overlay.py`** - Pure overlay rendering (stateless)
- Text overlays: camera ID, timestamp, session name
- FPS display showing hardware and processing FPS
- Frame counters with accurate tracking
- Recording indicator with filename
- Configurable styling, colors, backgrounds

**4. `camera_display.py`** - Thread-safe display frame storage
- Stores latest preview frame with lock
- Main thread reads frames for `cv2.imshow()`
- Decouples async processing from sync display

**5. `recording/` subdirectory** - Modular recording subsystem
- **`manager.py`** - Recording coordinator (public API)
  - Orchestrates all recording components
  - Handles start/stop lifecycle
  - MP4 remuxing coordination
- **`encoder.py`** - H.264 hardware encoder wrapper
  - Simple start/stop interface
  - Hardware-accelerated encoding via picamera2
- **`overlay.py`** - Frame overlay handler
  - Zero-copy overlay via MappedArray
  - Frame number burning to video stream
- **`csv_logger.py`** - CSV timing logger (threaded)
  - Non-blocking CSV logging in separate thread
  - Frame timing diagnostics with drop tracking
- **`remux.py`** - Video format conversion utilities
  - H.264 to MP4 container conversion
  - FPS correction from timing data

**6. `camera_handler.py`** - Single camera coordinator
- Initializes camera hardware at configured FPS (1-60)
- Creates and starts capture/processor loops (2 loops)
- Loads overlay configuration
- Manages recording start/stop
- Provides frame access for preview

**7. `camera_system.py`** - Multi-camera system coordinator
- Manages multiple camera handlers
- Handles interactive/slave/headless modes
- Processes JSON commands (start/stop recording, snapshots)
- Creates session directories
- Signal handling for graceful shutdown

**8. `camera_supervisor.py`** - Async supervisor wrapper
- Wraps CameraSystem with retry logic
- Automatic recovery on hardware failures
- Used by main_camera.py for robustness

**9. `camera_utils.py`** - Utility classes
- `RollingFPS`: FPS tracking with sliding window
- `FrameTimingMetadata`: Dataclass for frame metadata
- `load_config_file()`: Configuration file loading

**10. `commands/` subdirectory** - JSON command protocol
- Command handler, protocol definitions, and exports
- Used for slave mode programmatic control

**11. `config/` subdirectory** - Configuration management
- Config file loading and camera configuration utilities
- Resolution presets and FPS validation

**12. `modes/` subdirectory** - Operation modes
- Base mode class with common functionality
- Interactive, slave, and headless mode implementations

## Key Architecture Features

### Simplified 2-Loop Design
Previous architecture had 3 loops (capture → collator → processor). The collator loop was unnecessary complexity - it just buffered frames between capture and processor. Now:
- **Capture Loop**: Fast hardware frame capture
- **Processor Loop**: Polls capture directly, handles all processing

Benefits:
- Simpler code flow
- Fewer moving parts
- Less overhead
- Easier to understand and maintain

### Hardware FPS Flow
```
1. Camera metadata: FrameDuration µs
2. Capture loop: Extracts → hardware_fps
3. Processor: Polls capture → gets hardware_fps
4. Overlay: Displays hardware_fps + processing_fps
```

### Modular Recording System
Recording logic is split into focused modules in `recording/` subdirectory:
- **manager.py** (207 lines) - Coordinates all recording operations
- **encoder.py** (87 lines) - H.264 encoder wrapper
- **overlay.py** (119 lines) - Frame overlay handler
- **csv_logger.py** (216 lines) - CSV logging in separate thread
- **remux.py** (160 lines) - Video format conversion

This modular design makes the code:
- Easier to test (test components independently)
- Easier to understand (single responsibility per module)
- Easier to maintain (changes isolated to specific modules)

## Performance Targets

- **Camera Hardware**: Configurable 1-60 FPS
- **Capture Loop**: Matches camera FPS
- **Processor Loop**: Polls at ~1ms intervals, processes at frame arrival rate
- **Display Update**: ~30 Hz (preview windows)
- **Recording**: Hardware H.264 encoding with minimal CPU usage

## File Structure

```
camera_core/
├── camera_capture_loop.py      # Async capture at camera FPS
├── camera_processor.py         # Processing orchestrator (polls capture)
├── camera_overlay.py           # Overlay rendering
├── camera_display.py           # Thread-safe display storage
├── camera_handler.py           # Single camera coordinator (2 loops)
├── camera_system.py            # Multi-camera system
├── camera_supervisor.py        # Retry wrapper
├── camera_utils.py             # Utilities (FPS tracking, etc.)
├── recording/                  # Modular recording subsystem
│   ├── manager.py              # Recording coordinator
│   ├── encoder.py              # H.264 encoder wrapper
│   ├── overlay.py              # Frame overlay handler
│   ├── csv_logger.py           # CSV timing logger
│   ├── remux.py                # Video conversion utilities
│   └── __init__.py             # Recording exports
├── commands/                   # JSON command protocol
│   ├── command_handler.py
│   ├── command_protocol.py
│   └── __init__.py
├── config/                     # Configuration management
│   ├── config_loader.py
│   ├── camera_config.py
│   └── __init__.py
├── modes/                      # Operation modes
│   ├── base_mode.py
│   ├── interactive_mode.py
│   ├── slave_mode.py
│   ├── headless_mode.py
│   └── __init__.py
├── __init__.py                 # Package exports
└── README.md                   # This file
```

## Debugging

Each module has its own logger:
- `CameraCapture{N}` - Capture loop
- `CameraProcessor{N}` - Processing loop
- `CameraOverlay{N}` - Overlay rendering
- `CameraDisplay{N}` - Display management
- `CameraRecorder` - Video recording (all recording modules)
- `H264EncoderWrapper` - Hardware encoder
- `FrameOverlay` - Frame overlay handler
- `CSVLogger` - CSV timing logger
- `Camera{N}` - Camera handler
- `CameraSystem` - System coordinator
- `CameraSupervisor` - Supervisor wrapper

Set `logging.basicConfig(level=logging.DEBUG)` for detailed output.

## Recent Updates

### Architecture Simplification (2025-10-13)
- **Removed collator loop** (191 lines eliminated)
  - Unnecessary buffering layer between capture and processor
  - Processor now polls capture loop directly
  - Simpler 2-loop architecture (capture → processor)

- **Refactored recording system** into modular subdirectory
  - Split monolithic 407-line `camera_recorder.py` into 5 focused modules
  - Better organization and maintainability
  - Each module has single responsibility

- **Code reduction**: -950 lines total
  - Removed dead code (655 lines)
  - Removed collator loop (191 lines)
  - Reorganized recording into focused modules

### Frame Number Overlay (2025-10-12)
- Frame numbers burned into recording via post_callback
- Zero-copy overlay using MappedArray
- Correlates video frames with CSV timing data

### Hardware FPS Decoupling (2025-10-10)
- Camera hardware captures at configured FPS (1-60)
- Hardware FPS extracted from metadata
- FPS overlay shows hardware + processing rates
