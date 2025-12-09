# EyeTracker Module Refactor Plan

## Overview

This plan consolidates optimization opportunities identified through deep analysis of the EyeTracker frame processing pipeline, combined with proven patterns from the Cameras module architecture.

**Goal**: Reduce CPU/GPU cycles without affecting tracking performance or data quality.

**Target Platforms**:
- Primary: Raspberry Pi 5 (quad-core ARM Cortex-A76 @ 2.4GHz)
- Secondary: Desktop/development machines (x86_64, optional NVIDIA GPU)

---

## Current Architecture

```
Pupil Labs Device (RTSP over network)
    → StreamHandler (async receive, ~30fps)
    → FrameProcessor (color conversion, scaling)
    → GazeTracker (coordination loop)
    → RecordingManager (frame timing, queueing)
    → VideoEncoder (FFmpeg subprocess)
```

### Detailed Frame Flow

1. **Frame Acquisition** (`stream_handler.py:139-201`)
   - Uses `pupil_labs.realtime_api.receive_video_frames()` async generator
   - Calls `frame.bgr_buffer()` to extract pixel data
   - Creates `np.ascontiguousarray(pixel_data)` on every frame
   - Enqueues into bounded `asyncio.Queue(maxsize=6)`
   - Uses event-driven signaling (`_frame_ready_event`)

2. **Main Processing Loop** (`gaze_tracker.py:135-319`)
   - Waits for frame via event-driven `wait_for_frame()`
   - Calls `frame_processor.process_frame()` for color conversion
   - Creates **preview frame** via `scale_for_preview()` (scaled to 640x360)
   - Creates **display overlays** (gaze circle, text)
   - Creates **recording frame** with minimal overlay if recording
   - Drains gaze/IMU/event/audio queues

3. **Frame Processing** (`frame_processor.py:51-98`)
   - Extracts scene camera region if tiled (2/3 height crop)
   - Color conversion: grayscale→BGR, RGBA→BGR
   - Uses `cv2.cvtColor()` and `cv2.resize()`

4. **Recording Pipeline** (`manager.py:556-564, 885-905, 1055-1131`)
   - `write_frame()` just stores reference (no copy)
   - `_frame_timer_loop()` runs at config FPS (default 5fps)
   - Enqueues to `_frame_queue` with timing metadata
   - `_frame_writer_loop()` offloads encoding to thread pool

5. **Video Encoding** (`video_encoder.py:74-89`)
   - FFmpeg subprocess with stdin pipe
   - `_resize_and_encode()` runs in thread: resize + `.tobytes()`
   - Writes raw BGR24 frames to FFmpeg

### Architecture Comparison: Cameras vs EyeTracker

| Aspect | Cameras Module | EyeTracker Module |
|--------|---------------|-------------------|
| **Process Model** | Multiprocess (worker per camera) | Single process |
| **GIL Contention** | Avoided (separate processes) | Present (shared process) |
| **Frame Capture** | Dedicated capture thread | Async generator from Pupil API |
| **Preview Transfer** | Shared memory + JPEG fallback | In-process numpy arrays |
| **Encoding** | PyAV or OpenCV VideoWriter | FFmpeg subprocess |
| **Preview Scaling** | ISP hardware (Picam) or CPU | Always CPU |

---

## Phase 0: Profiling Infrastructure (Required First)

Before implementing any optimizations, establish baseline measurements and profiling tools.

### 0.1 Platform Detection Module
**New file**: `tracker_core/platform_caps.py`

Detect platform-specific capabilities to enable appropriate optimizations:

```python
"""Platform capability detection for optimization selection."""

import os
import subprocess
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional

@dataclass(frozen=True)
class PlatformCapabilities:
    """Detected platform capabilities."""
    is_raspberry_pi: bool
    pi_model: Optional[str]  # e.g., "Raspberry Pi 5 Model B"
    cpu_cores: int
    has_nvenc: bool  # NVIDIA hardware encoder (desktop only)

@lru_cache(maxsize=1)
def detect_platform() -> PlatformCapabilities:
    """Detect platform capabilities (cached)."""
    is_pi = False
    pi_model = None
    has_nvenc = False

    # Check for Raspberry Pi
    try:
        with open('/proc/device-tree/model', 'r') as f:
            model = f.read().strip('\x00').strip()
            if 'Raspberry Pi' in model:
                is_pi = True
                pi_model = model
    except (FileNotFoundError, PermissionError):
        pass

    # Check CPU cores
    try:
        cpu_cores = len(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        cpu_cores = os.cpu_count() or 1

    # Check for NVENC (desktop only - Pi 5 has no hardware encoder)
    if not is_pi:
        try:
            result = subprocess.run(
                ['ffmpeg', '-hide_banner', '-encoders'],
                capture_output=True, text=True, timeout=5
            )
            has_nvenc = 'h264_nvenc' in result.stdout
        except Exception:
            pass

    return PlatformCapabilities(
        is_raspberry_pi=is_pi,
        pi_model=pi_model,
        cpu_cores=cpu_cores,
        has_nvenc=has_nvenc,
    )
```

