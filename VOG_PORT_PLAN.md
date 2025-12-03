# VOG (Occlusion Glasses) Port Plan: RS_Logger → RPi_Logger

## Overview

Port VOG (Visual Occlusion Glasses) functionality from RS_Logger to RPi_Logger as an autonomous module supporting **both sVOG (wired) and wVOG (wireless)** devices.

**Scope**: Universal VOG module supporting all device variants
**Firmware**: No changes - must work with existing field devices
**Independence**: VOG operates autonomously, separate from DRT

### Device Variants

| Variant | Connection | VID | PID | Protocol |
|---------|------------|-----|-----|----------|
| **sVOG** | USB Serial | 0x16C0 | 0x0483 | `>cmd\|val<<` |
| **wVOG** | XBee 802.15.4 + USB fallback | 0xf057 | 0x08AE | `cmd>val` |
| **wVOG Dongle** | FTDI USB-UART (XBee host) | 0x0403 | 0x6015 | N/A |

---

## Getting Up to Speed

If you're resuming this project, read these files in order to understand the architecture:

### 1. Understand the Existing sVOG Protocol (5 min)
```
RS_Logger/RSLogger/hardware_io/sVOG_HI/sVOG_HIController.py
```
- Small file (~100 lines)
- Shows exact command format: `>do_expStart|<<`, `>get_configName|<<`, etc.
- Shows response parsing: `keyword|value` format
- Shows CSV logging format

### 2. Understand RPi_Logger Module Pattern (15 min)
Read these DRT files in order:

```
RPi_Logger/rpi_logger/modules/DRT/
├── config.txt                 # Module config format
├── main_drt.py               # Entry point pattern (argparse, supervisor setup)
├── drt_core/
│   ├── constants.py          # Command definitions
│   ├── drt_handler.py        # Per-device serial handler (KEY FILE)
│   ├── drt_system.py         # System coordinator (KEY FILE)
│   └── commands/handler.py   # Master logger integration
```

**Key patterns to note:**
- `BaseSystem` inheritance and `_initialize_devices()` method
- `USBDeviceMonitor` for device discovery
- Async read loops with `await device.read_line()`
- CSV logging with `module_filename_prefix()`
- `StatusMessage.send()` for master communication

### 3. Understand Base Classes (10 min)
```
RPi_Logger/rpi_logger/modules/base/
├── base_system.py            # BaseSystem abstract class
├── usb_serial_manager.py     # USBDeviceMonitor, USBSerialDevice
├── command_handler.py        # BaseCommandHandler
└── storage_utils.py          # module_filename_prefix()
```

### 4. Current VOG Module Structure
```
RPi_Logger/rpi_logger/modules/VOG/
├── config.txt                # Device settings (VID, PID, baud)
├── main_vog.py              # Entry point (minimal placeholder)
├── vog_core/
│   ├── constants.py         # Command protocol (Task 2)
│   ├── vog_handler.py       # Device handler (Task 4)
│   ├── vog_system.py        # System coordinator (Task 5)
│   ├── config/
│   │   └── config_loader.py # Config loading (Task 3)
│   ├── commands/
│   │   └── handler.py       # Master integration (Task 6)
│   ├── modes/
│   │   ├── gui_mode.py      # GUI mode (Task 14)
│   │   └── simple_mode.py   # Headless mode (Task 7)
│   └── interfaces/gui/
│       ├── tkinter_gui.py   # Main GUI (Tasks 10-11)
│       ├── vog_plotter.py   # Plotter (Task 12)
│       └── config_window.py # Config dialog (Task 13)
└── vog/
    ├── runtime.py           # VMC runtime (Task 15)
    └── view.py              # VMC view (Task 15)
```

### 5. Quick Verification Commands
```bash
cd /home/joel/Development/RPi_Logger

# Verify module is discovered
python3 -c "from rpi_logger.core.module_discovery import discover_modules; print([m.name for m in discover_modules()])"

# Test import (should show no errors)
python3 -c "from rpi_logger.modules.VOG.vog_core.constants import SVOG_COMMANDS; print(len(SVOG_COMMANDS))"
```

---

## How to Use This Plan

### Before Starting Each Task

1. **Read the task completely** - Understand the goal, files, and test criteria
2. **Check dependencies** - Verify all prerequisite tasks are marked complete
3. **Review reference files** - Look at the RS_Logger and RPi_Logger files listed in Quick Reference
4. **State your intent** - Tell Claude: "Starting Task N: [Task Name]"

### While Working on a Task

1. **Focus on ONE task only** - Do not add features from future tasks
2. **Follow existing patterns** - Match the DRT module's style and structure
3. **Keep it minimal** - Implement only what's needed to pass the test criteria
4. **Test as you go** - Run the test criteria commands after each significant change

### Completing a Task

1. **Run ALL test criteria** - Every checkbox must pass
2. **Mark checkboxes complete** - Change `[ ]` to `[x]` in this file
3. **Update task status** - Add `**Status: COMPLETE**` after the task header
4. **Create the commit** - Use the exact commit message provided
5. **Verify the commit** - Ensure only files for this task are included

### If You Get Stuck

1. **Check the reference files** - DRT implementation is your guide
2. **Re-read the task goal** - Make sure you understand what's needed
3. **Simplify** - Can you make a smaller change that still passes tests?
4. **Ask for clarification** - If requirements are unclear, stop and ask

### Commands to Remember

```bash
# Run from RPi_Logger directory
cd /home/joel/Development/RPi_Logger

# Test module import
python -c "from rpi_logger.modules.VOG import *"

# Test module discovery
python -c "from rpi_logger.core.module_discovery import discover_modules; print([m.name for m in discover_modules()])"

# Run module standalone (after Task 8)
python -m rpi_logger.modules.VOG.main_vog --help

# Build executable (Task 16)
pyinstaller rpi_logger.spec
```

### Progress Tracking

Update this section as tasks complete:

| Task | Status | Date |
|------|--------|------|
| 1. Scaffolding | COMPLETE | 2025-12-02 |
| 2. Constants | COMPLETE | 2025-12-02 |
| 3. Config Loader | COMPLETE | 2025-12-02 |
| 4. VOG Handler | COMPLETE | 2025-12-02 |
| 5. VOG System | COMPLETE | 2025-12-02 |
| 6. Command Handler | COMPLETE | 2025-12-02 |
| 7. Simple Mode | COMPLETE | 2025-12-02 |
| 8. Entry Point | COMPLETE | 2025-12-02 |
| 9. Hardware Validation | **PENDING - requires sVOG hardware** | |
| 10. GUI - Device Tab | COMPLETE | 2025-12-02 |
| 11. GUI - Main Window | COMPLETE | 2025-12-02 |
| 12. GUI - Plotter | COMPLETE | 2025-12-02 |
| 13. GUI - Config Dialog | COMPLETE | 2025-12-02 |
| 14. GUI Mode | COMPLETE | 2025-12-02 |
| 15. VMC Integration | COMPLETE | 2025-12-02 |
| 16. Build Integration | COMPLETE | 2025-12-02 |
| 17. Integration Testing | COMPLETE | 2025-12-02 |
| 18. Documentation | COMPLETE | 2025-12-02 |
| **Phase 2: wVOG Support** | | |
| 19. Protocol Abstraction Layer | COMPLETE | 2025-12-02 |
| 20. VOGHandler Protocol Integration | COMPLETE | 2025-12-02 |
| 21. VOGSystem Multi-Device Support | COMPLETE | 2025-12-02 |
| 22. wVOG Hardware Validation | COMPLETE | 2025-12-02 |
| 24. GUI Dual Lens Control | COMPLETE | 2025-12-02 |
| 25. Config Dialog Update | COMPLETE | 2025-12-02 |
| 26. Config Loader Update | COMPLETE | 2025-12-02 |
| 29. Universal Integration Testing | PENDING | |
| 30. Documentation Update | PENDING | |

---

## Task List

