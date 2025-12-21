# DRT Module

The DRT (Detection Response Task) module measures cognitive workload by recording reaction times to visual stimuli. Participants respond to a red LED stimulus by pressing a button as quickly as possible. Degraded reaction times indicate increased cognitive load.

The module supports two device types:
- **DRT (USB)** - USB-connected tactile response device
- **wDRT (Wireless DRT)** - XBee wireless response device

Devices are auto-detected when plugged in via USB.

---

## Getting Started

1. Connect your DRT device via USB (or XBee dongle for wDRT)
2. Enable the DRT module from the Modules menu
3. Wait for device detection (status shows device port)
4. Start a session to begin recording reaction times

---

## User Interface

### Real-time Chart

The main display shows:
- **Upper plot** - Stimulus state (ON/OFF) over time
- **Lower plot** - Reaction time bar chart for each stimulus

During recording, the chart scrolls to show a 60-second window of stimulus activity and reaction times.

### Results Panel (Capture Stats)

| Field | Description |
|-------|-------------|
| Stim | Current stimulus number |
| RT | Last reaction time in milliseconds (or "Miss") |
| Responses | Total button press count |
| Battery | Battery level (wDRT only) |

### Device Menu

- **Stimulus: ON** - Manually turn on the LED stimulus
- **Stimulus: OFF** - Manually turn off the LED stimulus
- **Configure...** - Open device configuration dialog

---

## Recording Sessions

### Starting a Session

When you start a recording session:
- Device enters experiment mode
- Chart clears and begins fresh
- Stim counter resets
- Stimulus cycle begins automatically

### During Recording

The DRT device automatically:
- Presents stimuli at random intervals (ISI range)
- Records reaction time for each stimulus
- Marks misses when no response before timeout

Each stimulus captures:
- Stimulus onset time
- Response time (or miss indicator)
- Reaction time (response - onset)

---

## Data Output

### File Location

```
{session_dir}/DRT/{prefix}_DRT_{device_id}.csv
```

Example: `20251208_143022_DRT_dev_ttyacm0.csv` (stim number is stored in the CSV data column)

### DRT CSV Columns (10 fields)

| Column | Description |
|--------|-------------|
| trial | Sequential stimulus count (1-based) |
| module | Module name ("DRT") |
| device_id | Device identifier (e.g., "DRT_dev_ttyacm0") |
| label | Trial/condition label (blank if not set) |
| record_time_unix | Host capture time (Unix seconds, 6 decimals) |
| record_time_mono | Host capture time (seconds, 9 decimals) |
| device_time_ms | Device timestamp in ms since experiment start |
| device_time_unix | Device absolute time (Unix seconds, if available) |
| responses | Button press count for this stimulus |
| reaction_time_ms | Response latency in ms (-1 = miss/timeout) |

**Example row:**
```
1,DRT,DRT_dev_ttyacm0,,1733649120.123456,12345.678901234,5000,,1,342
```

### wDRT CSV Columns (11 fields)

| Column | Description |
|--------|-------------|
| trial | Sequential stimulus count (1-based) |
| module | Module name ("DRT") |
| device_id | Device identifier (e.g., "wDRT_dev_ttyacm0") |
| label | Trial/condition label (blank if not set) |
| record_time_unix | Host capture time (Unix seconds, 6 decimals) |
| record_time_mono | Host capture time (seconds, 9 decimals) |
| device_time_ms | Device timestamp in ms since experiment start |
| device_time_unix | Device RTC timestamp (Unix seconds) |
| responses | Button press count for this stimulus |
| reaction_time_ms | Response latency in ms (-1 = miss/timeout) |
| battery_percent | Device battery level (0-100%) |

**Example row:**
```
2,DRT,wDRT_dev_ttyacm0,,1733649120.456789,12345.678901234,5500,1733649118,1,287,85
```

### Timing and Synchronization

**Reaction Time Measurement:**
```
Reaction Time = Device End Time - Stimulus Onset Time
```

The DRT device firmware measures reaction time internally with typical accuracy of 1-5 ms.

**Timestamp Precision:**
- record_time_unix: Seconds with microsecond precision (host system time)
- record_time_mono: Seconds with nanosecond precision (host monotonic clock)
- device_time_ms: Integer milliseconds (device time)
- reaction_time_ms: Integer milliseconds

**Miss Detection:**
A reaction time of -1 indicates a "miss" - the participant did not respond before the stimulus turned off.

**Cross-Module Synchronization:**
Use record_time_unix or record_time_mono to correlate DRT events with:
- Video frames (via camera timing CSV)
- Audio samples (via audio timing CSV)
- Eye tracking data (via gaze CSV)
- VOG lens states (via VOG record_time_* fields)

---

## Configuration

Click **Device > Configure** to access device settings.

### Timing Parameters

| Parameter | Description |
|-----------|-------------|
| Lower ISI | Minimum inter-stimulus interval (ms) |
| Upper ISI | Maximum inter-stimulus interval (ms) |
| Stim Duration | How long stimulus stays on (ms) |
| Intensity | LED brightness (0-100%) |

### ISO 17488 Standard Values

Click "ISO Defaults" to apply standard parameters:
- Lower ISI: 3000 ms
- Upper ISI: 5000 ms
- Stimulus Duration: 1000 ms
- Intensity: 100%

### Configuration Buttons

- **Get Config** - Reads current parameters from the device
- **Upload** - Sends new parameters to the device

---

## Understanding Results

### Reaction Times

| Range | Interpretation |
|-------|----------------|
| 200-500 ms | Normal range (unloaded baseline) |
| >500 ms | Elevated - indicates increased cognitive load |
| <150 ms | Very fast - may indicate anticipation |

### Misses

A "Miss" occurs when the participant fails to respond before the stimulus turns off. Misses indicate:
- High cognitive workload
- Inattention to the DRT task
- Possible equipment issues (check device)

### Hit Rate

The percentage of stimuli receiving valid responses. Lower hit rates indicate higher cognitive demand.

---

## Device Types

### DRT (USB)

USB-connected device with:
- Tactile response button
- Red LED stimulus
- Direct USB serial communication

**Connection:** USB cable to computer
**Port appears as:** COM port (Windows), `/dev/tty.*` (macOS), or `/dev/ttyACM*` (Linux)

### wDRT (Wireless DRT)

XBee-based wireless device with:
- Same response mechanism as USB DRT
- Battery powered for mobility
- XBee radio for wireless data

**Connection:** XBee USB dongle to computer
**Note:** Supports multiple wDRT devices on same network

---

## Troubleshooting

### Device not detected

1. Check USB connection
2. Verify device is powered on (wDRT: check battery)
3. Check that your OS recognizes the device:
   - Windows: Check Device Manager > Ports (COM & LPT)
   - macOS: Check System Information > USB
   - Linux: Run `lsusb` or check `/dev/ttyACM*`
4. Check the log panel for connection errors
5. Try unplugging and reconnecting

### No reaction times recorded

1. Ensure recording session is active
2. Verify stimulus LED is blinking
3. Check that button presses register (Responses count)
4. Review device configuration (ISI settings)

### All responses showing as "Miss"

1. Check stimulus duration is adequate (>500 ms)
2. Verify participant understands the task
3. Test button responsiveness manually
4. Check for loose connections

### Configure button doesn't work

1. Wait for device to fully connect
2. Ensure not currently recording
3. Check that runtime is bound (wait a moment after launch)

### wDRT not connecting

1. Verify XBee dongle is connected
2. Check wDRT battery level
3. Ensure devices are on same XBee network
4. Move devices closer together
