# VOG (Occlusion Glasses) Port Plan: RS_Logger → RPi_Logger

## Overview

Port sVOG (Serial Visual Occlusion Glasses) functionality from RS_Logger to RPi_Logger as an autonomous module.

**Scope**: sVOG only (Arduino-based, USB serial)
**Firmware**: No changes - must work with existing field devices
**Independence**: VOG operates autonomously, separate from DRT

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
| 2. Constants | NOT STARTED | |
| 3. Config Loader | NOT STARTED | |
| 4. VOG Handler | NOT STARTED | |
| 5. VOG System | NOT STARTED | |
| 6. Command Handler | NOT STARTED | |
| 7. Simple Mode | NOT STARTED | |
| 8. Entry Point | NOT STARTED | |
| 9. Hardware Validation | NOT STARTED | |
| 10. GUI - Device Tab | NOT STARTED | |
| 11. GUI - Main Window | NOT STARTED | |
| 12. GUI - Plotter | NOT STARTED | |
| 13. GUI - Config Dialog | NOT STARTED | |
| 14. GUI Mode | NOT STARTED | |
| 15. VMC Integration | NOT STARTED | |
| 16. Build Integration | NOT STARTED | |
| 17. Integration Testing | NOT STARTED | |
| 18. Documentation | NOT STARTED | |

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