### Task 1: Module Scaffolding **Status: COMPLETE**
**Goal**: Create the basic directory structure and empty files

**Create these files/directories**:
```
rpi_logger/modules/VOG/
├── __init__.py
├── main_vog.py
├── config.txt
├── vog_core/
│   ├── __init__.py
│   ├── constants.py
│   ├── vog_system.py
│   ├── vog_handler.py
│   ├── config/
│   │   ├── __init__.py
│   │   └── config_loader.py
│   ├── commands/
│   │   ├── __init__.py
│   │   └── handler.py
│   ├── modes/
│   │   ├── __init__.py
│   │   ├── gui_mode.py
│   │   └── simple_mode.py
│   └── interfaces/
│       └── gui/
│           ├── __init__.py
│           ├── tkinter_gui.py
│           ├── vog_plotter.py
│           └── config_window.py
└── vog/
    ├── __init__.py
    ├── runtime.py
    └── view.py
```

**config.txt contents**:
```ini
display_name = VOG
visible = true
enabled = true
device_vid = 0x16C0
device_pid = 0x0483
baudrate = 9600
window_geometry = 400x300
output_dir = vog_data
log_level = info
```

**Test criteria**:
- [x] Directory structure exists
- [x] `python3 -c "from rpi_logger.modules.VOG import main_vog"` runs without error
- [x] Module discovery finds VOG: `python3 -c "from rpi_logger.core.module_discovery import discover_modules; print([m.name for m in discover_modules()])"` includes 'Vog'

**Commit message**: `feat(VOG): add module scaffolding and directory structure`

---

### Task 2: Constants and Command Protocol
**Goal**: Define the sVOG command protocol matching existing firmware

**File**: `vog_core/constants.py`

**Contents**:
```python
"""sVOG command protocol constants - must match existing firmware exactly."""

# sVOG Commands (Arduino protocol)
SVOG_COMMANDS = {
    'exp_start': '>do_expStart|<<',
    'exp_stop': '>do_expStop|<<',
    'trial_start': '>do_trialStart|<<',
    'trial_stop': '>do_trialStop|<<',
    'peek_open': '>do_peekOpen|<<',
    'peek_close': '>do_peekClose|<<',
    'get_device_ver': '>get_deviceVer|<<',
    'get_config_name': '>get_configName|<<',
    'get_max_open': '>get_configMaxOpen|<<',
    'get_max_close': '>get_configMaxClose|<<',
    'get_debounce': '>get_configDebounce|<<',
    'get_click_mode': '>get_configClickMode|<<',
    'get_button_control': '>get_configButtonControl|<<',
    'set_config_name': '>set_configName|{val}<<',
    'set_max_open': '>set_configMaxOpen|{val}<<',
    'set_max_close': '>set_configMaxClose|{val}<<',
    'set_debounce': '>set_configDebounce|{val}<<',
    'set_click_mode': '>set_configClickMode|{val}<<',
    'set_button_control': '>set_configButtonControl|{val}<<',
}

# Response keywords from device
SVOG_RESPONSE_KEYWORDS = [
    'deviceVer',
    'configName',
    'configMaxOpen',
    'configMaxClose',
    'configDebounce',
    'configClickMode',
    'configButtonControl',
    'stm',
    'data',
]

# Response types for parsing
SVOG_RESPONSE_TYPES = {
    'deviceVer': 'version',
    'configName': 'config',
    'configMaxOpen': 'config',
    'configMaxClose': 'config',
    'configDebounce': 'config',
    'configClickMode': 'config',
    'configButtonControl': 'config',
    'stm': 'stimulus',
    'data': 'data',
}

# CSV header for data output
CSV_HEADER = "Device ID, Label, Unix time in UTC, Milliseconds Since Record, Trial Number, Shutter Open, Shutter Closed"
```

**Test criteria**:
- [ ] `python -c "from rpi_logger.modules.VOG.vog_core.constants import SVOG_COMMANDS; print(len(SVOG_COMMANDS))"` returns 17
- [ ] Commands match RS_Logger protocol exactly (verified against `RS_Logger/RSLogger/hardware_io/sVOG_HI/sVOG_HIController.py`)

**Commit message**: `feat(VOG): add command protocol constants`

---

### Task 3: Config Loader
**Goal**: Load module configuration with defaults

**File**: `vog_core/config/config_loader.py`

**Test criteria**:
- [ ] `load_config_file()` returns dict with all default values when no config exists
- [ ] Config values from file override defaults
- [ ] Hex values (VID/PID) are parsed correctly

**Commit message**: `feat(VOG): add configuration loader`

---

### Task 4: VOG Handler (Serial Communication)
**Goal**: Per-device serial communication handler

**File**: `vog_core/vog_handler.py`

**Key functionality**:
- Async serial read loop
- Command sending with proper formatting
- Response parsing (config, stimulus, data)
- CSV data logging

**Test criteria**:
- [ ] `VOGHandler` class instantiates without error
- [ ] `send_command()` formats commands correctly (unit test with mock serial)
- [ ] `_process_response()` correctly parses all response types
- [ ] CSV output matches expected format

**Commit message**: `feat(VOG): add device handler with serial communication`

---

### Task 5: VOG System (Device Management)
**Goal**: Main system coordinator with USB device discovery

**File**: `vog_core/vog_system.py`

**Key functionality**:
- Inherit from `BaseSystem`
- USB device monitoring via `USBDeviceMonitor`
- Device connect/disconnect handling
- Recording start/stop coordination

**Test criteria**:
- [ ] `VOGSystem` class instantiates without error
- [ ] System creates `USBDeviceMonitor` with correct VID/PID
- [ ] `start_recording()` sends commands to all handlers
- [ ] `stop_recording()` sends commands to all handlers

**Commit message**: `feat(VOG): add system coordinator with USB device management`

---

### Task 6: Command Handler (Master Logger Integration)
**Goal**: Handle JSON commands from master logger

**File**: `vog_core/commands/handler.py`

**Key functionality**:
- Inherit from `BaseCommandHandler`
- Implement `_start_recording_impl()`
- Implement `_stop_recording_impl()`
- Send `StatusMessage` responses

**Test criteria**:
- [ ] `VOGCommandHandler` class instantiates
- [ ] Recording commands update system state
- [ ] StatusMessage sent on recording start/stop

**Commit message**: `feat(VOG): add command handler for master logger integration`

---

### Task 7: Simple Mode (Headless)
**Goal**: Headless mode for testing without GUI

**File**: `vog_core/modes/simple_mode.py`

**Test criteria**:
- [ ] Module can run in headless mode
- [ ] Commands received via stdin are processed
- [ ] Status messages sent to stdout

**Commit message**: `feat(VOG): add headless mode`

---

### Task 8: Entry Point
**Goal**: Main entry point that ties everything together

**File**: `main_vog.py`

**Key functionality**:
- Argument parsing with config overrides
- Logging setup
- System initialization
- Mode selection (gui/headless)
- Signal handling

**Test criteria**:
- [ ] `python -m rpi_logger.modules.VOG.main_vog --help` shows usage
- [ ] Module discovered by master logger
- [ ] Standalone launch works: `python -m rpi_logger.modules.VOG.main_vog --mode headless --enable-commands`

**Commit message**: `feat(VOG): add main entry point`

---

### Task 9: Hardware Validation
**Goal**: Verify communication with real sVOG device

**Test criteria** (requires hardware):
- [ ] Device detected when plugged in
- [ ] `get_config` commands return valid responses
- [ ] `exp_start` / `exp_stop` commands work
- [ ] Trial data received and logged to CSV
- [ ] Peek open/close commands work

**Commit message**: `test(VOG): verify hardware communication`

---

### Task 10: GUI - Device Tab Widget
**Goal**: Per-device tab with controls and results display

**File**: `vog_core/interfaces/gui/tkinter_gui.py` (VOGDeviceTab class)

