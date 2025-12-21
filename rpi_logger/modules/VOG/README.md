# VOG Module

The VOG (Visual Occlusion Glasses) module controls electronic shutter glasses for vision research experiments. The glasses can rapidly switch between clear (transparent) and opaque states with millisecond precision, enabling precise control of visual stimulus presentation.

Devices are auto-detected when plugged in via USB.

---

## Getting Started

1. Connect your VOG device via USB
2. Enable the VOG module from the Modules menu
3. Wait for the device tab to appear (indicates successful detection)
4. Use the lens controls or start a recording session

---

## User Interface

### Device Tabs

Each connected device gets its own tab showing:

| Element | Description |
|---------|-------------|
| Real-time Chart | Stimulus state and shutter timing over 60 seconds |
| Lens Controls | Buttons to manually open/close lenses |
| Results Panel | Trial number and timing data (TSOT/TSCT) |
| Configure | Opens device settings dialog |

### Lens Controls

| Button | Action |
|--------|--------|
| Clear/Open | Opens the lens (transparent) |
| Opaque/Close | Closes the lens (blocks vision) |

Wireless devices have additional buttons for independent left/right lens control.

### Results Display

After each trial, the panel shows:

| Metric | Description |
|--------|-------------|
| Trial Number | Current trial count |
| TSOT | Total Shutter Open Time (milliseconds the participant could see) |
| TSCT | Total Shutter Close Time (milliseconds the participant was occluded) |

---

## Recording Sessions

### Starting a Session

When you start a recording session:
- Device enters experiment mode
- Chart clears and begins fresh
- Trial counter resets to 1

### During Recording

Each trial captures:
- Timing data for all lens state changes
- Accumulated open/close durations
- Timestamps synchronized to system time

---

## Data Output

### File Location

```
{session_dir}/VOG/
```

### File Naming

```
    {timestamp}_VOG_{port}.csv
```

Example: `20251208_143022_VOG_ttyACM0.csv` (trial number is stored in the CSV data column)

### sVOG CSV Columns (8 fields)

For wired VOG devices:

| Column | Description |
|--------|-------------|
| trial | Sequential trial count (1-based) |
| module | Module name ("VOG") |
| device_id | Device identifier (e.g., "sVOG") |
| label | Trial/condition label (blank if not set) |
| record_time_unix | Host capture time (Unix seconds, 6 decimals) |
| record_time_mono | Host capture time (seconds, 9 decimals) |
| shutter_open | Total Shutter Open Time (milliseconds) |
| shutter_closed | Total Shutter Close Time (milliseconds) |

**Example row:**
```
1,VOG,sVOG,,1733649120.123456,12345.678901234,1500,3500
```

### wVOG CSV Columns (11 fields)

For wireless VOG devices (same first 8 columns as sVOG, plus):

| Column | Description |
|--------|-------------|
| shutter_total | Combined shutter time (milliseconds) |
| lens | Lens state (Open/Closed/Left/Right) |
| battery_percent | Device battery level (0-100%) |

**Example row:**
```
2,VOG,wVOG,,1733649120.456789,12345.678901234,3000,2500,5500,Open,85
```

### Timing and Synchronization

**Timing Precision:**
- TSOT/TSCT: Millisecond precision (device firmware)
- Unix time in UTC: Microsecond precision (6 decimals)
- Lens state changes: Device-measured (<50ms for close, <15ms for open, continuous state change)

**Cross-Module Synchronization:**
Use "Unix time in UTC" to correlate VOG events with:
- Video frames (via camera `capture_time_unix`)
- Audio samples (via audio `record_time_unix`)
- DRT trials (via DRT `record_time_unix`)
- Eye tracking data (via `record_time_unix`)

---

## Experiment Types

### Cycle

Standard visual occlusion testing following NHTSA Visual Manual Distraction Guidelines and ISO 16673.

**How it works:** The lenses automatically alternate between clear and opaque at fixed intervals (e.g., 1.5 seconds each). Participants perform a task while only able to see during the clear periods. The system records total shutter open time (TSOT) and total task time.

**Use case:** Measuring the visual demand of in-vehicle interfaces and other tasks requiring intermittent visual attention.

### Peek

For testing interfaces where the primary modality is non-visual (e.g., auditory or haptic) but occasional visual confirmation may be needed.

**How it works:** Lenses start opaque. Participants press a button to request a "peek" - the lenses clear for a set duration (default 1.5 seconds) then return to opaque. A lockout period prevents consecutive peeks.

**Data collected:** Number of peeks and cumulative peek time, providing a measure of visual attention demand for interfaces designed for eyes-free operation.

**Use case:** Evaluating voice-controlled or auditory display systems where visual glances should be minimized.

### eBlindfold

For measuring visual search time.

**How it works:** Trial begins with lenses clear. The participant searches for a specified target. Upon locating the target, they press the button - the lenses immediately go opaque and the trial ends. Total shutter open time equals search time.

**Use case:** Measuring visual search performance, comparing display layouts, or evaluating icon/element discoverability.

### Direct

Simple manual control mode for integrating with external equipment or custom experiment setups.

**How it works:** The lenses directly mirror the button state - press and hold to clear, release to go opaque (or vice versa). No timing data is recorded by the glasses themselves.

**Use case:** When you need to control the glasses from other laboratory equipment, or for demonstrations and testing.

---

## Configuration

Click **"Configure Unit"** on any device tab to access settings.

| Setting | Description |
|---------|-------------|
| Open/Close Time | Lens timing duration (ms) |
| Debounce | Button debounce time (ms) |
| Opacity | Lens transparency levels (0-100%) |

The configuration dialog adapts to show available options based on the connected device type.

---

## Troubleshooting

### Device not detected

1. Check USB connection
2. Verify device is powered on
3. Check that your OS recognizes the device:
   - Windows: Check Device Manager > Ports (COM & LPT)
   - macOS: Check System Information > USB
   - Linux: Run `lsusb` to list USB devices
4. Check the log panel for connection errors

### No data after trial

1. Ensure recording was started before the trial
2. Check that the session directory exists and is writable
3. Review module logs for errors

### Lens not responding

1. Try Configure > Refresh to reload device state
2. Check battery level (wireless devices)
3. Reconnect the USB cable
4. Restart the module