---

### 0.2 Frame Processing Profiler
**New file**: `tracker_core/profiling.py`

Lightweight profiler for measuring frame processing phases:

```python
"""Lightweight profiling for frame processing pipeline."""

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional

@dataclass
class PhaseMetrics:
    """Metrics for a single processing phase."""
    samples: deque = field(default_factory=lambda: deque(maxlen=1000))

    def record(self, duration_ms: float) -> None:
        self.samples.append(duration_ms)

    @property
    def mean_ms(self) -> float:
        return sum(self.samples) / len(self.samples) if self.samples else 0.0

    @property
    def max_ms(self) -> float:
        return max(self.samples) if self.samples else 0.0

    @property
    def p95_ms(self) -> float:
        if not self.samples:
            return 0.0
        sorted_samples = sorted(self.samples)
        idx = int(len(sorted_samples) * 0.95)
        return sorted_samples[min(idx, len(sorted_samples) - 1)]


class FrameProfiler:
    """
    Lightweight profiler for frame processing pipeline.

    Usage:
        profiler = FrameProfiler()

        with profiler.measure('acquire'):
            frame = await stream_handler.wait_for_frame()

        with profiler.measure('process'):
            processed = frame_processor.process_frame(frame)

        # Get report
        print(profiler.report())
    """

    def __init__(self, enabled: bool = True):
        self._enabled = enabled
        self._phases: Dict[str, PhaseMetrics] = {}
        self._frame_count = 0
        self._start_time = time.perf_counter()

    def measure(self, phase: str):
        """Context manager for measuring a phase."""
        return _PhaseMeasurer(self, phase) if self._enabled else _NullMeasurer()

    def record(self, phase: str, duration_ms: float) -> None:
        """Record a duration for a phase."""
        if not self._enabled:
            return
        if phase not in self._phases:
            self._phases[phase] = PhaseMetrics()
        self._phases[phase].record(duration_ms)

    def tick_frame(self) -> None:
        """Call once per frame to track frame count."""
        self._frame_count += 1

    def report(self) -> Dict:
        """Generate profiling report."""
        elapsed = time.perf_counter() - self._start_time
        return {
            'elapsed_seconds': elapsed,
            'frame_count': self._frame_count,
            'effective_fps': self._frame_count / elapsed if elapsed > 0 else 0,
            'phases': {
                name: {
                    'mean_ms': metrics.mean_ms,
                    'max_ms': metrics.max_ms,
                    'p95_ms': metrics.p95_ms,
                    'samples': len(metrics.samples),
                }
                for name, metrics in self._phases.items()
            }
        }

    def reset(self) -> None:
        """Reset all metrics."""
        self._phases.clear()
        self._frame_count = 0
        self._start_time = time.perf_counter()


class _PhaseMeasurer:
    """Context manager for phase measurement."""

    def __init__(self, profiler: FrameProfiler, phase: str):
        self._profiler = profiler
        self._phase = phase
        self._start: float = 0

    def __enter__(self):
        self._start = time.perf_counter()
        return self

    def __exit__(self, *args):
        duration_ms = (time.perf_counter() - self._start) * 1000
        self._profiler.record(self._phase, duration_ms)


class _NullMeasurer:
    """No-op context manager when profiling disabled."""

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass
```

---

### 0.3 Baseline Measurement Protocol

Before any optimization work, collect baseline metrics:

**Metrics to capture:**
```
┌─────────────────────────────────────────────────────────────┐
│ Metric                    │ Method              │ Target    │
├───────────────────────────┼─────────────────────┼───────────┤
│ CPU % (streaming only)    │ pidstat -p PID 1    │ < 50%     │
│ CPU % (streaming+record)  │ pidstat -p PID 1    │ < 70%     │
│ Frame acquire latency     │ FrameProfiler       │ < 10ms    │
│ Frame process latency     │ FrameProfiler       │ < 15ms    │
│ Overlay render latency    │ FrameProfiler       │ < 5ms     │
│ Encode latency            │ FrameProfiler       │ < 20ms    │
│ End-to-end latency        │ capture→display     │ < 50ms    │
│ Dropped frames            │ StreamHandler       │ < 1%      │
│ Memory usage              │ /proc/PID/status    │ < 500MB   │
└─────────────────────────────────────────────────────────────┘
```

**Test scenarios:**
1. Streaming only (no recording) - 5 minutes
2. Streaming + recording at 5fps - 10 minutes
3. Streaming + recording at 30fps - 10 minutes
4. Start/stop recording cycles (20x)
5. Network interruption recovery

---