**Key functionality**:
- Peek Open / Peek Close buttons
- Configure button
- Results display (Trial, Shutter Open, Shutter Closed)
- Placeholder for plotter

**Test criteria**:
- [ ] Tab displays correctly when device connects
- [ ] Buttons trigger correct commands
- [ ] Results update when data received

**Commit message**: `feat(VOG): add device tab GUI widget`

---

### Task 11: GUI - Main Window
**Goal**: Main VOG window with device tabs

**File**: `vog_core/interfaces/gui/tkinter_gui.py` (VOGTkinterGUI class)

**Key functionality**:
- Inherit from `TkinterGUIBase`
- Notebook for device tabs
- Status bar showing connection count
- Device connect/disconnect handling

**Test criteria**:
- [ ] Window opens without error
- [ ] Tabs added when devices connect
- [ ] Tabs removed when devices disconnect
- [ ] Status bar updates correctly

**Commit message**: `feat(VOG): add main GUI window`

---

### Task 12: GUI - Real-time Plotter
**Goal**: Matplotlib plotter for stimulus state and accumulated times

**File**: `vog_core/interfaces/gui/vog_plotter.py`

**Key functionality**:
- Two subplots (stimulus state, accumulated times)
- Real-time updates
- Clear on recording start

**Test criteria**:
- [ ] Plotter displays in device tab
- [ ] Stimulus events shown correctly
- [ ] Accumulated times update on data received
- [ ] Clear resets all data

**Commit message**: `feat(VOG): add real-time plotter`

---

### Task 13: GUI - Config Dialog
**Goal**: Device configuration dialog

**File**: `vog_core/interfaces/gui/config_window.py`

**Key functionality**:
- Modal dialog
- Fields: name, max open, max close, debounce
- Get Config button (reads from device)
- Upload Settings button (sends to device)

**Test criteria**:
- [ ] Dialog opens from device tab
- [ ] Get Config populates fields
- [ ] Upload Settings sends correct commands

**Commit message**: `feat(VOG): add configuration dialog`

---

### Task 14: GUI Mode
**Goal**: Full GUI mode with async bridge

**File**: `vog_core/modes/gui_mode.py`

**Test criteria**:
- [ ] GUI launches correctly
- [ ] Device connections reflected in GUI
- [ ] Recording state synced between system and GUI
- [ ] Commands from master logger update GUI

**Commit message**: `feat(VOG): add GUI mode`

---

### Task 15: VMC Integration Layer
**Goal**: Runtime and view factories for stub supervisor

**Files**: `vog/runtime.py`, `vog/view.py`

**Test criteria**:
- [ ] Module works with stub supervisor pattern
- [ ] Consistent with DRT module integration

**Commit message**: `feat(VOG): add VMC integration layer`

---

### Task 16: Build Integration
**Goal**: Include VOG module in PyInstaller build

**File to modify**: `rpi_logger.spec`

**Changes**:
```python
# Add 'VOG' to module lists (lines 63 and 148)
for module_name in ['Audio', 'Cameras', 'DRT', 'EyeTracker', 'GPS', 'Notes', 'VOG', 'stub (codex)']:
```

**Test criteria**:
- [ ] `pyinstaller rpi_logger.spec` completes without error
- [ ] `dist/rpi-logger/rpi_logger/modules/VOG/` exists with all files
- [ ] Built executable discovers VOG module
- [ ] VOG module launches from built executable

**Commit message**: `build(VOG): add module to PyInstaller spec`

---

### Task 17: Integration Testing
**Goal**: End-to-end testing with master logger

**Test criteria**:
- [ ] VOG appears in master logger module list
- [ ] VOG window opens when enabled
- [ ] Session start/stop propagates to VOG
- [ ] Trial recording creates correct CSV files
- [ ] Multiple VOG devices work simultaneously

**Commit message**: `test(VOG): add integration tests`

---

### Task 18: Documentation
**Goal**: Update documentation

**Test criteria**:
- [ ] README updated with VOG module info
- [ ] Code has appropriate docstrings
- [ ] config.txt options documented

**Commit message**: `docs(VOG): add module documentation`

---

## Task Dependencies

```
Task 1 (Scaffolding)
    ↓
Task 2 (Constants)
    ↓
Task 3 (Config Loader)
    ↓
Task 4 (Handler) ←──────────────────┐
    ↓                               │
Task 5 (System)                     │
    ↓                               │
Task 6 (Command Handler)            │
    ↓                               │
Task 7 (Simple Mode)                │
    ↓                               │
Task 8 (Entry Point)                │
    ↓                               │
Task 9 (Hardware Validation) ───────┘
    ↓
Task 10 (GUI - Device Tab)
    ↓
Task 11 (GUI - Main Window)
    ↓
Task 12 (GUI - Plotter)
    ↓
Task 13 (GUI - Config Dialog)
    ↓
Task 14 (GUI Mode)
    ↓
Task 15 (VMC Integration)
    ↓
Task 16 (Build Integration)
    ↓
Task 17 (Integration Testing)
    ↓
Task 18 (Documentation)
```

---

## Quick Reference

### sVOG Device Info
- **VID**: 0x16C0
- **PID**: 0x0483
- **Baud**: 9600

### Key Files from RS_Logger (Reference)
- Protocol: `RS_Logger/RSLogger/hardware_io/sVOG_HI/sVOG_HIController.py`
- UI: `RS_Logger/RSLogger/user_interface/sVOG_UI/`

### Key Files from RPi_Logger (Reference)
- DRT Handler: `RPi_Logger/rpi_logger/modules/DRT/drt_core/drt_handler.py`
- DRT System: `RPi_Logger/rpi_logger/modules/DRT/drt_core/drt_system.py`
- Base System: `RPi_Logger/rpi_logger/modules/base/base_system.py`
- USB Monitor: `RPi_Logger/rpi_logger/modules/base/usb_serial_manager.py`

### CSV Output Format
```
Device ID, Label, Unix time in UTC, Milliseconds Since Record, Trial Number, Shutter Open, Shutter Closed
sVOG_dev_ttyACM0, baseline, 1701539987, 1234, 1, 1500, 1500
```

### File Naming Pattern
```
{session_dir}/VOG/{timestamp}_VOG_trial{N:03d}_VOG_{port}.csv
```

---

## Phase 2: Universal VOG Support (wVOG Integration)

The following tasks extend the VOG module to support both sVOG (wired) and wVOG (wireless) devices.

### Architecture Overview

The universal VOG module uses a protocol abstraction layer:

```
┌─────────────────────────────────────────────────────────────┐
│                     VOGSystem                                │
│  (Device management, recording control, session handling)   │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                   VOGHandler (Base)                          │
│  (Common interface: send_command, parse_response, log_data) │
└─────────────────────────────────────────────────────────────┘
                   ╱                    ╲
                  ╱                      ╲
                 ▼                        ▼
┌─────────────────────────┐    ┌─────────────────────────┐
│     SVOGHandler         │    │     WVOGHandler         │
│  - USB Serial direct    │    │  - XBee 802.15.4        │
│  - >cmd|val<< format    │    │  - cmd>val format       │
│  - Single lens          │    │  - Dual lens (A/B/X)    │
│  - 6-field data         │    │  - 10-field data        │
└─────────────────────────┘    │  - Battery monitoring   │
                               │  - Network discovery    │
                               └─────────────────────────┘
```

### Protocol Comparison

| Feature | sVOG | wVOG |
|---------|------|------|
| **Connection** | USB Serial direct | USB Serial or XBee 802.15.4 |
| **Baud Rate** | 9600 | 57600 |
| **Command Format** | `>cmd\|val<<` | `cmd` or `cmd>val` |
| **Response Format** | `keyword\|value` | `keyword>value` |
| **Lens Control** | Single | Dual (A, B, or X=both) |
| **Battery** | N/A | Monitored (percent) |
| **Data Fields** | 6 | 7 |
| **Device Discovery** | USB VID/PID | USB VID/PID or XBee ND |

