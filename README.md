# Logger

**Synchronized Multi-Sensor Data Collection for Research**

A cross-platform data acquisition system for automotive and human factors research. Capture synchronized video, audio, eye tracking, and behavioral task data. Runs on Windows, macOS, Linux, and Raspberry Pi.

---

## Modules

| Module | Capability |
|--------|-----------|
| **Cameras** | System camera video recording (webcams, etc.) |
| **Cameras-CSI** | CSI camera video (Raspberry Pi only) |
| **Audio** | Multi-channel microphone recording |
| **EyeTracker-Neon** | Pupil Labs Neon gaze tracking with scene video |
| **DRT** | Detection Response Task devices (wired & wireless) |
| **VOG** | Visual Occlusion Glasses with experiment modes |
| **GPS** | Real-time location tracking (Raspberry Pi only) |
| **Notes** | Timestamped session annotations |

All modules record with **frame-level synchronization** (~30ms accuracy) and export timestamped CSV data for analysis.

---

## Supported Hardware

| Device | Connection |
|--------|------------|
| IMX296 Global Shutter Cameras | CSI |
| System Cameras (webcams, etc.) | USB/System |
| USB Microphones | USB |
| Pupil Labs Neon | Network |
| Red Scientific DRT | USB Serial |
| Red Scientific VOG | USB Serial |
| OzzMaker BerryGPS | UART |

---

## Getting Started

### Install

```bash
git clone https://github.com/JoelCooperPhD/Logger.git
cd Logger
uv sync
```

#### Raspberry Pi (CSI Camera Support)

On Raspberry Pi, install `picamera2` for CSI camera support:

```bash
uv add picamera2
```

### Run

```bash
uv run rpi-logger
```

### Workflow

1. **Select modules** — Check the boxes for devices you want to use
2. **Start Session** — Initialize all selected modules
3. **Record** — Begin a trial
4. **Stop** — End the trial (data saves automatically)
5. **End Session** — Finalize and close

Record multiple trials per session. Each trial is saved with synchronized timestamps across all modules.

---

## Data Output

Recordings use a shared filename prefix:
Most modules use `{sessionToken}_{MODULECODE}_trial###_...`
(sessionToken is the timestamp portion of the session directory name).

DRT, VOG, and GPS append to a single file per session:
`{sessionToken}_DRT_{device_id}.csv`
`{sessionToken}_VOG_{port}.csv`
`{sessionToken}_GPS_{device_id}.csv`

```
session_20251208_143022/
├── Cameras/
│   └── usb_1_2_3/
│       ├── 143022_CAM_trial001_logitech-c920.mp4
│       └── 143022_CAM_trial001_logitech-c920_timing.csv
├── Audio/
│   ├── 143022_AUD_trial001_MIC0_blue-yeti.wav
│   └── 143022_AUD_trial001_MIC0_blue-yeti_timing.csv
├── EyeTracker-Neon/
│   ├── 143022_EYE_trial001_WORLD_1280x720_30fps.mp4
│   ├── 143022_EYE_trial001_EYES_384x192_200fps.mp4
│   ├── 143022_EYE_trial001_AUDIO.wav
│   ├── 143022_EYE_trial001_GAZE.csv
│   ├── 143022_EYE_trial001_IMU.csv
│   ├── 143022_EYE_trial001_EVENTS.csv
│   ├── 143022_EYE_trial001_FRAME_timing.csv
│   └── 143022_EYE_trial001_AUDIO_timing.csv
├── DRT/
│   └── 143022_DRT_ttyacm0.csv
├── VOG/
│   └── 143022_VOG_ttyacm0.csv
├── GPS/
│   └── 143022_GPS_serial0.csv
└── Notes/
    └── 143022_NTS_trial001_notes.csv
```

### Post-Processing

Combine audio and video with calculated sync offsets:

```bash
python -m rpi_logger.tools.muxing_tool
```

---

## System Requirements

| Requirement | Specification |
|-------------|---------------|
| Platform | Windows, macOS, Linux, Raspberry Pi |
| Python | 3.11+ |
| RAM | 4GB minimum, 8GB recommended |
| Storage | SSD recommended for video recording |

### Platform Notes

- **Raspberry Pi**: Full feature support including CSI cameras (requires `picamera2`)
- **Linux**: System cameras, audio, eye tracking, serial devices
- **macOS**: System cameras, audio, eye tracking
- **Windows**: System cameras, audio, eye tracking

---

## Debugging and Logging

### Log Level Control

Use **View > Log Level** in the main window to control log verbosity:

| Level | What's shown |
|-------|-------------|
| Debug | All messages including internal diagnostics |
| Info | Normal operation messages (default) |
| Warning | Warnings and errors only |
| Error | Errors only |
| Critical | Only critical failures |

Log files are always captured at DEBUG level in the `logs/` directory.

### Debug API (Development)

When running with the API server, debug endpoints are available:

| Endpoint | Description |
|----------|-------------|
| `GET /api/v1/debug/mode` | Check debug mode status |
| `POST /api/v1/debug/mode` | Toggle debug mode |
| `GET /api/v1/debug/modules` | Module state dump |
| `GET /api/v1/debug/devices` | Device/connection state |
| `GET /api/v1/debug/events` | Recent event log |
| `GET /api/v1/debug/config` | Full config dump |
| `GET /api/v1/debug/memory` | Memory usage by component |
| `GET /api/v1/debug/routes` | List all API routes |

### Troubleshooting

**Check logs directory** for detailed diagnostics:
```
~/.local/share/rpi_logger/logs/
```

**System Information** available via Help > System Information shows:
- Application version and platform
- Module status (running/stopped)
- Storage space and session directory

---

## Support

**Red Scientific**
[redscientific.com](https://redscientific.com)

---

*Professional multi-modal data collection for researchers who need reliable, synchronized sensor data.*