## Phase 1: Quick Wins (Low Risk, Immediate Impact)

### 1.1 Switch to INTER_AREA for Downscaling
**File**: `tracker_core/frame_processor.py:241`

**Current**:
```python
scaled = cv2.resize(frame, preview_size, interpolation=cv2.INTER_LINEAR)
```

**Change**:
```python
scaled = cv2.resize(frame, preview_size, interpolation=cv2.INTER_AREA)
```

**Rationale**: INTER_AREA is faster and produces better quality for downscaling (uses pixel averaging). INTER_LINEAR is only better for upscaling. This matches the Cameras module pattern.

**Impact**: Faster resize + fewer aliasing artifacts
**Risk**: Low
**Verification**: Visual comparison, timing measurement

---

### 1.2 Batch Frame Timing CSV Flushes
**File**: `tracker_core/recording/manager.py:1171-1173`

**Current**:
```python
await asyncio.to_thread(self._frame_timing_file.write, row)
await asyncio.to_thread(self._frame_timing_file.flush)  # Every frame!
```

**Change**:
```python
await asyncio.to_thread(self._frame_timing_file.write, row)
self._timing_rows_since_flush += 1
if self._timing_rows_since_flush >= 30:  # Flush every 30 frames (~6 seconds at 5fps)
    await asyncio.to_thread(self._frame_timing_file.flush)
    self._timing_rows_since_flush = 0
```

**Also ensure final flush on stop** (already in `stop_recording`):
```python
# In stop_recording(), before closing:
if self._frame_timing_file:
    await asyncio.to_thread(self._frame_timing_file.flush)
```

**Impact**: Significant I/O reduction, especially on SD cards
**Risk**: Low (final flush ensures no data loss)
**Verification**: I/O monitoring with `iotop`, verify CSV completeness

---

### 1.3 Add Latency and Drop Metrics
**Files**: `tracker_core/stream_handler.py`, `tracker_core/gaze_tracker.py`

Add tracking similar to Cameras module's `wait_ms` and `dropped_frames`:

```python
@dataclass(slots=True)
class FramePacket:
    image: np.ndarray
    received_monotonic: float
    timestamp_unix_seconds: Optional[float]
    camera_frame_index: int
    wait_ms: float = 0.0  # NEW: Time spent waiting for frame

class StreamHandler:
    def __init__(self):
        # ... existing ...
        self._dropped_frames = 0
        self._total_wait_ms = 0.0

    @property
    def dropped_frames(self) -> int:
        return self._dropped_frames

    @property
    def avg_wait_ms(self) -> float:
        if self.camera_frames == 0:
            return 0.0
        return self._total_wait_ms / self.camera_frames

    async def wait_for_frame(self, timeout: Optional[float] = None) -> Optional[FramePacket]:
        """Wait for frame, tracking wait time."""
        wait_start = time.perf_counter()
        try:
            await asyncio.wait_for(self._frame_ready_event.wait(), timeout=timeout)
            self._frame_ready_event.clear()
            packet = self._last_frame_packet
            if packet is not None:
                wait_ms = (time.perf_counter() - wait_start) * 1000
                self._total_wait_ms += wait_ms
                # Return packet with wait_ms populated
                return FramePacket(
                    image=packet.image,
                    received_monotonic=packet.received_monotonic,
                    timestamp_unix_seconds=packet.timestamp_unix_seconds,
                    camera_frame_index=packet.camera_frame_index,
                    wait_ms=wait_ms,
                )
            return None
        except asyncio.TimeoutError:
            return None
```

**Impact**: Essential debugging/monitoring capability
**Risk**: Low (non-invasive additions)
**Verification**: Log output, compare with Cameras module metrics

---

### 1.4 Periodic fsync for Data Integrity
**File**: `tracker_core/recording/video_encoder.py`

Add periodic fsync to protect against data loss (matching Cameras pattern):

```python
import os

class VideoEncoder:
    def __init__(self, ...):
        # ... existing ...
        self._flush_interval = 600  # frames (2 minutes at 5fps)
        self._frames_since_flush = 0
        self._output_path: Optional[Path] = None

    async def start(self, output_path: Path) -> None:
        self._output_path = output_path
        # ... existing start logic ...

    async def write_frame(self, frame: np.ndarray) -> None:
        # ... existing write logic ...

        self._frames_since_flush += 1
        if self._frames_since_flush >= self._flush_interval:
            self._frames_since_flush = 0
            await self._fsync()

    async def _fsync(self) -> None:
        """Sync file to disk for crash safety."""
        if self._output_path is None:
            return
        try:
            # For FFmpeg subprocess, we can't directly fsync the pipe
            # but we can fsync the output file periodically
            fd = os.open(str(self._output_path), os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        except (OSError, FileNotFoundError):
            pass  # File may not exist yet or be locked
```