### wVOG Command Protocol (Verified from Hardware 2025-12-02)

```python
WVOG_COMMANDS = {
    # Experiment control
    'exp_start': 'exp>1',
    'exp_stop': 'exp>0',
    'trial_start': 'trl>1',
    'trial_stop': 'trl>0',

    # Lens control (a=left, b=right, x=both)
    # Value: 1=clear/open, 0=opaque/closed
    'lens_open_a': 'a>1',
    'lens_close_a': 'a>0',
    'lens_open_b': 'b>1',
    'lens_close_b': 'b>0',
    'lens_open_x': 'x>1',   # Both lenses
    'lens_close_x': 'x>0',  # Both lenses

    # Configuration
    'get_config': 'cfg',                    # Returns full config
    'set_config': 'set>{key},{value}',      # Update single config value

    # Status
    'get_battery': 'bat',
    'get_rtc': 'rtc',
    'set_rtc': 'rtc>{Y},{M},{D},{dow},{H},{M},{S},{ss}',
}
```

### wVOG Response Format (Verified from Hardware)

| Command | Response | Example |
|---------|----------|---------|
| `cfg` | `cfg>key:val,key:val,...` | `cfg>clr:100,cls:1500,dbc:20,srt:1,opn:1500,dta:0,drk:0,typ:cycle` |
| `bat` | `bty>percent` | `bty>85` |
| `rtc` | `rtc>Y,M,D,dow,H,M,S,ss` | `rtc>2025,12,2,1,14,30,0,0` |
| `exp>1` | `exp>1` | Experiment started |
| `exp>0` | `exp>0` | Experiment stopped |
| `trl>1` | `trl>1` | Trial started |
| `trl>0` | `trl>0`, `end`, `dta>...` | Trial stopped, data returned |
| `x>1` | `stm>1` | Shutter opened (stimulus on) |
| `x>0` | `stm>0` | Shutter closed (stimulus off) |

### wVOG Configuration Keys

| Key | Description | Default |
|-----|-------------|---------|
| `clr` | Clear/open opacity (0-100) | 100 |
| `cls` | Close time in ms | 1500 |
| `dbc` | Debounce time in ms | 20 |
| `srt` | Start state (0=opaque, 1=clear) | 1 |
| `opn` | Open time in ms | 1500 |
| `dta` | Data mode | 0 |
| `drk` | Dark/opaque opacity (0-100) | 0 |
| `typ` | Experiment type (cycle, peek, eblind, direct) | cycle |

### wVOG Data Format (on trial stop)

```
dta>trial_num,shutter_open,shutter_closed,total_ms,lens(X/A/B),battery_pct,device_unix_time
```

**Example:**
```
dta>1,1999,1500,3499,X,85,1733150423
```

### wVOG CSV Header

```
Device ID, Label, Unix time in UTC, Milliseconds Since Record, Trial Number, Shutter Open, Shutter Closed, Total, Lens, Battery Percent
```

### wVOG Firmware Data Header (for MMC storage)

From firmware: `'Device ID,Label,Unix time in UTC,Trial Number,Shutter Open,Shutter Closed,Shutter Total,Transition 0 1 or X,Battery SOC,Device Unix time in UTC\n'`

---

### Task 19: Protocol Abstraction Layer
**Goal**: Create base protocol class and device-specific implementations

**Files to create**:
```
vog_core/protocols/
├── __init__.py
├── base_protocol.py      # Abstract base class
├── svog_protocol.py      # sVOG implementation
└── wvog_protocol.py      # wVOG implementation
```

**base_protocol.py contents**:
```python
"""Abstract base protocol for VOG devices."""
from abc import ABC, abstractmethod
from typing import Dict, Optional, Tuple
from dataclasses import dataclass

@dataclass
class VOGDataPacket:
    """Universal data packet from VOG device."""
    device_id: str
    trial_number: int
    shutter_open: int        # ms shutter was open/clear
    shutter_closed: int      # ms shutter was closed/opaque
    shutter_total: int = 0   # Total ms (wVOG only)
    lens: str = 'X'          # Which lens: 'A', 'B', or 'X' (both) - wVOG only
    battery_percent: int = 0 # Battery SOC - wVOG only
    device_unix_time: int = 0  # Device's RTC timestamp - wVOG only

class BaseVOGProtocol(ABC):
    """Abstract base class for VOG device protocols."""

    @property
    @abstractmethod
    def device_type(self) -> str:
        """Return device type identifier ('svog' or 'wvog')."""
        pass

    @property
    @abstractmethod
    def supports_dual_lens(self) -> bool:
        """Return True if device supports dual lens control."""
        pass

    @property
    @abstractmethod
    def supports_battery(self) -> bool:
        """Return True if device reports battery status."""
        pass

    @abstractmethod
    def format_command(self, command: str, value: Optional[str] = None) -> bytes:
        """Format a command for transmission to device."""
        pass

    @abstractmethod
    def parse_response(self, response: str) -> Tuple[str, str]:
        """Parse device response into (keyword, value) tuple."""
        pass

    @abstractmethod
    def parse_data(self, data_str: str, device_id: str) -> Optional[VOGDataPacket]:
        """Parse data string into VOGDataPacket."""
        pass

    @abstractmethod
    def get_csv_header(self) -> str:
        """Return CSV header for this device type."""
        pass

    @abstractmethod
    def format_csv_row(self, packet: VOGDataPacket, label: str, unix_time: float, ms_since_record: int) -> str:
        """Format data packet as CSV row."""
        pass
```

**Test criteria**:
- [ ] `BaseVOGProtocol` defines all required abstract methods
- [ ] `SVOGProtocol` correctly implements `>cmd|val<<` format
- [ ] `WVOGProtocol` correctly implements `cmd>val` format
- [ ] Both protocols can parse their respective data formats
- [ ] `VOGDataPacket` works for both device types

**Commit message**: `feat(VOG): add protocol abstraction layer for universal device support`

---

### Task 20: Update Constants for Universal Support
**Goal**: Extend constants.py with wVOG protocol and unified device detection

**File**: `vog_core/constants.py`

**Changes**:
```python
# Add device type constants
DEVICE_TYPE_SVOG = 'svog'
DEVICE_TYPE_WVOG = 'wvog'
DEVICE_TYPE_WVOG_DONGLE = 'wvog_dongle'

# USB device identifiers
DEVICE_IDS = {
    DEVICE_TYPE_SVOG: {'vid': 0x16C0, 'pid': 0x0483, 'baud': 9600},
    DEVICE_TYPE_WVOG: {'vid': 0xf057, 'pid': 0x08AE, 'baud': 57600},
    DEVICE_TYPE_WVOG_DONGLE: {'vid': 0x0403, 'pid': 0x6015, 'baud': 57600},
}

# Add WVOG_COMMANDS dict (see Protocol Comparison section above)

# Add wVOG response keywords
WVOG_RESPONSE_KEYWORDS = [
    'deviceVer',
    'configName',
    'configMaxOpen',
    'configMaxClose',
    'configDebounce',
    'configClickMode',
    'configButtonControl',
    'battery',
    'stm',
    'data',
    'ND',  # Node discovery response
]

# Extended CSV header for wVOG
WVOG_CSV_HEADER = "Device ID, Label, Unix time in UTC, Milliseconds Since Record, Trial Number, Lens A Open, Lens A Closed, Lens B Open, Lens B Closed, Battery Voltage, Battery Percent, RSSI"
```

**Test criteria**:
- [ ] All device VID/PIDs defined correctly
- [ ] `WVOG_COMMANDS` matches RS_Logger protocol
- [ ] CSV headers appropriate for each device type

**Commit message**: `feat(VOG): extend constants for wVOG support`

---

### Task 21: wVOG Handler Implementation
**Goal**: Handler for wireless VOG devices via XBee

**File**: `vog_core/wvog_handler.py`

