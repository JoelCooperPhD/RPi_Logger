# Cameras_USB Module

USB camera module with optional audio recording. Supports video-only or synchronized audio+video capture depending on camera capabilities and user preference.

## Supported Platforms

- **Linux** (including Raspberry Pi): sysfs-based device discovery, ALSA audio
- **macOS**: AVFoundation device enumeration, CoreAudio
- **Windows**: DirectShow device enumeration, WASAPI

**Hardware:**
- USB cameras: UVC-compliant webcams with or without built-in microphones
- Audio: Platform audio devices (built-in camera mics or external)

## Architecture

Uses a direct async controller pattern with simple state management:

```
Command → CameraController.method() → state update + async operations
                                          ↓
                                   View.render(state)
```

The controller combines state management and side effects into a single class with direct async methods, avoiding the overhead of action dispatch and effect execution layers.

### Module Structure

```
Cameras_USB/
├── main_cameras_usb.py   # Entry point
├── bridge.py             # USBCamerasRuntime (ModuleRuntime interface)
├── config.txt            # Module configuration
├── core/                 # State and controller
│   ├── state.py          # CameraState (boolean flags), CameraSettings, device types
│   └── controller.py     # CameraController (state + operations)
├── discovery/            # Cross-platform device discovery
│   ├── platform_scanner.py  # Platform abstraction (get_scanner())
│   ├── linux_scanner.py     # Linux: sysfs + ALSA
│   ├── macos_scanner.py     # macOS: AVFoundation + sounddevice
│   ├── windows_scanner.py   # Windows: DirectShow + sounddevice
│   ├── usb_scanner.py       # Linux-specific USB enumeration
│   ├── audio_matcher.py     # Linux-specific ALSA matching
│   ├── camera_knowledge.py  # VID:PID capability cache
│   └── prober.py            # OpenCV-based capability probing
├── capture/              # Camera and audio capture
│   ├── usb_source.py     # USBSource wrapping OpenCV VideoCapture
│   ├── audio_source.py   # AudioSource using sounddevice
│   ├── frame.py          # CapturedFrame and AudioChunk dataclasses
│   └── frame_buffer.py   # Async frame/audio buffers with backpressure
├── recording/            # Video/audio recording
│   ├── encoder.py        # VideoEncoder (OpenCV MJPG → AVI)
│   ├── muxer.py          # AVMuxer for audio+video (ffmpeg → MP4)
│   ├── timing_writer.py  # TimingCSVWriter for frame timestamps
│   └── session.py        # RecordingSession coordinator
├── infra/                # Command handling
│   └── command_handler.py    # JSON stdin/stdout command interface
├── ui/                   # User interface
│   ├── view.py           # USBCameraView (stub integration)
│   └── widgets/
│       └── settings_window.py  # Camera/audio settings dialog
└── tests/                # Test suite
```

### CameraController API

```python
class CameraController:
    # State access
    @property
    def state(self) -> CameraState
    def subscribe(callback) -> unsubscribe_fn

    # Camera lifecycle
    async def assign(device_info: USBDeviceInfo)
    async def unassign()

    # Streaming
    async def start_streaming()
    async def stop_streaming()

    # Recording
    async def start_recording(session_dir, trial)
    async def stop_recording()

    # Settings
    async def set_audio_mode(mode: str)
    async def apply_settings(settings: CameraSettings)

    # Cleanup
    async def shutdown()
```

## Device Discovery

### Cross-Platform Scanner

```python
from discovery import get_scanner

scanner = get_scanner()  # Auto-selects platform implementation
videos = await scanner.scan_video_devices()    # → [VideoDevice]
audios = await scanner.scan_audio_devices()    # → [AudioDevice]
audio = await scanner.match_audio_to_video(video)  # → AudioDevice | None
```

### Platform-Specific Behavior

| Platform | Video Discovery | Audio Matching | Device ID |
|----------|-----------------|----------------|-----------|
| Linux | sysfs `/sys/class/video4linux` | USB bus path matching | `usb:1-2.3` (stable) |
| macOS | OpenCV + AVFoundation | Name substring matching | Device index `0, 1, 2` |
| Windows | OpenCV + DirectShow | Name substring matching | Device index `0, 1, 2` |

### Camera Knowledge Cache (Linux)

On Linux, the module uses a two-path discovery system via `CameraKnowledge`:

1. **Fast Path**: Check cache for VID:PID → quick verify camera accessible (1-2 seconds)
2. **Slow Path**: Full OpenCV probe, filter modes, cache for next time (30-60 seconds)

The cache stores per-camera profiles including supported modes, resolution limits, and defaults.

### Device Identifiers

- **Linux**: USB bus path (e.g., `usb:1-2.3`) - stable across reboots
- **macOS/Windows**: Device index (e.g., `0`, `1`) - may change on reconnect

## Capture Pipeline

### Video Capture

```
USBSource (OpenCV) → FrameBuffer → Encoder
                              ↘ Preview (PPM → Tkinter)
```

### Audio Capture (when enabled)

```
AudioSource (sounddevice) → AudioBuffer → Muxer
```

### Synchronized Recording

```
Video frames ─┐
              ├→ AVMuxer (ffmpeg) → .mp4 file
Audio chunks ─┘
              └→ TimingCSVWriter → _timing.csv
```

## Recording

### Output Formats