**Impact**: Data integrity on crash/power failure
**Risk**: Low (already proven in Cameras module)
**Verification**: Kill process mid-recording, verify file is recoverable

---

### 1.5 Conditional Array Copy
**File**: `tracker_core/stream_handler.py:159`

**Current**:
```python
frame_array = np.ascontiguousarray(pixel_data)
```

**Change**:
```python
if pixel_data.flags['C_CONTIGUOUS']:
    frame_array = pixel_data
else:
    frame_array = np.ascontiguousarray(pixel_data)
```

**Important**: First verify what `frame.bgr_buffer()` actually returns:
```python
# Add temporary logging to determine if this optimization is worthwhile
if self.camera_frames <= 10:
    logger.info(f"Frame {self.camera_frames}: C_CONTIGUOUS={pixel_data.flags['C_CONTIGUOUS']}")
```

**Impact**: ~0.5-1ms saved per frame IF buffer is sometimes contiguous
**Risk**: Low
**Verification**: Log flag values to confirm optimization applies

---

### 1.6 Skip Processing When Paused/Hidden
**File**: `tracker_core/gaze_tracker.py:145-152`

The pause mechanism exists but could be extended with visibility awareness:

**Change** (in `_process_frames`):
```python
# Early in loop, check if we should skip heavy processing
if self._paused:
    await asyncio.sleep(0.1)
    next_frame_deadline = time.perf_counter() + frame_interval
    continue

# NEW: Reduced processing mode when not visible and not recording
if self._reduced_processing and not self.recording_manager.is_recording:
    # Only update frame occasionally for UI thumbnail
    if self.frame_count % 10 == 0:
        # Process frame but skip display
        pass
    else:
        await asyncio.sleep(frame_interval)
        continue
```

**Also add property for UI to control**:
```python
def set_reduced_processing(self, enabled: bool) -> None:
    """Enable reduced processing when window not visible."""
    self._reduced_processing = enabled
    if enabled:
        logger.info("Eye tracker entering reduced processing mode")
    else:
        logger.info("Eye tracker resuming full processing")
```

**Integration**: The main UI should call `set_reduced_processing(True)` when EyeTracker tab is not active.

**Impact**: ~50-80% CPU reduction when not actively viewed
**Risk**: Low (always full processing when recording)
**Verification**: CPU monitoring when switching tabs

---

## Phase 2: Medium Effort Improvements

### 2.1 Lazy Color Conversion
**File**: `tracker_core/frame_processor.py`

Only convert grayscale to BGR when needed for colored overlays:

```python
from typing import Tuple

def process_frame(self, raw_frame: np.ndarray) -> Tuple[np.ndarray, bool]:
    """
    Process raw frame from camera.

    Returns:
        Tuple of (processed_frame, is_grayscale)
        Keeps grayscale frames as-is when possible for efficiency.
    """
    try:
        h, w = raw_frame.shape[:2]

        # ... existing tiled extraction logic ...

        if len(scene_frame.shape) == 2:  # Grayscale
            # Return grayscale directly, let caller convert if needed
            if not self._logged_color_info:
                logger.info("Scene camera is grayscale - deferring BGR conversion")
                self._logged_color_info = True
            return scene_frame, True

        elif len(scene_frame.shape) == 3:
            if scene_frame.shape[2] == 1:
                return scene_frame.squeeze(), True  # Still grayscale
            elif scene_frame.shape[2] == 3:
                return scene_frame, False  # Already BGR
            elif scene_frame.shape[2] == 4:
                return cv2.cvtColor(scene_frame, cv2.COLOR_RGBA2BGR), False

        return scene_frame, False

    except Exception as e:
        logger.error(f"Error processing frame: {e}")
        return raw_frame, len(raw_frame.shape) == 2

def ensure_bgr(self, frame: np.ndarray, is_grayscale: bool) -> np.ndarray:
    """Convert to BGR only when needed (for overlay drawing)."""
    if is_grayscale:
        return cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
    return frame
```

**Update callers** in `gaze_tracker.py`:
```python
processed_frame, is_grayscale = self.frame_processor.process_frame(raw_frame)

# Only convert to BGR when we need to draw colored overlays
if need_overlays:
    display_frame = self.frame_processor.ensure_bgr(processed_frame, is_grayscale)
    display_frame = self.frame_processor.add_display_overlays(display_frame, ...)
else:
    display_frame = processed_frame
```

**Impact**: ~1-2ms saved per frame for grayscale sources
**Risk**: Medium (must ensure overlays still render correctly)
**Verification**: Visual inspection of overlays with grayscale source

---

### 2.2 Cache Gaze Indicator Sprites
**File**: `tracker_core/frame_processor.py`

Cache pre-rendered gaze indicators instead of drawing every frame:

