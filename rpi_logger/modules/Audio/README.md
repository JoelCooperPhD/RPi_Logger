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
| `{timestamp}_AUDIO_trial{NNN}_MIC{id}_{name}.wav` | Audio recording |
| `{timestamp}_AUDIOTIMING_trial{NNN}_MIC{id}_{name}.csv` | Timing data |

Example: `20251208_143022_AUDIO_trial001_MIC0_usb-microphone.wav`

### WAV Audio Format

| Property | Value |
|----------|-------|
| Format | PCM (uncompressed) |
| Bit Depth | 16-bit signed integer |
| Channels | Mono (1 channel) |
| Sample Rate | 48,000 Hz default (8-192 kHz supported) |

Multi-channel devices are recorded as mono using the first channel.

### Timing CSV Columns (8 fields)

The timing CSV contains per-chunk timing data for precise synchronization with other modules.

| Column | Description |
|--------|-------------|
| Module | Always "Audio" |
| trial | Trial number (integer, 1-based) |
| write_time_unix | System time when chunk was written (Unix seconds, 6 decimals) |
| chunk_index | Sequential chunk number (1-based) |
| write_time_monotonic | High-precision monotonic clock (seconds, 9 decimals) |
| adc_timestamp | Hardware ADC timestamp if available (seconds, 9 decimals) |
| frames | Number of audio samples in this chunk |
| total_frames | Cumulative sample count since recording started |

**Example row:**
```
Audio,1,1702080123.456789,1,12.345678901,12.345678901,2048,2048
```

### Understanding the Timestamps

The timing CSV provides three independent time sources for maximum flexibility:

| Timestamp | Use Case |
|-----------|----------|
| write_time_unix | Cross-module synchronization (matches other modules' Unix timestamps) |
| write_time_monotonic | Precise relative timing (never jumps or drifts) |
| adc_timestamp | Sample-accurate sync (most precise, but may be empty on some devices) |

### Calculating Audio Position

To find the exact time of any sample in the recording:

1. Find the chunk containing that sample using `total_frames`
2. Use `write_time_monotonic` for that chunk as the base time
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

### Empty adc_timestamp in CSV

This is normal - not all audio devices provide hardware timestamps. Use `write_time_monotonic` for synchronization instead.