| Audio Enabled | Container | Video Codec | Audio Codec |
|---------------|-----------|-------------|-------------|
| No            | .avi      | MJPEG       | -           |
| Yes           | .mp4      | H.264       | AAC         |

### Output Files

Per-trial output in `<session_dir>/<stable_id>/`:
- `trial_001.mp4` or `trial_001.avi` - Video file
- `trial_001_timing.csv` - Frame and audio timing data

### Timing CSV Format

```csv
trial,module,device_id,label,record_time_unix,record_time_mono,frame_index,capture_timestamp_ns,video_pts,audio_pts
```

## Configuration

Settings in `config.txt`:

| Setting | Default | Description |
|---------|---------|-------------|
| `enabled` | false | Module enabled state |
| `audio_enabled` | auto | Audio recording: auto, on, off |
| `audio_device` | auto | Audio device selection |
| `container_format` | mp4 | Output container format |
| `frame_rate` | 30 | Recording frame rate |
| `preview_scale` | 0.25 | Preview scaling (1/4) |
| `preview_divisor` | 4 | Preview frame skip |
| `sample_rate` | 48000 | Audio sample rate |
| `window_geometry` | 320x200 | Initial window size |

Runtime settings via Settings dialog:

| Setting | Default | Options |
|---------|---------|---------|
| Resolution | auto | From camera capabilities |
| Record FPS | 30 | 1, 2, 5, 10, 15, 30 |
| Preview Scale | 1/4 | 1/2, 1/4, 1/8 |
| Audio Mode | auto | auto, on, off |
| Sample Rate | 48000 | 22050, 44100, 48000 |

### Audio Mode Behavior

| Mode | Behavior |
|------|----------|
| `auto` | Enable audio if camera has microphone, otherwise video-only |
| `on` | Require audio; fail if no audio device available |
| `off` | Video-only recording, ignore audio devices |

## Usage

### Standalone (video only)

```bash
# Linux - device path or index
python -m rpi_logger.modules.Cameras_USB.main_cameras_usb --device /dev/video0
python -m rpi_logger.modules.Cameras_USB.main_cameras_usb --device 0

# macOS/Windows - device index
python -m rpi_logger.modules.Cameras_USB.main_cameras_usb --device 0
```

### With Audio

```bash
python -m rpi_logger.modules.Cameras_USB.main_cameras_usb \
    --device 0 \
    --audio auto \
    --record \
    --output-dir /path/to/recordings
```

### CLI Arguments

| Argument | Description |
|----------|-------------|
| `--device` | Camera device: index (0, 1, 2) or Linux path (/dev/video0) |
| `--audio` | Audio mode: auto, on, off (default: auto) |
| `--audio-device` | Specific audio device (default: auto-detect) |
| `--record` | Start recording immediately after camera assignment |
| `--output-dir` | Recording output directory |
| `--container` | Output format: mp4, mkv, avi |
| `--console-output` | Enable console logging |
| `--log-level` | Logging level (debug, info, warning, error) |

## Commands

JSON commands via stdin when running as subprocess:

| Command | Description |
|---------|-------------|
| `assign_device` | Assign camera by `device_path` or `stable_id` |
| `unassign_device` | Release camera |
| `set_audio` | Configure audio mode |
| `start_streaming` | Start camera preview |
| `stop_streaming` | Stop camera preview |
| `start_recording` | Start recording with `session_dir` and `trial_number` |
| `stop_recording` | Stop current recording |
| `apply_settings` | Apply new camera/audio settings |
| `get_state` | Query current state |
| `get_capabilities` | Query camera capabilities |
| `shutdown` | Clean shutdown |

## State Model

The `CameraState` dataclass uses boolean flags instead of enums for simplicity:

```python
@dataclass
class CameraState:
    # Camera state
    assigned: bool        # Camera device assigned
    probing: bool         # Discovering capabilities
    ready: bool           # Ready to stream
    streaming: bool       # Actively capturing
    camera_error: str?    # Error message if failed

    # Audio state
    audio_enabled: bool   # User preference (not "off")
    audio_available: bool # Matching audio device found
    audio_capturing: bool # Audio stream active
    audio_error: str?     # Audio error if any

    # Recording
    recording: bool       # Currently recording

    # Data
    device_info: USBDeviceInfo?
    capabilities: CameraCapabilities?
    audio_device: USBAudioDevice?
    settings: CameraSettings
    metrics: FrameMetrics
```

### State Transitions

```
assign() → assigned=True, probing=True
       → [probe camera]
       → probing=False, ready=True, capabilities=...
       → [probe audio in background]
       → audio_available=True/False

start_streaming() → streaming=True
                 → [start capture loop]
                 → [start audio if available]

start_recording() → recording=True
                 → [frames written to encoder]

stop_recording() → recording=False

stop_streaming() → streaming=False, audio_capturing=False

unassign() → reset to initial state (preserving settings)
```

## Dependencies

- `opencv-python` - Video capture and encoding
- `sounddevice` - Audio capture
- `ffmpeg` - Audio/video muxing (system binary, called via subprocess)
- `numpy` - Frame/audio buffer handling

## Testing

```bash
pytest rpi_logger/modules/Cameras_USB/tests/
```

Test categories:
- `tests/unit/` - Pure function tests (state, timing_writer)
- `tests/integration/` - Controller, device discovery, and multi-component tests