```python
from functools import lru_cache

class FrameProcessor:
    def __init__(self, config: Config):
        # ... existing ...
        self._gaze_sprite_cache: Dict[Tuple, np.ndarray] = {}

    def _get_gaze_sprite(self, radius: int, thickness: int, color: Tuple[int, int, int],
                         shape: str, center_radius: int) -> np.ndarray:
        """Get cached gaze indicator sprite."""
        cache_key = (radius, thickness, color, shape, center_radius)
        if cache_key not in self._gaze_sprite_cache:
            # Create sprite with alpha channel for blending
            size = radius * 2 + thickness * 2 + 4
            sprite = np.zeros((size, size, 4), dtype=np.uint8)
            center = size // 2

            if shape == "cross":
                # Draw cross on sprite
                cv2.line(sprite, (center - radius, center), (center + radius, center),
                        (*color, 255), thickness)
                cv2.line(sprite, (center, center - radius), (center, center + radius),
                        (*color, 255), thickness)
            else:
                # Draw circle on sprite
                cv2.circle(sprite, (center, center), radius, (*color, 255), thickness)

            # Draw center dot
            cv2.circle(sprite, (center, center), center_radius, (*color, 255), -1)

            self._gaze_sprite_cache[cache_key] = sprite

            # Limit cache size
            if len(self._gaze_sprite_cache) > 20:
                # Remove oldest entry
                oldest_key = next(iter(self._gaze_sprite_cache))
                del self._gaze_sprite_cache[oldest_key]

        return self._gaze_sprite_cache[cache_key]

    def _draw_gaze_indicator_fast(self, frame: np.ndarray, gaze_x: int, gaze_y: int,
                                   is_worn: bool) -> None:
        """Draw gaze indicator using cached sprite (faster than cv2.circle every frame)."""
        color = self._get_gaze_color(is_worn)
        sprite = self._get_gaze_sprite(
            self.config.gaze_circle_radius,
            self.config.gaze_circle_thickness,
            color,
            self.config.gaze_shape,
            self.config.gaze_center_radius,
        )

        # Calculate blit region
        sprite_h, sprite_w = sprite.shape[:2]
        half_h, half_w = sprite_h // 2, sprite_w // 2

        # Frame bounds
        frame_h, frame_w = frame.shape[:2]

        # Source and destination regions (handle edge clipping)
        src_y1 = max(0, half_h - gaze_y)
        src_y2 = min(sprite_h, half_h + (frame_h - gaze_y))
        src_x1 = max(0, half_w - gaze_x)
        src_x2 = min(sprite_w, half_w + (frame_w - gaze_x))

        dst_y1 = max(0, gaze_y - half_h)
        dst_y2 = min(frame_h, gaze_y + half_h)
        dst_x1 = max(0, gaze_x - half_w)
        dst_x2 = min(frame_w, gaze_x + half_w)

        if dst_y2 > dst_y1 and dst_x2 > dst_x1:
            # Blend sprite onto frame using alpha
            sprite_region = sprite[src_y1:src_y2, src_x1:src_x2]
            alpha = sprite_region[:, :, 3:4] / 255.0
            frame_region = frame[dst_y1:dst_y2, dst_x1:dst_x2]
            blended = (sprite_region[:, :, :3] * alpha + frame_region * (1 - alpha)).astype(np.uint8)
            frame[dst_y1:dst_y2, dst_x1:dst_x2] = blended
```

**Impact**: ~0.2-0.5ms per frame (avoid cv2.circle/line per frame)
**Risk**: Low
**Verification**: Visual comparison, timing measurement

---

### 2.3 Skip Processing for Unchanged/Duplicate Frames
**File**: `tracker_core/frame_processor.py`

Detect duplicate frames from static scenes and skip processing:

```python
class FrameProcessor:
    def __init__(self, config: Config):
        # ... existing ...
        self._last_frame_hash: Optional[int] = None
        self._last_processed: Optional[np.ndarray] = None
        self._duplicate_count = 0

    def process_frame(self, raw_frame: np.ndarray) -> Tuple[np.ndarray, bool]:
        """
        Process frame, detecting duplicates for efficiency.

        Uses sparse pixel sampling for fast duplicate detection.
        """
        # Fast duplicate detection using sparse sampling
        # Sample every 64th pixel in a grid pattern
        sample = raw_frame[::64, ::64]
        frame_hash = hash(sample.tobytes())

        if frame_hash == self._last_frame_hash and self._last_processed is not None:
            self._duplicate_count += 1
            # Return cached result for duplicate frame
            return self._last_processed, self._last_was_grayscale

        # Process frame normally
        processed, is_grayscale = self._do_process(raw_frame)

        # Cache for next comparison
        self._last_frame_hash = frame_hash
        self._last_processed = processed
        self._last_was_grayscale = is_grayscale

        return processed, is_grayscale

    @property
    def duplicate_frames_skipped(self) -> int:
        return self._duplicate_count
```

