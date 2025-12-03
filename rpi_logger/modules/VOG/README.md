# VOG Module

Visual Occlusion Glasses (VOG) module for controlling shutter glasses in vision
research experiments.

## Overview

The VOG module controls electronic shutter glasses that can rapidly switch
between clear (transparent) and opaque states. This enables researchers to
control visual stimulus presentation with millisecond precision.

Devices are auto-detected when plugged in via USB.

## Getting Started

1. Connect your VOG device via USB
2. Enable the VOG module from the Modules menu
3. Wait for the device tab to appear (indicates successful detection)
4. Use the lens controls or start a recording session

## User Interface

### Device Tabs

Each connected device gets its own tab showing:

- **Real-time Chart**: Displays stimulus state and shutter timing over 60 seconds
- **Lens Controls**: Buttons to manually open/close lenses
- **Results Panel**: Shows trial number and timing data (TSOT/TSCT)
- **Configure Button**: Opens device settings dialog

### Lens Controls

- **Clear/Open**: Opens the lens (transparent)
- **Opaque/Close**: Closes the lens (blocks vision)

Wireless devices have additional buttons for independent left/right lens control.

### Results Display

After each trial, the panel shows:
- **Trial Number**: Current trial count
- **TSOT**: Total Shutter Open Time (milliseconds)
- **TSCT**: Total Shutter Close Time (milliseconds)

## Recording Sessions

### Starting a Session

When you start a recording session from the main application:
1. The device enters experiment mode
2. The chart clears and begins fresh
3. Trial counter resets to 1

### During Recording

Each trial captures:
- Timing data for all lens state changes
- Accumulated open/close durations
- Timestamps synchronized to system time

### Stopping Recording

When recording stops:
- Device exits experiment mode
- Data is saved to CSV files in the session directory
- Chart data is preserved for review

## Data Output

Trial data is saved as CSV files:

```
{session_dir}/VOG/{timestamp}_VOG_trial{N}_VOG_{port}.csv
```

CSV columns include device ID, timestamps, trial number, and shutter timing data.

## Configuration

Click the "Configure" button on any device tab to access settings.

Common settings include:
- **Open/Close Time**: Lens timing duration (ms)
- **Debounce**: Button debounce time (ms)
- **Opacity**: Lens transparency levels (0-100%)

The configuration dialog adapts to show available options based on the connected device type.

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

## Troubleshooting

### Device not detected

1. Check USB connection
2. Verify device is powered on
3. Run `lsusb` to confirm device is visible to the system
4. Check the log panel for connection errors

### No data after trial

1. Ensure recording was started before the trial
2. Check that the session directory exists and is writable
3. Review module logs for errors

### Lens not responding

1. Try the Configure > Refresh button to reload device state
2. Check battery level (wireless devices)
3. Reconnect the USB cable
4. Restart the module

## Module Files

```
rpi_logger/modules/VOG/
├── main_vog.py          # Entry point
├── config.txt           # Module configuration
└── vog_core/            # Core functionality
    ├── vog_system.py    # Device orchestration
    ├── vog_handler.py   # Per-device communication
    ├── data_logger.py   # CSV output
    └── protocols/       # Device protocol implementations
```
