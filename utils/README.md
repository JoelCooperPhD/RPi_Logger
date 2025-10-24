# RPi Logger Utilities

Post-processing utilities for RPi Logger recordings.

---

## sync_and_mux.py

**Audio-Video Synchronization and Muxing Utility**

### Purpose

This utility processes RPi Logger session recordings to:
1. **Generate SYNC.json**: Create unified timing metadata files for all modules per trial
2. **Calculate Offsets**: Compute audio-video timing offsets from CSV logs
3. **Mux A/V Streams**: Combine audio and video files with frame-level synchronization (~30ms accuracy)
4. **Output MP4**: Create single MP4 files with AAC audio and H.264 video

### Usage

#### Process a single trial (default: trial 1)
```bash
python utils/sync_and_mux.py data/session_20251024_120000
```

#### Process a specific trial
```bash
python utils/sync_and_mux.py data/session_20251024_120000 --trial 3
```

#### Process all trials in a session
```bash
python utils/sync_and_mux.py data/session_20251024_120000 --all-trials
```

#### Generate sync files only (skip muxing)
```bash
python utils/sync_and_mux.py data/session_20251024_120000 --no-mux
```

### Input Files Required

For each trial, the utility automatically discovers and processes:

**Audio Files:**
- `{timestamp}_AUDIO_trial{N:03d}_MIC{id}_{name}.wav` - WAV audio recordings
- `{timestamp}_AUDIOTIMING_trial{N:03d}_MIC{id}.csv` - Per-chunk timing logs

**Video Files:**
- `{timestamp}_CAM_trial{N:03d}_CAM{id}_{w}x{h}_{fps}fps.mp4` - H.264 video recordings
- `{timestamp}_CAMTIMING_trial{N:03d}_CAM{id}.csv` - Per-frame timing logs

**Location:** All files should be in the session directory (e.g., `data/session_20251024_120000/`)

### Output Files

- **Sync Metadata**: `{timestamp}_SYNC_trial{N:03d}.json`
  - Contains timing information for all modules
  - Includes start times (Unix and monotonic), file paths, and module settings

- **Muxed Video**: `{timestamp}_AV_trial{N:03d}.mp4`
  - Single MP4 file with synchronized audio and video
  - Audio encoded as AAC at 192kbps
  - Video copied without re-encoding (lossless)

### How Synchronization Works

The sync_and_mux utility achieves ~30ms A/V synchronization accuracy through:

#### 1. Timestamp Capture (During Recording)
- **Audio**: Timestamps captured at chunk boundaries
  - ~21ms intervals @ 48kHz sample rate with 1024-sample chunks
  - CSV columns: `trial`, `chunk_number`, `write_time_unix`, `frames_in_chunk`, `total_frames`
- **Video**: Timestamps captured per-frame
  - ~33ms intervals @ 30fps (or ~16ms @ 60fps)
  - CSV columns: `trial`, `frame_number`, `write_time_unix`, `sensor_timestamp_ns`, `dropped_since_last`, `total_hardware_drops`

#### 2. Offset Calculation (Post-Processing)
- Reads `start_time_unix` from both audio and video CSV files
- Calculates offset: `audio_start - video_start`
  - **Positive offset**: Audio started after video → delay audio
  - **Negative offset**: Video started after audio → delay video
- Offset written to SYNC.json metadata

#### 3. FFmpeg Muxing (Post-Processing)
- Uses `-itsoffset` flag to apply calculated offset
- Video: Copied without re-encoding (lossless, fast)
- Audio: Converted to AAC @ 192kbps (standard web compatibility)
- Output: Single MP4 with synchronized tracks

#### 4. Accuracy and Limitations
- **Frame-level sync**: ~30ms accuracy (sufficient for most research applications)
- **Drift**: May accumulate in very long recordings (>1 hour)
- **Hardware sync**: For sub-frame accuracy (<5ms), hardware triggers required

### Configuration

Edit `Modules/base/constants.py` to configure:

```python
AV_MUXING_ENABLED = True          # Enable/disable muxing
AV_MUXING_TIMEOUT_SECONDS = 60    # FFmpeg timeout
AV_DELETE_SOURCE_FILES = False    # Keep/delete originals after mux
```

### Requirements