**Considerations**:
- Only effective for static scenes (parked vehicle, stationary subject)
- Hash comparison is O(1) - negligible overhead
- Overlays still need updating even for duplicate frames (gaze moves independently)

**Impact**: Skip processing for ~10-90% of frames in static scenes
**Risk**: Medium (ensure gaze overlay still updates)
**Verification**: Test with static and dynamic scenes

---

### 2.4 Evaluate PyAV vs FFmpeg Encoding
**File**: `tracker_core/recording/video_encoder.py`

Before switching, benchmark both approaches on Pi 5:

```python
class VideoEncoder:
    """Video encoder with selectable backend."""

    BACKEND_FFMPEG = 'ffmpeg'
    BACKEND_PYAV = 'pyav'
    BACKEND_V4L2 = 'v4l2'  # Pi hardware encoder

    def __init__(self, resolution: Tuple[int, int], fps: float, *,
                 backend: str = BACKEND_FFMPEG):
        self.resolution = resolution
        self.fps = fps
        self._backend = backend
        self._encoder: Optional[_BaseEncoder] = None

    async def start(self, output_path: Path) -> None:
        if self._backend == self.BACKEND_PYAV:
            self._encoder = _PyAVEncoder(self.resolution, self.fps)
        elif self._backend == self.BACKEND_V4L2:
            self._encoder = _V4L2Encoder(self.resolution, self.fps)
        else:
            self._encoder = _FFmpegEncoder(self.resolution, self.fps)
        await self._encoder.start(output_path)

    async def write_frame(self, frame: np.ndarray) -> None:
        if self._encoder:
            await self._encoder.write_frame(frame)

    async def stop(self) -> None:
        if self._encoder:
            await self._encoder.stop()
            self._encoder = None
```

**Benchmark protocol** (run on Pi 5):
```bash
# Test each backend with 1000 frames at 1920x1080
python -m tracker_core.benchmark_encoders --frames 1000 --resolution 1920x1080
```

**Decision criteria**:
- Encoding latency p95 < 20ms
- CPU usage < 30% of one core
- Output file quality acceptable
- Reliability over 100+ recordings

**Impact**: TBD (requires benchmarking)
**Risk**: Medium (keep FFmpeg as fallback)
**Verification**: Benchmark on target hardware

---

## Phase 3: Configurable Frame Selection

### 3.1 Frame Selection Mode (Timer vs Camera-Based)
**File**: `tracker_core/recording/manager.py`

Add configurable frame selection to support different research use cases:

**Config addition** (`tracker_config.py`):
```python
@dataclass
class TrackerConfig:
    # ... existing ...
    frame_selection_mode: str = "timer"  # "timer" or "camera"
```

**Timer mode** (current behavior):
- Maintains consistent output video FPS
- Duplicates frames when camera is slower than recording FPS
- Best for: playback synchronization with audio

**Camera mode** (new option):
- Only writes unique camera frames
- Variable timing in output, but no duplicates
- Best for: frame-accurate analysis, reduced file size

```python
class RecordingManager:
    async def _frame_timer_loop(self) -> None:
        """Timer-based frame selection (original behavior)."""
        # ... existing implementation ...

    async def _frame_camera_loop(self) -> None:
        """Camera-based frame selection (new option)."""
        last_camera_index = -1

        while self._is_recording:
            if self._latest_frame is None:
                await asyncio.sleep(0.01)
                continue

            metadata = self._latest_frame_metadata
            if metadata is None:
                continue

            # Only process new camera frames
            if metadata.camera_frame_index == last_camera_index:
                await asyncio.sleep(0.001)
                continue

            last_camera_index = metadata.camera_frame_index

            # Apply frame rate limiting
            camera_fps = metadata.available_camera_fps or 30.0
            recording_fps = self.config.fps
            frame_ratio = max(1, int(camera_fps / recording_fps))

            if metadata.camera_frame_index % frame_ratio == 0:
                await self._enqueue_frame_for_writing(self._latest_frame, metadata)
                self._latest_frame = None

    async def _start_frame_selection(self) -> None:
        """Start appropriate frame selection loop."""
        if self.config.frame_selection_mode == "camera":
            self._frame_timer_task = asyncio.create_task(self._frame_camera_loop())
        else:
            self._frame_timer_task = asyncio.create_task(self._frame_timer_loop())
```

**Impact**: Flexibility for different research requirements
**Risk**: Medium (timer mode remains default, well-tested)
**Verification**: Test both modes, verify CSV timing accuracy

---

## Phase 4: Platform-Specific Acceleration (Optional)

