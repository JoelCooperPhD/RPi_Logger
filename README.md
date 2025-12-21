# Logger

**Synchronized Multi-Sensor Data Collection for Research**

A professional data acquisition platform designed for automotive and human factors research on Raspberry Pi. Capture synchronized video, audio, eye tracking, and behavioral task data in a single unified system.

---

## Modules

| Module | Capability |
|--------|-----------|
| **Cameras** | Multi-camera video with hardware-accelerated H.264 encoding |
| **Audio** | Multi-channel USB microphone recording |
| **Eye Tracker** | Pupil Labs Neon integration with gaze overlay |
| **DRT** | Detection Response Task devices (wired & wireless) |
| **VOG** | Visual Occlusion Glasses with experiment modes |
| **GPS** | Real-time location with offline map support |
| **Notes** | Timestamped session annotations |

All modules record with **frame-level synchronization** (~30ms accuracy) and export timestamped CSV data for analysis.

---

## Supported Hardware

| Device | Connection |
|--------|------------|
| IMX296 Global Shutter Cameras | CSI |
| USB Webcams | USB |
| USB Microphones | USB |
| Pupil Labs Neon | Network |
| Red Scientific DRT | USB Serial |
| Red Scientific VOG | USB Serial |
| OzzMaker BerryGPS | UART |

---

## Getting Started

### Install

```bash
git clone https://github.com/JoelCooperPhD/RPi_Logger.git
cd RPi_Logger
uv sync
```

### Run

```bash
python -m rpi_logger
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

DRT and VOG append to a single file per session:
`{sessionToken}_DRT_{device_id}.csv`
`{sessionToken}_VOG_{port}.csv`

```
session_YYYYMMDD_HHMMSS/
├── Cameras/
│   └── FaceTime_HD_0D0B7853/
│       ├── 20251208_143022_CAM_trial001_FaceTime_HD_0D0B7853.avi
│       └── 20251208_143022_CAM_trial001_FaceTime_HD_0D0B7853_timing.csv
├── Audio/
│   ├── 20251208_143022_AUD_trial001_MIC0_blue-yeti.wav
│   └── 20251208_143022_AUD_trial001_MIC0_blue-yeti_timing.csv
├── EyeTracker-Neon/
│   ├── 20251208_143022_EYE_trial001_WORLD_1280x720_30fps.mp4
│   ├── 20251208_143022_EYE_trial001_EYES_384x192_200fps.mp4
│   ├── 20251208_143022_EYE_trial001_AUDIO.wav
│   ├── 20251208_143022_EYE_trial001_GAZE.csv
│   ├── 20251208_143022_EYE_trial001_IMU.csv
│   ├── 20251208_143022_EYE_trial001_EVENTS.csv
│   ├── 20251208_143022_EYE_trial001_FRAME_timing.csv
│   └── 20251208_143022_EYE_trial001_AUDIO_timing.csv
├── DRT/
│   └── 20251208_143022_DRT_ttyacm0.csv
├── VOG/
│   └── 20251208_143022_VOG_ttyacm0.csv
├── GPS/
│   └── 20251208_143022_GPS_trial001_GPS_serial0.csv
└── Notes/
    └── 20251208_143022_NTS_trial001_notes.csv
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
| Platform | Raspberry Pi 5 (Pi 4 compatible) |
| OS | Raspberry Pi OS Bookworm |
| Python | 3.11+ |
| RAM | 4GB minimum, 8GB recommended |
| Storage | USB 3.0 SSD recommended |

---

## Support

**Red Scientific**
[redscientific.com](https://redscientific.com)

---

*Professional multi-modal data collection for researchers who need reliable, synchronized sensor data.*
