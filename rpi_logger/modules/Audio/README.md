# Audio Module

The Audio module records synchronized audio from a USB microphone during experiment sessions. It operates with a single audio input device assigned by the main logger and provides real-time level monitoring to help you verify audio is being captured correctly.

The device is discovered and assigned by the main logger - no manual device selection is needed.

---

## Getting Started

1. Connect your USB microphone
2. Enable the Audio module from the Modules menu
3. Wait for automatic device assignment (level meter appears when ready)
4. Start a session to begin recording

---

## User Interface

### Device Assignment

The audio device is automatically assigned by the main logger when the module starts. When a device is assigned, a level meter appears in the control panel. Only one audio device is supported per Audio module instance.

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
- Audio stream is captured to a WAV file
- Timing data is logged to a companion CSV file
- Level meter continues to show real-time levels

### During Recording

- One WAV file is created for the assigned microphone
- Audio is recorded continuously until you stop
- Timing CSV tracks every audio chunk for synchronization

---

## Data Output

### File Location

```
{session_dir}/Audio/
```

### Files Generated

For the assigned microphone, two files are created:

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
| trial | Trial number (integer, 1-based) |
| module | Module name ("Audio") |
| device_id | Device identifier (integer index) |
| label | Device name |
| record_time_unix | Host capture time (Unix seconds, 6 decimals) |
| record_time_mono | Host capture time (seconds, 9 decimals) |
| device_time_unix | Device absolute time (Unix seconds, if available) |
| device_time_seconds | Hardware ADC timestamp if available (seconds) |
| write_time_unix | Host write time (Unix seconds, 6 decimals) |
| write_time_mono | Host write time (seconds, 9 decimals) |
| chunk_index | Sequential chunk number (1-based) |
| frames | Number of audio samples in this chunk |
| total_frames | Cumulative sample count since recording started |

**Example row:**
```
1,Audio,0,usb-microphone,1702080123.456789,12.345678901,,12.345678901,1702080123.457123,12.346012345,1,2048,2048
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

### Device not assigned

1. Check USB connection
2. Verify device is powered on
3. Check system audio settings to confirm the device is recognized
4. Verify the main logger has discovered the device
5. Restart the module to trigger re-assignment

### No audio in recording

1. Check input levels in the meter display - should show activity when you speak
2. Verify microphone is not muted (check physical switches)
3. Check system audio input settings
4. Verify the correct device is assigned as the input source

### Level meter shows no activity

1. Speak into the microphone or tap it gently
2. Check physical mute switches on the microphone
3. Verify the correct device is assigned
4. Restart the module

### Empty device_time_seconds in CSV

This is normal - not all audio devices provide hardware timestamps. Use `record_time_mono` for synchronization instead.