> **Important Note on Pi 5 Hardware Encoding**
>
> The Raspberry Pi 5 does **NOT** have a hardware video encoder. This is a common misconception.
> The VideoCore VII on Pi 5 only provides hardware **decoding**. The `h264_v4l2m2m` codec
> on Pi 5 is actually software encoding via the V4L2 API, not hardware-accelerated.
>
> Previous Pi models (Pi 4 and earlier) had limited hardware encoding via the legacy GPU,
> but this was removed in Pi 5's architecture.
>
> For Pi 5, the best encoding approach remains FFmpeg with `libx264` using the `ultrafast`
> preset, which is already what we use. Focus optimization efforts elsewhere.

### 4.1 Desktop GPU Acceleration (NVENC) - Desktop Only

For desktop development machines with NVIDIA GPUs, NVENC can be used by simply changing the FFmpeg codec:

```python
# In VideoEncoder, detect and use NVENC if available
def _get_ffmpeg_codec(self) -> list:
    """Get FFmpeg codec arguments, using NVENC if available on desktop."""
    if self._has_nvenc:  # Detected at init time
        return ["-c:v", "h264_nvenc", "-preset", "p1", "-tune", "ll"]
    return ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "23"]
```

This is a simple change to the existing FFmpeg command - no new classes or abstractions needed.

**Impact**: Faster encoding on desktop dev machines
**Risk**: Low (simple codec swap with detection)
**When to implement**: Only if desktop encoding is a bottleneck during development

---

### 4.2 Subprocess Encoding Worker (Deferred)

> **Complexity Warning**: This adds significant complexity (shared memory, IPC, process lifecycle
> management, error handling across process boundaries) for uncertain gain. The current FFmpeg
> subprocess already runs encoding in a separate process. The GIL contention is primarily in
> the frame preparation (`resize`, `tobytes`), not the actual encoding.
>
> **Recommendation**: Only implement if profiling shows frame preparation is a significant
> bottleneck AND Phases 1-2 optimizations are insufficient. The Cameras module uses this
> pattern because it manages multiple cameras simultaneously; the EyeTracker has only one
> stream, making the complexity/benefit tradeoff less favorable.

If profiling confirms this is needed, the pattern from `Cameras/worker/shared_preview.py` can be adapted. See the Cameras module for a working implementation.

---

## Implementation Order

> **Guiding Principle**: Minimize code proliferation. Each optimization should provide
> measurable benefit relative to its complexity. Prefer modifying existing code over
> adding new abstractions. Profile before implementing.

### Sprint 0: Profiling Foundation (1 day)
- [ ] 0.1 Platform detection (simple, ~50 lines)
- [ ] 0.2 Frame processing profiler (~100 lines)
- [ ] 0.3 Baseline measurements on Pi 5

### Sprint 1: Quick Wins (1-2 days)
These are small, targeted changes to existing code:
- [ ] 1.1 INTER_AREA for downscaling (1 line change)
- [ ] 1.2 Batch CSV flushes (~10 lines)
- [ ] 1.3 Add latency/drop metrics (~20 lines)
- [ ] 1.4 Periodic fsync (~15 lines)
- [ ] 1.5 Conditional array copy (3 lines, verify first)
- [ ] 1.6 Reduced processing mode (~15 lines)

### Sprint 2: Processing Optimizations (2-3 days)
Implement based on profiling results - skip items that don't show measurable benefit:
- [ ] 2.1 Lazy color conversion (if grayscale source confirmed)
- [ ] 2.2 Cache gaze sprites (if overlay rendering is significant)
- [ ] 2.3 Skip duplicate frames (if static scenes are common)
- [ ] 2.4 Benchmark PyAV vs FFmpeg (decide based on data)

### Sprint 3: Configurability (Optional)
Only if research team needs different recording modes:
- [ ] 3.1 Frame selection mode (timer vs camera)

### Sprint 4: Platform Acceleration (Deferred)
Only if Sprints 0-2 don't meet targets:
- [ ] 4.1 Desktop NVENC (simple codec swap, if desktop encoding is slow)
- [ ] 4.2 Subprocess encoding worker (high complexity - last resort)

---

## Testing Strategy

### Performance Benchmarks (Before/After Each Sprint)

Use the profiling infrastructure from Phase 0:

```bash
# Run benchmark suite
python -m rpi_logger.modules.EyeTracker.benchmark \
    --duration 300 \
    --scenarios streaming,recording \
    --output benchmark_results.json
```

**Metrics to compare**:
| Metric | Baseline | Target | Method |
|--------|----------|--------|--------|
| CPU % (streaming) | TBD | < 50% | pidstat |
| CPU % (recording) | TBD | < 70% | pidstat |
| Acquire latency p95 | TBD | < 10ms | FrameProfiler |
| Process latency p95 | TBD | < 15ms | FrameProfiler |
| End-to-end latency | TBD | < 50ms | timestamp delta |
| Dropped frames | TBD | < 1% | StreamHandler |
| Memory peak | TBD | < 500MB | /proc/status |

### Regression Tests