- **FFmpeg**: Must be installed and available in PATH
  ```bash
  sudo apt install ffmpeg  # Raspberry Pi / Debian
  ```

### Troubleshooting

**Error: "No audio or video files found"**
- Check that files follow the expected naming pattern
- Ensure trial number matches (e.g., `trial001`, `trial002`)

**Error: "ffmpeg mux failed"**
- Check FFmpeg is installed: `which ffmpeg`
- Check video/audio files are valid (not corrupted)
- Increase timeout in constants if files are very large

**Sync drift over time**
- Frame-level sync (~30ms accuracy) may accumulate drift in long recordings
- For sub-frame accuracy, consider hardware sync solutions

### Complete Workflow Example

#### 1. Record Session
```bash
# Launch main logger
python3 main_logger.py

# In the GUI:
# 1. Check "Cameras" and "AudioRecorder" modules
# 2. Click "Start Session"
# 3. Click "Record" to record trial 1
# 4. Click "Stop" when finished
# 5. Click "Record" again for trial 2
# 6. Repeat for additional trials
# 7. Click "End Session" when done
```

#### 2. Process Recordings
```bash
# Navigate to project root
cd ~/Development/RPi_Logger

# Process all trials in the session
python utils/sync_and_mux.py data/session_20251024_120000 --all-trials

# Or process specific trial
python utils/sync_and_mux.py data/session_20251024_120000 --trial 1
```

#### 3. Review Outputs
```
data/session_20251024_120000/
├── Cameras/
│   ├── 20251024_120000_CAM_trial001_CAM0_1456x1088_30.0fps.mp4
│   └── 20251024_120000_CAMTIMING_trial001_CAM0.csv
├── AudioRecorder/
│   ├── 20251024_120000_AUDIO_trial001_MIC0_usb-audio.wav
│   └── 20251024_120000_AUDIOTIMING_trial001_MIC0.csv
├── 20251024_120000_SYNC_trial001.json          ← Generated by sync_and_mux
└── 20251024_120000_AV_trial001.mp4             ← Muxed output
```

#### 4. Analyze Data
```python
import pandas as pd
import json

# Load sync metadata
with open('data/session_20251024_120000/20251024_120000_SYNC_trial001.json') as f:
    sync_data = json.load(f)

print(f"Audio offset: {sync_data['audio_offset']:.3f}s")

# Load timing CSVs
camera_timing = pd.read_csv('data/session_20251024_120000/Cameras/20251024_120000_CAMTIMING_trial001_CAM0.csv')
audio_timing = pd.read_csv('data/session_20251024_120000/AudioRecorder/20251024_120000_AUDIOTIMING_trial001_MIC0.csv')

# Check for dropped frames
print(f"Total dropped frames: {camera_timing['total_hardware_drops'].iloc[-1]}")
```

### Sync Metadata JSON Format

```json
{
  "trial_number": 1,
  "start_time_unix": 1729789123.456789,
  "start_time_monotonic": 12345.678,
  "modules": {
    "AudioRecorder_0": {
      "device_id": 0,
      "device_name": "USB Audio",
      "sample_rate": 48000,
      "chunk_size": 1024,
      "start_time_unix": 1729789123.456789,
      "start_time_monotonic": 12345.678,
      "audio_file": "path/to/audio.wav",
      "timing_csv": "path/to/audio_timing.csv"
    },
    "Camera_0": {
      "camera_id": 0,
      "fps": 30.0,
      "resolution": [1920, 1080],
      "start_time_unix": 1729789123.457,
      "start_time_monotonic": 12345.679,
      "video_file": "path/to/video.mp4",
      "timing_csv": "path/to/camera_timing.csv"
    }
  }
}
```

### Advanced Usage

#### Manual Muxing with Custom Offset

```python
from Modules.base.av_muxer import AVMuxer
from pathlib import Path

muxer = AVMuxer(timeout_seconds=60)
await muxer.mux_audio_video(
    video_path=Path("video.mp4"),
    audio_path=Path("audio.wav"),
    output_path=Path("output.mp4"),
    audio_offset=0.05  # 50ms offset
)
```

#### Reading Sync Metadata

```python
from Modules.base.sync_metadata import SyncMetadataWriter
from pathlib import Path

sync_data = await SyncMetadataWriter.read_sync_file(
    Path("session/SYNC_trial001.json")
)
print(sync_data)
```