**Key functionality**:
- XBee communication via dongle serial port
- Network discovery (find wVOG devices on XBee network)
- Dual lens control (A, B, X commands)
- Battery status monitoring
- Extended data parsing (10 fields)
- RSSI tracking for signal quality

**Class structure**:
```python
class WVOGHandler:
    """Handler for wireless VOG devices."""

    def __init__(self, dongle_port: str, device_address: str, protocol: WVOGProtocol):
        self.dongle_port = dongle_port
        self.device_address = device_address
        self.protocol = protocol
        self._battery_voltage = 0.0
        self._battery_percent = 0
        self._rssi = 0

    async def discover_devices(self) -> List[str]:
        """Discover wVOG devices on XBee network."""
        pass

    async def send_command(self, command: str, value: str = None) -> None:
        """Send command to specific device address."""
        pass

    async def peek_open(self, lens: str = 'X') -> None:
        """Open shutter (lens: 'A', 'B', or 'X' for both)."""
        pass

    async def peek_close(self, lens: str = 'X') -> None:
        """Close shutter (lens: 'A', 'B', or 'X' for both)."""
        pass

    @property
    def battery_status(self) -> Tuple[float, int]:
        """Return (voltage, percent) tuple."""
        return (self._battery_voltage, self._battery_percent)
```

**Test criteria**:
- [ ] `WVOGHandler` instantiates without error
- [ ] Commands formatted correctly for wVOG protocol
- [ ] Dual lens commands (A, B, X) work correctly
- [ ] Battery status parsed from responses
- [ ] Extended data (10 fields) parsed correctly

**Commit message**: `feat(VOG): add wVOG handler for wireless device support`

---

### Task 22: XBee Network Discovery Module
**Goal**: Discover and manage wVOG devices on XBee 802.15.4 network

**File**: `vog_core/xbee_discovery.py`

**Key functionality**:
- Detect XBee dongle (FTDI USB-UART)
- Send ND (Node Discovery) command
- Parse discovery responses
- Track device addresses and names
- Handle network join/leave events

**Class structure**:
```python
class XBeeDiscovery:
    """XBee network discovery for wVOG devices."""

    def __init__(self, dongle_device: USBSerialDevice):
        self.dongle = dongle_device
        self._devices: Dict[str, XBeeNode] = {}

    async def start_discovery(self, timeout: float = 10.0) -> List[XBeeNode]:
        """Run network discovery and return found devices."""
        pass

    async def get_device_by_address(self, address: str) -> Optional[XBeeNode]:
        """Get device info by XBee address."""
        pass

    def on_device_found(self, callback: Callable[[XBeeNode], None]) -> None:
        """Register callback for device discovery events."""
        pass

@dataclass
class XBeeNode:
    """Information about a discovered XBee device."""
    address: str           # 16-bit network address
    serial_high: str       # Serial number high
    serial_low: str        # Serial number low
    node_id: str           # Human-readable identifier
    rssi: int              # Signal strength
    device_type: str       # 'wvog' or 'unknown'
```

**Test criteria**:
- [ ] XBee dongle detected by VID/PID
- [ ] ND command sent correctly
- [ ] Discovery responses parsed into XBeeNode objects
- [ ] Multiple devices tracked correctly
- [ ] Callback system works for device events

**Commit message**: `feat(VOG): add XBee network discovery module`

---

### Task 23: Update VOG System for Universal Support
**Goal**: Modify VOGSystem to handle both sVOG and wVOG devices

**File**: `vog_core/vog_system.py`

**Changes**:
- Add multi-device-type USB monitoring
- Create appropriate handler based on detected device type
- Support XBee dongle + network discovery for wVOG
- Unified interface for recording control

**Key modifications**:
```python
class VOGSystem(BaseSystem):
    """Universal VOG system supporting sVOG and wVOG devices."""

    def __init__(self, ...):
        # Monitor for both device types
        self._svog_monitor = USBDeviceMonitor(
            vid=DEVICE_IDS[DEVICE_TYPE_SVOG]['vid'],
            pid=DEVICE_IDS[DEVICE_TYPE_SVOG]['pid'],
            ...
        )
        self._wvog_monitor = USBDeviceMonitor(
            vid=DEVICE_IDS[DEVICE_TYPE_WVOG_DONGLE]['vid'],
            pid=DEVICE_IDS[DEVICE_TYPE_WVOG_DONGLE]['pid'],
            ...
        )
        self._xbee_discovery: Optional[XBeeDiscovery] = None

    async def _on_svog_connected(self, device: USBSerialDevice) -> None:
        """Handle sVOG device connection."""
        handler = SVOGHandler(device, SVOGProtocol())
        self._handlers[device.port] = handler

    async def _on_dongle_connected(self, device: USBSerialDevice) -> None:
        """Handle XBee dongle connection - start wVOG discovery."""
        self._xbee_discovery = XBeeDiscovery(device)
        devices = await self._xbee_discovery.start_discovery()
        for node in devices:
            handler = WVOGHandler(device.port, node.address, WVOGProtocol())
            self._handlers[f"wvog_{node.address}"] = handler

    def get_device_type(self, port: str) -> str:
        """Return device type for given port."""
        handler = self._handlers.get(port)
        if handler:
            return handler.protocol.device_type
        return 'unknown'
```

**Test criteria**:
- [ ] System monitors for both sVOG and wVOG dongle
- [ ] Correct handler created based on device type
- [ ] XBee discovery initiated when dongle connects
- [ ] wVOG devices added as handlers with network addresses
- [ ] Recording commands sent to all device types

**Commit message**: `feat(VOG): update system for universal sVOG/wVOG support`

---

### Task 24: Update GUI for Dual Lens Control **Status: COMPLETE**
**Goal**: Extend GUI to support wVOG dual lens controls and battery display

**Files**:
- `vog_core/interfaces/gui/tkinter_gui.py`
- `vog_core/interfaces/gui/vog_plotter.py`

**Changes to tkinter_gui.py**:
```python
class VOGDeviceTab:
    """Device tab that adapts to device type."""

    def _build_ui(self):
        # ... existing code ...

        # Add lens control frame (wVOG only)
        if self._is_wvog():
            self._build_dual_lens_controls()
            self._build_battery_display()

    def _build_dual_lens_controls(self):
        """Build A/B/X lens control buttons for wVOG."""
        lens_frame = ttk.LabelFrame(self._control_frame, text="Lens Control")

        # Lens A controls
        ttk.Button(lens_frame, text="Open A",
                   command=lambda: self._peek_open('A')).pack(side=tk.LEFT)
        ttk.Button(lens_frame, text="Close A",
                   command=lambda: self._peek_close('A')).pack(side=tk.LEFT)

        # Lens B controls
        ttk.Button(lens_frame, text="Open B",
                   command=lambda: self._peek_open('B')).pack(side=tk.LEFT)
        ttk.Button(lens_frame, text="Close B",
                   command=lambda: self._peek_close('B')).pack(side=tk.LEFT)

        # Both lenses
        ttk.Button(lens_frame, text="Open Both",
                   command=lambda: self._peek_open('X')).pack(side=tk.LEFT)
        ttk.Button(lens_frame, text="Close Both",
                   command=lambda: self._peek_close('X')).pack(side=tk.LEFT)

    def _build_battery_display(self):
        """Build battery status display for wVOG."""
        batt_frame = ttk.Frame(self._status_frame)
        self._batt_label = ttk.Label(batt_frame, text="Battery: ---%")
        self._batt_label.pack(side=tk.LEFT)
        self._rssi_label = ttk.Label(batt_frame, text="Signal: ---")
        self._rssi_label.pack(side=tk.LEFT, padx=10)

    def update_battery_status(self, voltage: float, percent: int, rssi: int):
        """Update battery and signal displays."""
        self._batt_label.config(text=f"Battery: {percent}% ({voltage:.1f}V)")
        self._rssi_label.config(text=f"Signal: {rssi} dBm")
```