- [ ] Verify gaze overlay accuracy unchanged (visual + coordinate test)
- [ ] Verify recording file integrity (ffprobe, playback test)
- [ ] Verify CSV timing data accuracy (parse and validate)
- [ ] Verify audio sync (if enabled) (muxing tool test)

### Stress Tests

- [ ] 30-minute continuous recording
- [ ] Multiple start/stop cycles (50x)
- [ ] Network interruption recovery (disconnect/reconnect Pupil Labs)
- [ ] Low memory conditions (limit with cgroups)
- [ ] High CPU load (stress -c 3 concurrent)

---

## Risk Assessment

| Change | Risk | Complexity | Mitigation |
|--------|------|------------|------------|
| Platform detection | Low | ~50 lines | Graceful fallback if detection fails |
| Profiling infrastructure | Low | ~100 lines | Can disable in production |
| INTER_AREA resize | Low | 1 line | Visual comparison test |
| Batch CSV flush | Low | ~10 lines | Ensure final flush on stop |
| Latency/drop metrics | Low | ~20 lines | Non-invasive additions |
| Periodic fsync | Low | ~15 lines | Already proven in Cameras |
| Conditional array copy | Low | 3 lines | Profile first to confirm benefit |
| Reduced processing mode | Low | ~15 lines | Always full processing when recording |
| Lazy color conversion | Medium | ~30 lines | Verify overlay colors correct |
| Cache gaze sprites | Low | ~50 lines | Visual comparison test |
| Skip duplicate frames | Medium | ~20 lines | Ensure gaze overlay still updates |
| PyAV encoding | Medium | ~50 lines | Keep FFmpeg as fallback, benchmark first |
| Frame selection mode | Medium | ~40 lines | Timer mode remains default |
| Desktop NVENC | Low | ~5 lines | Desktop only, simple codec swap |
| Subprocess encoder | High | ~150+ lines | Last resort - extensive testing needed |

---

## Success Metrics

- **CPU reduction**: Target 30-50% reduction during streaming
- **Latency**: Target <50ms capture-to-display
- **Zero regressions**: All existing functionality preserved
- **Data integrity**: No corrupt recordings after 100+ test runs
- **Platform coverage**: Works on Pi 5 and desktop

---

## Appendix: Removed/Deferred Items

The following items from the original plan were removed or substantially reworked:

### Removed: Drain Queues with List (Original 1.5)
**Reason**: Creating a list to drain queues adds allocation overhead. The current `while` loop with `get_nowait()` is more efficient as it avoids heap allocation.

### Removed: NumPy Gaze Coordinate Math (Original 1.6)
**Reason**: Vectorizing 2 scalar values with NumPy is slower than native Python due to NumPy's setup overhead (~10-50μs) for small arrays. The current `max(0, min(...))` approach is faster for 2 elements.

### Removed: Pi 5 Hardware Encoding (V4L2 M2M)
**Reason**: The Pi 5 does **not** have a hardware video encoder. This is a common misconception. The VideoCore VII on Pi 5 only provides hardware decoding. The `h264_v4l2m2m` codec is software encoding via V4L2 API, not hardware-accelerated. The current FFmpeg + libx264 ultrafast approach is already optimal for Pi 5.

### Reworked: Pre-render Overlay Sprites (Original 2.5)
**Original**: Cache overlays keyed by frame number (0% hit rate since frame numbers are unique).
**New (2.2)**: Cache gaze indicator sprites by visual parameters (color, size, shape). These are reused across frames.

### Reworked: Frame Selection (Original 3.1)
**Original**: Replace timer-based with camera-based selection.
**New (3.1)**: Make it configurable option. Timer-based is correct for audio sync; camera-based avoids duplicates for frame-accurate analysis.

### Reworked: GPU Acceleration (Original 3.3)
**Original**: CUDA suggestions for all platforms.
**New (4.1)**: Desktop-only NVENC as simple codec swap. No CUDA OpenCV complexity (requires special build). Pi 5 has no hardware encoder.

### Deferred: Subprocess Encoding Worker (Original 3.2)
**Reason**: High complexity for uncertain gain. The FFmpeg subprocess already runs in a separate process. GIL contention is primarily in frame preparation, which is already offloaded via `asyncio.to_thread()`. Only implement as last resort if profiling confirms it's needed.

---

## File Reference

| File | Key Lines | Purpose |
|------|-----------|---------|
| `tracker_core/stream_handler.py` | 159 | Array copy |
| `tracker_core/frame_processor.py` | 241 | Resize interpolation |
| `tracker_core/recording/manager.py` | 1171-1173 | CSV flush |
| `tracker_core/gaze_tracker.py` | 145-152 | Pause handling |
| `tracker_core/recording/video_encoder.py` | 61-65 | Encoding resize |
| `Cameras/worker/shared_preview.py` | - | Reference pattern |
| `tracker_core/config/tracker_config.py` | - | Configuration |
