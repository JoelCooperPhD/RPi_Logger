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
- **Lower plot** - Reaction time bar chart for each trial

During recording, the chart scrolls to show a 60-second window of stimulus activity and reaction times.

### Results Panel (Capture Stats)

| Field | Description |
|-------|-------------|
| Trial | Current trial number |
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
- Trial counter resets
- Stimulus cycle begins automatically

### During Recording

The DRT device automatically:
- Presents stimuli at random intervals (ISI range)
- Records reaction time for each stimulus
- Marks misses when no response before timeout

Each trial captures:
- Stimulus onset time
- Response time (or miss indicator)
- Reaction time (response - onset)

---

## Data Output

### File Location

```
{session_dir}/DRT/{timestamp}_DRT_trial{NNN}_{device_id}.csv
```

Example: `20251208_143022_DRT_trial001_DRT_ttyACM0.csv`

### DRT CSV Columns (7 fields)

| Column | Description |
|--------|-------------|
| Device ID | Full device identifier (e.g., "DRT_dev_ttyacm0") |
| Label | Trial/condition label, or "NA" if not set |
| Unix time in UTC | Host timestamp when trial logged (Unix seconds) |
| Milliseconds Since Record | Device timestamp in ms since experiment start |
| Trial Number | Sequential trial count (1-based) |
| Responses | Button press count for this trial |
| Reaction Time | Response latency in ms (-1 = miss/timeout) |

**Example row:**
```
DRT_dev_ttyacm0,NA,1733649120,5000,1,1,342
```

### wDRT CSV Columns (9 fields)

| Column | Description |
|--------|-------------|
| Device ID | Full device identifier (e.g., "wDRT_dev_ttyacm0") |
| Label | Trial/condition label, or "NA" if not set |
| Unix time in UTC | Host timestamp when trial logged (Unix seconds) |
| Milliseconds Since Record | Device timestamp in ms since experiment start |
| Trial Number | Sequential trial count (1-based) |
| Responses | Button press count for this trial |
| Reaction Time | Response latency in ms (-1 = miss/timeout) |
| Battery Percent | Device battery level (0-100%) |
| Device time in UTC | Device's internal RTC timestamp (Unix seconds) |

**Example row:**
```
wDRT_dev_ttyacm0,NA,1733649120,5500,2,1,287,85,1733649118
```

### Timing and Synchronization

**Reaction Time Measurement:**
```
Reaction Time = Device End Time - Stimulus Onset Time
```

The DRT device firmware measures reaction time internally with typical accuracy of 1-5 ms.

**Timestamp Precision:**
- Unix time in UTC: Integer seconds (host system time)
- Milliseconds Since Record: Integer milliseconds (device time)
- Reaction Time: Integer milliseconds

**Miss Detection:**
A reaction time of -1 indicates a "miss" - the participant did not respond before the stimulus turned off.

**Cross-Module Synchronization:**
Use "Unix time in UTC" to correlate DRT events with:
- Video frames (via camera timing CSV)
- Audio samples (via audio timing CSV)
- Eye tracking data (via gaze CSV)
- VOG lens states (wDRT Lens column when synced)

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
