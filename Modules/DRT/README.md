# DRT Module - sDRT Device Monitor and Data Logger

## Overview

The DRT module provides multi-device support for sDRT (Simple Detection Response Task) devices connected via USB serial. It features automatic device detection, hot-plug support, real-time data display, and data logging.

## Architecture

### Reusable USB Serial Framework (`Modules/base/usb_serial_manager.py`)
- **USBDeviceConfig**: Device configuration (VID/PID, baudrate, timeouts)
- **USBSerialDevice**: Individual device connection and async I/O
- **USBDeviceMonitor**: Hot-plug detection with automatic connect/disconnect

### Module Structure
```
DRT/
├── main_drt.py                  # Entry point
├── config.txt                   # Configuration
└── drt_core/
    ├── constants.py             # Protocol commands and response types
    ├── drt_system.py            # Multi-device system management
    ├── drt_supervisor.py        # Lifecycle and error handling
    ├── drt_handler.py           # sDRT protocol implementation
    ├── modes/gui_mode.py        # GUI mode with device events
    ├── interfaces/gui/tkinter_gui.py  # Multi-device GUI
    ├── commands/handler.py      # Main logger integration
    └── config/                  # Config loading
```

## sDRT Communication Protocol

### Commands Sent to Device

All commands are formatted as: `command [value]\n\r`

| Command | Format | Description |
|---------|--------|-------------|
| exp_start | `exp_start\n\r` | Start experiment/recording |
| exp_stop | `exp_stop\n\r` | Stop experiment/recording |
| stim_on | `stim_on\n\r` | Enable stimulus |
| stim_off | `stim_off\n\r` | Disable stimulus |
| get_config | `get_config\n\r` | Request device configuration |
| get_lowerISI | `get_lowerISI\n\r` | Get lower ISI value |
| set_lowerISI | `set_lowerISI 3000\n\r` | Set lower ISI (ms) |
| get_upperISI | `get_upperISI\n\r` | Get upper ISI value |
| set_upperISI | `set_upperISI 5000\n\r` | Set upper ISI (ms) |
| get_stimDur | `get_stimDur\n\r` | Get stimulus duration |
| set_stimDur | `set_stimDur 1000\n\r` | Set stimulus duration (ms) |
| get_intensity | `get_intensity\n\r` | Get stimulus intensity |
| set_intensity | `set_intensity 255\n\r` | Set stimulus intensity (0-255) |
| get_name | `get_name\n\r` | Get device name |

### ISO Preset Configuration

The `set_iso_params()` method sends a batch configuration:
- `set_lowerISI 3000`
- `set_upperISI 5000`
- `set_stimDur 1000`
- `set_intensity 255`

(50ms delay between each command)

### Responses Received from Device

All responses use `>` as delimiter: `type>value` or `type>value1>value2`

| Response Type | Format | Example | Description |
|---------------|--------|---------|-------------|
| Click | `clk>value` | `clk>123` | Button click event |
| Trial | `trl>trial_num>reaction_time` | `trl>5>342` | Trial result (RT in ms) |
| Experiment End | `end` | `end` | Experiment completed |
| Stimulus | `stm>value` | `stm>on` | Stimulus state callback |
| Config | `cfg>value` | `cfg>...` | Configuration response |

## Device Configuration

**VID/PID** (in `config.txt`):
- **VID**: 9114 (0x239A - Adafruit Industries)
- **PID**: 32799 (0x801F - Trinket M0)
- **Baudrate**: 9600

To support different devices, update these values in `config.txt`.

## Data Logging

Trial data is logged to CSV files with format:
```
Timestamp,Port,TrialNumber,ReactionTime_ms
2025-10-23T10:15:30.123456,/dev/ttyACM0,1,342
2025-10-23T10:15:32.456789,/dev/ttyACM0,2,298
```

Files are created per device: `sDRT_<port>_<timestamp>.csv`

## Usage

### Standalone Mode
```bash
cd Modules/DRT
python3 main_drt.py --mode gui
```

### With Main Logger
The module auto-integrates when `enabled = true` in `config.txt`

### Multi-Device Support
- Automatically detects and connects to all sDRT devices
- Each device gets its own data file
- GUI shows all connected devices with live data feed
- Hot-plug/unplug supported during operation

## GUI Features

The GUI replicates the original sDRT UI design with modern improvements:

### Real-Time Scrolling Plot
- **60-second sliding window** showing historical data
- **Upper Subplot**: Stimulus state (On/Off) over time
- **Lower Subplot**: Reaction times with hit/miss markers
  - Circles (o) = Hits
  - X markers = Misses
- **Auto-scaling**: Y-axis adapts to reaction time range
- **Multi-device support**: Each device gets its own colored line

### Device Selection
- **Dropdown menu** to select active device for control
- Auto-selects first device on connection
- Shows all connected devices

### Stimulus Controls
- **ON Button**: Enable stimulus on selected device
- **OFF Button**: Disable stimulus on selected device
- Real-time visual feedback in plot

### Results Display
Shows current trial data for selected device:
- **Trial Number**: Current trial count
- **Reaction Time**: Latest RT in milliseconds
- **Response Count**: Click count during trial

### Configure Button
- One-click ISO preset configuration
- Sets standard parameters:
  - Lower ISI: 3000ms
  - Upper ISI: 5000ms
  - Stimulus Duration: 1000ms
  - Intensity: 255

### Recording Control
- Start/stop recording via File menu or main logger
- Window title updates to show recording status

## Extending to Other Devices

The USB serial framework is designed for reuse. To add wDRT, VOG, or GPS:

1. Copy the DRT module structure
2. Update `config.txt` with new VID/PID
3. Modify `constants.py` with device-specific commands
4. Update `<device>_handler.py` for device protocol
5. Reuse `USBDeviceMonitor` - no changes needed!

## API Reference

### DRTHandler Methods

```python
async def send_command(command: str, value: Optional[str] = None) -> bool
async def start_experiment() -> bool
async def stop_experiment() -> bool
async def set_stimulus(enabled: bool) -> bool
async def set_iso_params() -> bool
```

### DRTSystem Methods

```python
def get_connected_devices() -> Dict[str, USBSerialDevice]
def get_device_handler(port: str) -> Optional[DRTHandler]
async def start_recording() -> bool
async def stop_recording() -> bool
```

## Notes

- Commands are sent with `\n\r` line endings
- Responses are parsed by splitting on `>` delimiter
- All file I/O uses async patterns (`asyncio.to_thread`)
- Device detection runs every 1 second
- Auto-reconnection on disconnect with exponential backoff (handled by supervisor)
