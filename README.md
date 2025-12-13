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
git clone https://github.com/redscientific/RS_Logger2.git
cd RS_Logger2
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

```
session_YYYYMMDD_HHMMSS/
├── Cameras/
│   ├── video.mp4
│   └── frame_timing.csv
├── AudioRecorder/
│   ├── audio.wav
│   └── chunk_timing.csv
├── EyeTracker/
│   ├── scene_video.mp4
│   └── gaze_data.csv
├── DRT/
│   └── response_data.csv
├── VOG/
│   └── shutter_timing.csv
├── GPS/
│   └── location_data.csv
└── Notes/
    └── annotations.csv
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