**Changes to vog_plotter.py**:
```python
class VOGPlotter:
    """Updated plotter supporting dual lens visualization."""

    def __init__(self, parent_frame, dual_lens: bool = False):
        self._dual_lens = dual_lens
        if dual_lens:
            self._setup_dual_lens_plot()
        else:
            self._setup_single_lens_plot()

    def _setup_dual_lens_plot(self):
        """Create two-row plot for A and B lenses."""
        self._ax_lens_a = self._fig.add_subplot(211)
        self._ax_lens_b = self._fig.add_subplot(212)
        # ... configure axes ...

    def update_dual_lens(self, port: str, lens_a_open: bool, lens_b_open: bool):
        """Update dual lens state."""
        pass
```

**Test criteria**:
- [ ] Device tab adapts UI based on device type
- [ ] Dual lens buttons appear for wVOG only
- [ ] Battery/signal display updates correctly
- [ ] Plotter shows dual lens state for wVOG
- [ ] Single lens mode still works for sVOG

**Commit message**: `feat(VOG): add dual lens GUI controls for wVOG`

---

### Task 25: Update Config Dialog for wVOG **Status: COMPLETE**
**Goal**: Extend config dialog with wVOG-specific options

**File**: `vog_core/interfaces/gui/config_window.py`

**Changes**:
- Add device type indicator
- Show battery status (wVOG only)
- Show XBee network info (wVOG only)
- Add signal strength indicator

**Test criteria**:
- [ ] Config dialog shows device type
- [ ] wVOG-specific fields displayed appropriately
- [ ] Battery status shown for wVOG
- [ ] XBee address/network info displayed

**Commit message**: `feat(VOG): extend config dialog for wVOG`

---

### Task 26: Update Config Loader for Multi-Device **Status: COMPLETE**
**Goal**: Update config.txt and loader for universal support

**File changes**:
- `config.txt` - Add wVOG settings
- `vog_core/config/config_loader.py` - Parse new settings

**New config.txt entries**:
```ini
# sVOG settings
svog_vid = 0x16C0
svog_pid = 0x0483
svog_baud = 9600

# wVOG settings
wvog_vid = 0xf057
wvog_pid = 0x08AE
wvog_baud = 57600

# wVOG Dongle (XBee host) settings
dongle_vid = 0x0403
dongle_pid = 0x6015
dongle_baud = 57600

# XBee discovery
xbee_discovery_timeout = 10
xbee_retry_count = 3
```

**Test criteria**:
- [ ] Config loader parses all device settings
- [ ] Default values work when config missing
- [ ] XBee settings loaded correctly

**Commit message**: `feat(VOG): update config for multi-device support`

---

### Task 27: Extended CSV Logging
**Goal**: Update CSV logging to handle both data formats

**File**: `vog_core/vog_handler.py` (and `wvog_handler.py`)

**Changes**:
- Use protocol's `get_csv_header()` for file headers
- Use protocol's `format_csv_row()` for data rows
- Support 6-field (sVOG) and 10-field (wVOG) formats
- Maintain backward compatibility

**Test criteria**:
- [ ] sVOG CSV format unchanged (backward compatible)
- [ ] wVOG CSV includes extended fields
- [ ] Both formats parseable by analysis tools

**Commit message**: `feat(VOG): extend CSV logging for wVOG data format`

---

### Task 28: wVOG Hardware Validation
**Goal**: Verify communication with real wVOG hardware

**Test criteria** (requires hardware):
- [ ] XBee dongle detected when plugged in
- [ ] Network discovery finds wVOG devices
- [ ] Commands sent/received via XBee
- [ ] Dual lens control works
- [ ] Battery status reported
- [ ] Data logging includes all 10 fields
- [ ] Signal strength (RSSI) tracked

**Commit message**: `test(VOG): verify wVOG hardware communication`

---

### Task 29: Universal Integration Testing
**Goal**: Test mixed sVOG and wVOG operation

**Test criteria**:
- [ ] Both device types work simultaneously
- [ ] Recording starts/stops on all devices
- [ ] Correct CSV format for each device
- [ ] GUI displays all devices correctly
- [ ] Device type identified in UI
- [ ] Hot-plug works for both types

**Commit message**: `test(VOG): verify universal sVOG/wVOG operation`

---

### Task 30: Universal Documentation Update
**Goal**: Document universal VOG module

**Files**:
- `README.md` - Update VOG section
- `VOG_PORT_PLAN.md` - Mark completed
- Inline docstrings

**Documentation should cover**:
- Supported device types
- Configuration options per device
- GUI differences between modes
- CSV format differences
- XBee network setup
- Troubleshooting

**Test criteria**:
- [ ] README documents both device types
- [ ] Config options documented
- [ ] Protocol differences explained
- [ ] XBee setup instructions included

**Commit message**: `docs(VOG): document universal sVOG/wVOG support`

---

## Phase 2 Task Dependencies

```
Task 19 (Protocol Abstraction)
    ↓
Task 20 (Constants Update)
    ↓
Task 21 (wVOG Handler) ←── Task 22 (XBee Discovery)
    ↓                           ↓
Task 23 (System Update) ←───────┘
    ↓
Task 24 (GUI Dual Lens)
    ↓
Task 25 (Config Dialog Update)
    ↓
Task 26 (Config Loader Update)
    ↓
Task 27 (Extended CSV)
    ↓
Task 28 (wVOG Hardware Validation) ─── requires hardware
    ↓
Task 29 (Universal Integration Testing)
    ↓
Task 30 (Documentation Update)
```

---

## Phase 2 Progress Tracking

| Task | Status | Date |
|------|--------|------|
| 19. Protocol Abstraction | COMPLETE | 2025-12-02 |
| 20. Constants Update | COMPLETE (merged into 19-21) | 2025-12-02 |
| 21. wVOG Handler | COMPLETE (merged into VOGHandler) | 2025-12-02 |
| 22. XBee Discovery | DEFERRED (USB mode works) | |
| 23. System Update | COMPLETE | 2025-12-02 |
| 24. GUI Dual Lens | COMPLETE | 2025-12-02 |
| 25. Config Dialog Update | COMPLETE | 2025-12-02 |
| 26. Config Loader Update | COMPLETE | 2025-12-02 |
| 27. Extended CSV | COMPLETE (merged into 19-21) | 2025-12-02 |
| 28. wVOG Hardware Validation | COMPLETE (USB mode) | 2025-12-02 |
| 29. Universal Integration Testing | PENDING | |
| 30. Documentation Update | PENDING | |

---

## Reference: RS_Logger wVOG Implementation

Key files from RS_Logger for wVOG reference:

```
RS_Logger/RSLogger/hardware_io/wVOG_HI/
├── wVOG_HIController.py    # Main controller
├── wVOG_HIModel.py         # Data model
└── xbee_discovery.py       # Network discovery

RS_Logger/RSLogger/user_interface/wVOG_UI/
├── wVOG_UIController.py    # UI controller
├── wVOG_UIModel.py         # UI model
└── wVOG_UIView.py          # UI view

RS_Logger/RSLogger/Firmware/wVOG_FW/
├── main.py                 # Entry point
└── wVOG/
    ├── controller.py       # Main controller with command parsing (KEY FILE)
    ├── experiments.py      # Experiment logic
    ├── lenses.py           # Lens control
    ├── battery.py          # Battery monitoring
    ├── config.py           # Configuration management
    ├── mmc.py              # MMC storage
    ├── xb.py               # XBee communication
    └── timers.py           # Timer utilities
```

### Key wVOG Protocol Details (Verified from Hardware 2025-12-02)

1. **Command format**: Short commands like `cfg`, `bat`, `exp>1`, `trl>0`, `x>1`
2. **Response format**: `keyword>value` with `>` separator
3. **Data packet**: 7 comma-separated values: `trial,open,closed,total,lens,batt,time`
4. **Battery monitoring**: `bat` returns `bty>percent` (just percentage, not voltage)
5. **Lens control**: Single-letter commands: `a>1`, `b>0`, `x>1` (1=clear, 0=opaque)
6. **Config format**: `cfg>key:val,key:val,...` with colon separators

