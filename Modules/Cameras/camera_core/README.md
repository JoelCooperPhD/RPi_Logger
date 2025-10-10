# Camera Core Module

This directory contains the core camera system components with built-in standalone tests.

## Component Architecture

The camera system uses a 3-loop architecture for optimal performance:

```
Camera Hardware (30 FPS)
    ↓
Capture Loop (30 FPS) → extracts hardware_fps from metadata
    ↓
Collator Loop (10 FPS) → timing-based frame collation
    ↓
Processor Loop → orchestrates processing pipeline
    ├→ Overlay Renderer → adds text, FPS, counters
    ├→ Display Manager → thread-safe preview frames
    └→ Recording Manager → ffmpeg encoding + timing CSV
```

### Core Modules

**1. `camera_capture_loop.py`** - Tight async capture at camera native FPS
- Captures frames from picamera2 at hardware rate (30 FPS)
- Extracts hardware FPS from camera metadata (`FrameDuration`)
- Stores latest frame atomically for collator to grab
- Tracks capture FPS with rolling window

**2. `camera_collator_loop.py`** - Timing-based frame collation
- Runs at precise intervals (e.g., 10 FPS for display/recording)
- Grabs latest frame from capture loop
- Duplicates frames when collation FPS > camera FPS
- Skips frames when collation FPS < camera FPS
- Passes hardware_fps metadata through the pipeline

**3. `camera_processor.py`** - Processing orchestrator (the "glue")
- Gets frames from collator queue
- Converts RGB to BGR for OpenCV
- Passes to overlay renderer
- Resizes for preview display
- Sends to display manager (thread-safe)
- Submits to recorder (if recording)

**4. `camera_overlay.py`** - Pure overlay rendering (stateless)
- Text overlays: camera ID, timestamp, session name
- FPS display: `FPS_10: 10 / 30` (collation / hardware)
- Frame counters: `Frames: 100 / 300` (collated / captured)
- Recording indicator with filename
- Configurable styling, colors, backgrounds

**5. `camera_display.py`** - Thread-safe display frame storage
- Stores latest preview frame with lock
- Main thread reads frames for `cv2.imshow()`
- Decouples async processing from sync display

**6. `camera_recorder.py`** - Video recording with ffmpeg
- H.264 encoding via ffmpeg subprocess
- Frame timing CSV output for diagnostics
- Consistent FPS enforcement
- Tracks duplicated/dropped frames

**7. `camera_handler.py`** - Single camera coordinator
- Initializes camera hardware at 30 FPS
- Creates and starts capture/collator/processor loops
- Loads overlay configuration
- Manages recording start/stop
- Provides frame access for preview

**8. `camera_system.py`** - Multi-camera system coordinator
- Manages multiple camera handlers
- Handles interactive/slave/headless modes
- Processes JSON commands (start/stop recording, snapshots)
- Creates session directories
- Signal handling for graceful shutdown

**9. `camera_supervisor.py`** - Async supervisor wrapper
- Wraps CameraSystem with retry logic
- Automatic recovery on hardware failures
- Used by main_camera.py for robustness

**10. `camera_utils.py`** - Utility classes
- `RollingFPS`: FPS tracking with sliding window
- `FrameTimingMetadata`: Dataclass for frame metadata
- `load_config_file()`: Configuration file loading

**11. `__init__.py`** - Package initialization
- Exports public API for external use

## Key Architecture Features

### Hardware FPS Decoupling
The camera hardware captures at 30 FPS (configurable), while collation/display/recording runs at a different FPS (e.g., 10 FPS). This allows:
- Maximum camera capture rate for best quality
- Lower processing/recording rate for efficiency
- Frame duplication when output > camera rate
- Frame skipping when output < camera rate

### Three Independent Async Loops
Each camera has 3 async loops running concurrently:
1. **Capture**: Tight loop grabbing frames as fast as camera provides them
2. **Collator**: Timer-based loop delivering frames at precise intervals
3. **Processor**: Orchestration loop handling overlays, display, and recording

### FPS Metadata Flow
```
1. Camera metadata: FrameDuration=33332µs
2. Capture loop: Extracts → hardware_fps=30.00
3. Collator loop: Gets hardware_fps via get_hardware_fps()
4. Processor: Receives hardware_fps in frame_data dict
5. Overlay: Displays "FPS_10: 10 / 30"
```

## Running Standalone Tests

### Test Capture Loop

Tests the tight camera capture loop in isolation:

```bash
cd /home/rs-pi-2/Development/RPi_Logger/Modules/Cameras/camera_core
uv run python camera_capture_loop.py
```

**What it tests:**
- Camera initialization at 30 FPS
- Frame capture at native hardware rate
- Hardware FPS extraction from metadata
- Rolling FPS tracking accuracy
- Frame count progression
- Clean shutdown

**Expected output:**
- Total frames: ~290-300 in 10 seconds
- FPS (calc): ~30.0
- FPS (hw): 30.00 (from metadata)
- Frame shape: (1080, 1920, 4)

**Exit codes:**
- `0` = Test passed
- `1` = Test failed or interrupted

