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

Uses an Elm/Redux-style architecture with unidirectional data flow:

```
User Input → Action → Store.dispatch() → update() → new State + Effects
                                              ↓
                                    EffectExecutor (side effects)
                                              ↓
                                    View.render(state)
```

### Module Structure

```
Cameras_USB/
├── main_cameras_usb.py   # Entry point
├── bridge.py             # USBCamerasRuntime (ModuleRuntime interface)
├── config.txt            # Module configuration
├── core/                 # Pure state machine
│   ├── state.py          # AppState, CameraPhase, AudioPhase, CameraSettings
│   ├── actions.py        # Action types (AssignDevice, SetAudioMode, StartRecording, etc.)
│   ├── effects.py        # Effect types (LookupKnownCamera, ProbeVideo, OpenCamera, etc.)
│   ├── update.py         # Pure reducer function
│   └── store.py          # Store class with subscribe/dispatch
├── discovery/            # Cross-platform device discovery
│   ├── platform_scanner.py  # Platform abstraction (get_scanner())
│   ├── linux_scanner.py     # Linux: sysfs + ALSA
│   ├── macos_scanner.py     # macOS: AVFoundation + sounddevice
│   ├── windows_scanner.py   # Windows: DirectShow + sounddevice
│   ├── usb_scanner.py       # Linux-specific USB enumeration
│   ├── audio_matcher.py     # Linux-specific ALSA matching
│   ├── fingerprint.py       # VID:PID + capability hash
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
├── infra/                # Side effect handlers
│   ├── effect_executor.py    # Executes effects (probe, capture, record, preview)
│   └── command_handler.py    # JSON stdin/stdout command interface
├── ui/                   # User interface
│   ├── view.py           # USBCameraView (stub integration)
│   └── widgets/
│       └── settings_window.py  # Camera/audio settings dialog
└── tests/                # Test suite
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

### Known Camera Cache (Linux)

On Linux, the module uses a two-path discovery system:

1. **Fast Path**: Check `known_cameras.json` for cached fingerprint, quick verify
2. **Slow Path**: Full probe, compute fingerprint, cache for next time

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

## State Machine

### Camera Phases

- `IDLE` - No camera assigned
- `DISCOVERING` - Looking up known cameras cache
- `PROBING` - Full capability probe (unknown camera)
- `VERIFYING` - Fingerprint verification (known camera)
- `READY` - Camera assigned, capabilities available
- `STREAMING` - Camera active, frames flowing
- `ERROR` - Camera error occurred

### Audio Phases

- `DISABLED` - Audio recording disabled by user
- `UNAVAILABLE` - No audio device detected for this camera
- `AVAILABLE` - Audio device detected, not yet opened
- `CAPTURING` - Audio stream active
- `ERROR` - Audio device error

### Recording Phases

- `STOPPED` - Not recording
- `STARTING` - Encoder/muxer initializing
- `RECORDING` - Actively recording
- `STOPPING` - Finalizing and flushing streams

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
- `tests/unit/` - Pure function tests (update, fingerprint, timing_writer)
- `tests/integration/` - Store, device discovery, and multi-component tests