### wVOG Modes

The wVOG can operate in two modes:
1. **USB Mode**: Direct USB serial connection (VID 0xf057, PID 0x08AE) at 57600 baud
2. **XBee Mode**: Wireless via XBee 802.15.4 through FTDI dongle (VID 0x0403, PID 0x6015)

Both modes use the same command protocol.

### Device Address Format (XBee Mode)

wVOG devices use 64-bit XBee addresses:
- High 32 bits: `0x0013A200` (Digi standard)
- Low 32 bits: Device-specific serial number
- Displayed as: `0013A200:XXXXXXXX`

---

## Hardware Testing Log

### wVOG USB Mode Test (2025-12-02)

**Device**: wVOG in USB mode
**Port**: /dev/ttyACM0
**VID/PID**: f057:08ae (MicroPython Pyboard Virtual Comm Port)
**Baud**: 57600

**Test Results**:
```
cfg             -> cfg>clr:100,cls:1500,dbc:20,srt:1,opn:1500,dta:0,drk:0,typ:cycle
bat             -> bty>0
rtc             -> rtc>2015,1,1,4,0,0,0,0
x>1             -> stm>1
x>0             -> stm>0
exp>1           -> exp>1
trl>1           -> trl>1, stm>1, stm>0
trl>0           -> stm>1, trl>0, stm>0, end, dta>1,1999,1500,3499,X,0,1420070423
exp>0           -> exp>0
```

**Notes**:
- Battery shows 0% when on USB power (expected - no battery connected)
- RTC was at factory default (2015-01-01), needs to be set on first use
- Data format confirmed: `dta>trial,open_ms,closed_ms,total_ms,lens,batt%,unix_time`

---

## Phase 2 Implementation Summary (2025-12-02)

### What Was Implemented

**Protocol Abstraction Layer** (`vog_core/protocols/`):
- `base_protocol.py`: Abstract base class with `VOGDataPacket`, `VOGResponse`, `ResponseType` enum
- `svog_protocol.py`: sVOG implementation (`>cmd|val<<` format)
- `wvog_protocol.py`: wVOG implementation (`cmd>val` format)

**VOGHandler Updates** (`vog_core/vog_handler.py`):
- Auto-detects protocol based on device VID/PID from `device.config`
- Uses protocol abstraction for command formatting and response parsing
- Supports dual lens control (`peek_open('a'/'b'/'x')`)
- Extended CSV output for wVOG with Total, Lens, Battery columns

**VOGSystem Updates** (`vog_core/vog_system.py`):
- Monitors **both** sVOG and wVOG VID/PIDs simultaneously
- Creates multiple USBDeviceMonitor instances
- Auto-selects correct protocol for each connected device
- New method: `get_handlers_by_type('svog'/'wvog')`

**Config Updates** (`config.txt`):
- Documents both device VID/PIDs
- System monitors both regardless of which is specified

### Files Created/Modified
```
vog_core/protocols/
├── __init__.py           # NEW
├── base_protocol.py      # NEW
├── svog_protocol.py      # NEW
└── wvog_protocol.py      # NEW

vog_core/vog_handler.py   # MODIFIED - protocol abstraction
vog_core/vog_system.py    # MODIFIED - multi-device support
config.txt                # MODIFIED - both VID/PIDs documented
```

### Hardware Validation Results

**Test**: Full experiment with wVOG in USB mode
**Result**: SUCCESS

```
Device detected: /dev/ttyACM0 (WVOG)
Config received: cfg>clr:100,cls:1500,dbc:20,srt:1,opn:1500,dta:0,drk:0,typ:cycle
Experiment started: exp>1
Trial 1 data: dta>1,1500,1500,3000,X,0,1420070400
Trial 2 data: dta>2,1500,499,1999,X,0,1420070403
CSV files created: 2 (with extended wVOG format)
```

### Remaining Work

1. **XBee Mode**: wVOG XBee wireless communication (Tasks 22-24 from original plan)
2. **GUI Updates**: wVOG-specific UI elements (lens selector, battery display)
3. **sVOG Validation**: Test with actual sVOG hardware when available

---

## Next Steps After Reboot

### XBee Dongle Setup

An XBee dongle was connected:
- **VID/PID**: 0403:6015 (FTDI Bridge)
- **Port**: /dev/ttyUSB0
- **Issue**: Permission denied - user not in dialout group

**To fix after reboot** (user should already be in dialout group after reboot if added):
```bash
# Check if user is in dialout group
groups

# If not, add user to dialout group (requires logout/login)
sudo usermod -a -G dialout $USER

# Or temporary fix:
sudo chmod 666 /dev/ttyUSB0
```

### XBee Test Commands

Once permissions are fixed, test the XBee dongle:
```python
import serial
import time

ser = serial.Serial('/dev/ttyUSB0', 9600, timeout=2)
time.sleep(0.5)

# Enter AT command mode
ser.write(b'+++')
time.sleep(1.5)
response = ser.read(10)  # Should get 'OK'

# Get XBee info
ser.write(b'ATVR\r')  # Firmware version
ser.write(b'ATSH\r')  # Serial high
ser.write(b'ATSL\r')  # Serial low
ser.write(b'ATID\r')  # PAN ID
ser.write(b'ATCH\r')  # Channel

# Node discovery (finds wVOG devices)
ser.write(b'ATND\r')
time.sleep(6)  # ND takes up to 5 seconds

# Exit command mode
ser.write(b'ATCN\r')
ser.close()
```

### XBee Implementation Tasks

To implement XBee support for wVOG:

1. **Create XBee Discovery Module** (`vog_core/xbee_discovery.py`):
   - Detect FTDI dongle (VID 0x0403, PID 0x6015)
   - Enter AT command mode
   - Run node discovery (ATND)
   - Parse discovered device addresses

2. **Create XBee Handler** (`vog_core/xbee_handler.py`):
   - Manage XBee serial connection
   - Send commands to specific device addresses
   - Parse responses with source address

3. **Update VOGSystem**:
   - Add XBee dongle monitoring
   - Create WVOGHandler instances for discovered devices
   - Handle XBee vs USB mode transparently

### Current Implementation Status

**Phase 1 (sVOG)**: COMPLETE (except hardware validation)
**Phase 2 (wVOG USB)**: COMPLETE and VALIDATED
**Phase 2 (wVOG XBee)**: NOT STARTED - waiting for permissions

### Files Implemented in Previous Session

```
vog_core/protocols/
├── __init__.py           # Protocol exports
├── base_protocol.py      # BaseVOGProtocol, VOGDataPacket, VOGResponse
├── svog_protocol.py      # SVOGProtocol (>cmd|val<< format)
└── wvog_protocol.py      # WVOGProtocol (cmd>val format)

vog_core/vog_handler.py   # Updated with protocol abstraction
vog_core/vog_system.py    # Updated with multi-device monitoring
config.txt                # Updated with both VID/PIDs
```

---

## Session 2025-12-02 (Continued) - GUI and Config Updates

### Tasks Completed This Session

1. **Task 24: GUI Dual Lens Control** - COMPLETE
   - `VOGDeviceTab` now accepts `device_type` parameter
   - sVOG: Simple peek open/close buttons
   - wVOG: Lens selector (A/B/X) + open/close + quick "Open Both"/"Close Both"
   - wVOG: Battery display at top of controls
   - wVOG: Extended results showing Total, Lens
   - Tab text now shows device type: "ttyACM0 (WVOG)"

2. **Task 25: Config Dialog for wVOG** - COMPLETE
   - `VOGConfigWindow` adapts UI based on device type
   - sVOG: Config name, max open/close, debounce, click mode, button control
   - wVOG: Battery status, experiment type, open/close times, debounce, clear/dark opacity, start state
   - Both: Device version display, Refresh/Apply/Close buttons