**Test duration:** ~10 seconds

### Test Collator Loop (Multi-FPS)

Tests the timing-based collation loop with multiple FPS scenarios:

```bash
cd /home/rs-pi-2/Development/RPi_Logger/Modules/Cameras/camera_core
uv run python camera_collator_loop.py
```

**What it tests:**
- **60 FPS Test**: Collation at 2x camera rate (tests duplicate frame generation)
- **30 FPS Test**: Collation at camera rate (tests 1:1 frame matching)
- **10 FPS Test**: Collation at 1/3 camera rate (tests frame skipping)
- Capture loop running continuously at 30 FPS
- Independent timing for each collation FPS
- Hardware FPS metadata propagation
- FPS accuracy and frame counting

**Expected output (5 seconds per test):**
- **60 FPS**: ~300 collated frames, ~150 duplicates, 60.0 FPS, 200% ratio
- **30 FPS**: ~150 collated frames, 0 duplicates, 30.0 FPS, ~100% ratio
- **10 FPS**: ~50 collated frames, 0 duplicates, 10.0 FPS, ~33% ratio

**Exit codes:**
- `0` = All tests passed
- `1` = Test failed or interrupted

**Test duration:** ~25 seconds total (3 tests × 5s + 2 pauses × 2s)

### Test Overlay Rendering

Tests the overlay rendering with various FPS scenarios:

```bash
cd /home/rs-pi-2/Development/RPi_Logger/Modules/Cameras/camera_core
uv run python camera_overlay.py
```

**What it tests:**
- Overlay rendering with 60, 30, and 10 FPS scenarios
- FPS display format: `FPS_<collation>: <collation> / <hardware>`
- Frame counter format: `Frames: <collated> / <captured>`
- Recording indicator overlay
- Configuration loading (with fallback to defaults)

**Expected output:**
- 4 test images saved to `test_outputs/` directory:
  - `overlay_test_1_60fps.jpg` - `FPS_60: 60 / 30` (duplicates needed)
  - `overlay_test_2_30fps.jpg` - `FPS_30: 30 / 30` (1:1 matching)
  - `overlay_test_3_10fps.jpg` - `FPS_10: 10 / 30` (frame skipping)
  - `overlay_test_4_recording.jpg` - Recording indicator

**Exit codes:**
- `0` = All tests passed
- `1` = Test failed

**Test duration:** < 1 second

### Test Complete System

Run the full camera system:

```bash
cd /home/rs-pi-2/Development/RPi_Logger/Modules/Cameras
uv run python main_camera.py --mode interactive
```

**Controls:**
- `r` - Toggle recording
- `s` - Take snapshot
- `q` - Quit

## Integration Testing

All components are tested together in the main camera system. The modular design allows each component to be tested independently for easier debugging.

## Performance Targets

- **Camera Hardware**: 30 FPS (configured in camera_handler.py)
- **Capture Loop**: 30 FPS (matches camera)
- **Collation Loop**: Configurable (default 10 FPS for display/recording)
- **Display Update**: ~30 Hz (preview windows)
- **Recording**: Matches collation FPS with precise timing

## File Structure

```
camera_core/
├── camera_capture_loop.py      # Async capture at camera FPS
├── camera_collator_loop.py     # Timing-based collation
├── camera_processor.py         # Processing orchestrator
├── camera_overlay.py           # Overlay rendering
├── camera_display.py           # Thread-safe display storage
├── camera_recorder.py          # Video recording with ffmpeg
├── camera_handler.py           # Single camera coordinator
├── camera_system.py            # Multi-camera system
├── camera_supervisor.py        # Retry wrapper
├── camera_utils.py             # Utilities (FPS tracking, etc.)
├── __init__.py                 # Package exports
├── README.md                   # This file
└── test_outputs/               # Test output images
```

## Debugging

Each module has its own logger:
- `CameraCapture{N}` - Capture loop
- `CameraCollator{N}` - Collation loop
- `CameraProcessor{N}` - Processing loop
- `CameraOverlay{N}` - Overlay rendering
- `CameraDisplay{N}` - Display management
- `CameraRecorder` - Video recording
- `Camera{N}` - Camera handler
- `CameraSystem` - System coordinator
- `CameraSupervisor` - Supervisor wrapper

Set `logging.basicConfig(level=logging.DEBUG)` for detailed output.

## Recent Updates

### Hardware FPS Decoupling (2025-10-10)
- Camera hardware now captures at 30 FPS (native rate)
- Collation runs at configurable FPS (e.g., 10 FPS for display/recording)
- Hardware FPS extracted from camera metadata and displayed in overlay
- FPS overlay shows: `FPS_10: 10 / 30` (collation / hardware)
- Frame counters show: `Frames: 100 / 300` (collated / captured)

### Snapshot Location (2025-10-10)
- Snapshots now save to session directory alongside videos
- Example: `recordings/cameras/session_20251010_140928/snapshot_cam0_20251010_140930.jpg`

### Debug Logging Cleanup (2025-10-10)
- Removed temporary debug logging after FPS fix verification
- Cleaner log output during normal operation
