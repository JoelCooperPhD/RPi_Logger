# Audio Module

The Audio module records synchronized audio from USB microphones during experiment sessions. It supports multiple audio input devices and provides real-time level monitoring to help you verify audio is being captured correctly.

Devices are discovered by the main logger and automatically assigned to this module.

---

## Getting Started

1. Connect your USB microphone(s)
2. Enable the Audio module from the Modules menu
3. Wait for device assignment (level meters appear when ready)
4. Start a session to begin recording

---

## User Interface

### Device Selection

Audio devices are assigned by the main logger. When a device is assigned, a level meter appears in the control panel.

### Level Meters

Real-time audio level visualization shows whether your microphone is picking up sound:

| Color | Level | Meaning |
|-------|-------|---------|
| Green | Below -12 dB | Normal levels |
| Yellow | -12 to -6 dB | Moderate levels |
| Red | Above -6 dB | High levels / clipping risk |

For best results, aim for levels that occasionally touch yellow during normal speech but rarely go red.

---

## Recording Sessions

### Starting Recording

When you start a recording session:
- Audio streams are captured to WAV files
- Timing data is logged to companion CSV files
- Level meters continue to show real-time levels

### During Recording

- One WAV file is created per microphone
- Audio is recorded continuously until you stop
- Timing CSV tracks every audio chunk for synchronization

---

## Data Output

### File Location

```
{session_dir}/Audio/
```

### Files Generated

For each microphone, two files are created:

| File | Description |
|------|-------------|
| `{prefix}_MIC{id}_{name}.wav` | Audio recording |
| `{prefix}_MIC{id}_{name}_timing.csv` | Timing data |

Example: `20251208_143022_AUD_trial001_MIC0_usb-microphone.wav`

### WAV Audio Format

| Property | Value |
|----------|-------|
| Format | PCM (uncompressed) |
| Bit Depth | 16-bit signed integer |
| Channels | Mono (1 channel) |
| Sample Rate | 48,000 Hz default (8-192 kHz supported) |

Multi-channel devices are recorded as mono using the first channel.

### Timing CSV Columns (13 fields)

The timing CSV contains per-chunk timing data for precise synchronization with other modules.

| Column | Description |
|--------|-------------|
| module | Module name ("Audio") |
| trial | Trial number (integer, 1-based) |
| device_id | Device identifier (integer index) |
| label | Device name |
| device_time_unix | Device absolute time (Unix seconds, if available) |
| device_time_seconds | Hardware ADC timestamp if available (seconds) |
| record_time_unix | Host capture time (Unix seconds, 6 decimals) |
| record_time_mono | Host capture time (seconds, 9 decimals) |
| write_time_unix | Host write time (Unix seconds, 6 decimals) |
| write_time_mono | Host write time (seconds, 9 decimals) |
| chunk_index | Sequential chunk number (1-based) |
| frames | Number of audio samples in this chunk |
| total_frames | Cumulative sample count since recording started |

**Example row:**
```
Audio,1,0,usb-microphone,,12.345678901,1702080123.456789,12.345678901,1702080123.457123,12.346012345,1,2048,2048
```

### Understanding the Timestamps

The timing CSV provides distinct capture and write timestamps for maximum flexibility:

| Timestamp | Use Case |
|-----------|----------|
| record_time_unix | Cross-module synchronization (capture time) |
| record_time_mono | Precise relative timing (capture time, never jumps) |
| write_time_unix | Disk write timing (useful for performance analysis) |
| write_time_mono | Disk write timing (monotonic) |
| device_time_unix | Device absolute time (Unix seconds, if available) |
| device_time_seconds | Sample-accurate device timing (may be empty) |

### Calculating Audio Position

To find the exact time of any sample in the recording:

1. Find the chunk containing that sample using `total_frames`
2. Use `record_time_mono` for that chunk as the base time
3. Calculate offset: `(sample_position_in_chunk / sample_rate)`

To calculate recording duration:
```
duration_seconds = total_frames / sample_rate
```

---

## Configuration

| Setting | Default | Range | Notes |
|---------|---------|-------|-------|
| Sample Rate | 48,000 Hz | 8-192 kHz | Higher = better quality, larger files |
| Channels | Mono | Fixed | Multi-channel inputs use first channel |
| Bit Depth | 16-bit | Fixed | Standard CD-quality audio |

---

## Troubleshooting

### Device not detected

1. Check USB connection
2. Verify device is powered on
3. Check system audio settings to confirm the device is recognized
4. On Linux: Run `arecord -l` to list devices; ensure user is in 'audio' group
5. On macOS: Check System Preferences > Sound > Input
6. On Windows: Check Sound settings > Recording devices

### No audio in recording

1. Check input levels in the meter display - should show activity when you speak
2. Verify microphone is not muted (check physical switches)
3. Check system audio input settings
4. Verify the correct device is selected as the input source

### Level meter shows no activity

1. Speak into the microphone or tap it gently
2. Check physical mute switches on the microphone
3. Verify the correct device is assigned
4. Restart the module

### Empty device_time_seconds in CSV

This is normal - not all audio devices provide hardware timestamps. Use `record_time_mono` for synchronization instead.