3. **Task 26: Config Loader Update** - COMPLETE
   - Added device constants: `SVOG_VID/PID/BAUD`, `WVOG_VID/PID/BAUD`, `WVOG_DONGLE_VID/PID`
   - Extended `DEFAULTS` with all device-specific settings
   - Added XBee discovery settings
   - Updated `config.txt` with comprehensive device documentation

### Files Modified This Session

```
vog_core/interfaces/gui/tkinter_gui.py   # Dual lens controls, battery display
vog_core/interfaces/gui/config_window.py # wVOG config UI
vog_core/config/config_loader.py         # Multi-device defaults
config.txt                               # Full device documentation
VOG_PORT_PLAN.md                         # Progress tracking
```

### Remaining Work

1. **Task 29: Universal Integration Testing** - Test sVOG and wVOG together
2. **Task 30: Documentation Update** - README and docstrings
3. **XBee Wireless Mode** - Task 22 deferred (USB mode works)

---

## Hardware Testing Session (2025-12-02)

### Test Environment
- **wVOG**: Connected on `/dev/ttyACM0` (VID f057:08ae)
- **XBee Dongle**: Connected on `/dev/ttyUSB0` (VID 0403:6015) - No devices on network

### Test Results

1. **wVOG USB Communication** - PASSED
   - Config retrieval: `cfg>clr:100,cls:1500,dbc:20,srt:1,opn:1500,dta:0,drk:0,typ:cycle`
   - Battery: `bty>0` (0% when on USB power - expected)
   - Lens open/close: `stm>1`/`stm>0`

2. **VOGSystem Device Detection** - PASSED
   - System monitors for both sVOG and wVOG simultaneously
   - wVOG correctly identified as `device_type='wvog'`
   - `supports_dual_lens=True`, `supports_battery=True`

3. **Full Experiment with Trial Data** - PASSED
   - Experiment start/stop
   - Trial 1: 2499ms open, 1500ms closed, 3999ms total
   - Trial 2: 2499ms open, 1500ms closed, 3999ms total
   - CSV files created with extended wVOG format

4. **XBee Dongle** - NOT RESPONDING
   - Tried baud rates: 9600, 57600, 115200, 38400, 19200
   - No AT command response - dongle may be in API mode
   - XBee wireless mode deferred to future work

5. **GUI Class Tests** - PASSED
   - sVOG tab: Simple peek controls (no lens selector, no battery)
   - wVOG tab: Lens selector, battery display, extended results
   - Config dialog adapts fields based on device type

### CSV Output Format (wVOG)
```csv
Device ID, Label, Unix time in UTC, Milliseconds Since Record, Trial Number, Shutter Open, Shutter Closed, Total, Lens, Battery Percent
WVOG_dev_ttyACM0, 1, 1764714461, 4545, 1, 2499, 1500, 3999, X, 0
```

---

## sVOG Protocol Verification (2025-12-02)

Verified sVOG protocol against RS_Logger firmware:
- `RS_Logger/RSLogger/Firmware/sVOG_FW/embedded`
- `RS_Logger/RSLogger/hardware_io/sVOG_HI/sVOG_HIController.py`

### Key Corrections Made

1. **Baud Rate**: Changed from 9600 to **115200** (firmware default)

2. **Command Format**: `>COMMAND|VALUE<<\n`
   - Example: `>do_expStart|<<\n`
   - Set commands: `>set_configMaxOpen|1500<<\n`

3. **Response Format**: `keyword|value` or simple `keyword`
   - Pipe-delimited: `stm|1`, `data|5,3000,1500`, `configName|NHTSA`
   - Simple acks: `expStart`, `expStop`, `trialStart`, `Click`

4. **Added Commands (26 total)**:
   - Device info: `get_deviceName`, `get_deviceDate`
   - Runtime state: `get_trialCounter`, `get_openElapsed`, `get_closedElapsed`
   - Factory reset: `do_factoryReset`
   - Combined config query: `get_config`

5. **Added Response Types**:
   - Simple acknowledgments: `expStart`, `expStop`, `trialStart`
   - Button events: `btn|1`, `btn|0`, `Click`
   - Device info: `deviceName`, `deviceDate`
   - Runtime state: `trialCounter`, `openElapsed`, `closedElapsed`

### Protocol Test Results
```
Command formatting:
   exp_start: b'>do_expStart|<<\n'
   set_max_open(1500): b'>set_configMaxOpen|1500<<\n'

Response parsing:
   stm|1        -> type=stimulus   data={'state': 1}
   expStart     -> type=experiment
   btn|1        -> type=stimulus   data={'state': 1, 'button_event': True}
   data|5,3000,1500 -> type=data

Data packet: Trial=5, Open=3000, Closed=1500
```

---

## RS_Logger Compatibility Verification (2025-12-02)

Compared our implementation against RS_Logger (the working reference):
- `RS_Logger/RSLogger/hardware_io/sVOG_HI/sVOG_HIController.py`
- `RS_Logger/RSLogger/hardware_io/usb_connect.py`

### Baud Rate Note
RS_Logger uses **921600** baud in `usb_connect.py`, but the sVOG firmware uses **115200**.
This appears to be a discrepancy in RS_Logger. We use **115200** to match the actual firmware.

### Command Format Verification
All 15 tested commands match RS_Logger exactly:
- Experiment: `>do_expStart|<<`, `>do_expStop|<<`
- Trial: `>do_trialStart|<<`, `>do_trialStop|<<`
- Peek: `>do_peekOpen|<<`, `>do_peekClose|<<`
- Config get: `>get_deviceVer|<<`, `>get_configName|<<`, etc.
- Config set: `>set_configName|VALUE<<`, `>set_configMaxOpen|VALUE<<`, etc.

### Response Parsing Verification
All RS_Logger keywords parsed correctly:
- `deviceVer|2.2` → version
- `configName|NHTSA` → config
- `stm|1`, `stm|0` → stimulus
- `data|5,3000,1500` → data
- `expStart`, `expStop`, `trialStart`, `Click` → simple acknowledgments

### Timing Behavior
- **Config commands**: Sent rapidly without delay (matches RS_Logger)
- **Response handling**: Async read loop with tight polling

---

## Post-Implementation Cleanup (2025-12-02)

After completing the port, cleanup work was done to address architectural issues. See `VOG_CLEANUP_STATUS.md` for full details.

### Summary of Cleanup Completed

| Phase | Description | Status |
|-------|-------------|--------|
| 1 | Centralize constants (VID/PID/baud) | ✅ COMPLETE |
| 2 | Consolidate duplicate systems (VOGSystem + VOGModuleRuntime) | ✅ COMPLETE |
| 4 | Fix encapsulation violations (handler._config access) | ✅ COMPLETE |
| 6 | Extract logging to VOGDataLogger | ✅ COMPLETE |
| 3 | Consolidate config dialogs | PENDING |
| 5 | Consolidate trial number logic | PENDING |
| 7 | Eliminate device type branching | PENDING |
| 8 | Simplify callback chain | OPTIONAL |

### Key Files Added During Cleanup

- `vog_core/data_logger.py` - Extracted CSV logging (170 lines)
- `vog_core/constants.py` - Added `determine_device_type_from_vid_pid()` utility

### Architectural Decisions

1. **Shared utility for device type detection** - `determine_device_type_from_vid_pid(vid, pid)` in constants.py
2. **Session control added to VOGSystem** - `start_session()`, `stop_session()`, `start_trial()`, `stop_trial()`
3. **VOGModuleRuntime kept separate** - Different lifecycle from VOGSystem (VMC vs standalone)
4. **VOGDataLogger extracted** - Cleaner separation of logging concerns

### For Future Work

Read `VOG_CLEANUP_STATUS.md` first - it contains:
- All import paths
- Class responsibilities
- Remaining cleanup phases
- Code locations for key functionality
