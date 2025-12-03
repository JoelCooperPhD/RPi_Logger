# VOG Module Cleanup - Status & Context

**Last Updated:** 2025-12-02
**Purpose:** Track cleanup progress for the VOG module. This file contains all context needed to continue work.

---

## Quick Start for Future Sessions

```bash
# Navigate to project
cd /home/joel/Development/RPi_Logger

# Test imports work
python3 -c "from rpi_logger.modules.VOG.vog_core.vog_handler import VOGHandler; from rpi_logger.modules.VOG.vog_core.data_logger import VOGDataLogger; from rpi_logger.modules.VOG.vog_core.constants import determine_device_type_from_vid_pid; print('OK')"

# Run VOG standalone (requires device)
python3 -m rpi_logger.modules.VOG.main_vog --mode gui

# Check git status
git status
```

---

## Project Location
`/home/joel/Development/RPi_Logger/rpi_logger/modules/VOG/`

## What is VOG?
Visual Occlusion Glasses module - controls shutter glasses for vision research experiments. Supports two device types:
- **sVOG**: Wired Arduino-based device (VID: 0x16C0, PID: 0x0483, 115200 baud)
- **wVOG**: Wireless MicroPython Pyboard device (VID: 0xF057, PID: 0x08AE, 57600 baud)

---

## Module Structure Overview

```
rpi_logger/modules/VOG/
├── main_vog.py                    # Entry point (189 lines)
├── config.txt                     # Configuration file
├── vog_core/                      # Core business logic
│   ├── __init__.py
│   ├── constants.py               # ✅ CENTRALIZED CONSTANTS + utility functions
│   ├── data_logger.py             # ✅ Extracted CSV logging (170 lines)
│   ├── vog_system.py              # Main orchestrator (600 lines, added session control)
│   ├── vog_handler.py             # Device handler (464 lines)
│   ├── protocols/
│   │   ├── __init__.py            # Exports SVOGProtocol, WVOGProtocol, BaseVOGProtocol
│   │   ├── base_protocol.py       # Abstract protocol interface + VOGDataPacket
│   │   ├── svog_protocol.py       # sVOG implementation (>cmd|val<< format)
│   │   ├── wvog_protocol.py       # wVOG implementation (cmd>val format)
│   │   └── __init__.py
│   ├── config/
│   │   └── config_loader.py       # Config file loading
│   ├── commands/
│   │   └── handler.py             # Command handling
│   ├── modes/
│   │   ├── gui_mode.py            # GUI mode launcher
│   │   └── simple_mode.py         # Headless/simple mode
│   └── interfaces/gui/
│       ├── tkinter_gui.py         # Main GUI + VOGDeviceTab (412 lines)
│       ├── config_window.py       # Config dialog - CANONICAL (379 lines)
│       └── vog_plotter.py         # Real-time plotting
└── vog/                           # VMC integration layer
    ├── __init__.py
    ├── runtime.py                 # ✅ REFACTORED - VMC wrapper (570 lines)
    ├── view.py                    # ✅ REFACTORED - View factory (uses VOGConfigWindow)
    └── plotter.py                 # VMC plotter wrapper
```

---

## Key Import Paths

### Core Classes
```python
# VOGSystem - main orchestrator
from rpi_logger.modules.VOG.vog_core.vog_system import VOGSystem

# VOGHandler - per-device serial handler
from rpi_logger.modules.VOG.vog_core.vog_handler import VOGHandler

# VOGDataLogger - CSV logging
from rpi_logger.modules.VOG.vog_core.data_logger import VOGDataLogger

# Protocols
from rpi_logger.modules.VOG.vog_core.protocols import SVOGProtocol, WVOGProtocol, BaseVOGProtocol
from rpi_logger.modules.VOG.vog_core.protocols.base_protocol import VOGDataPacket, VOGResponse

# Constants
from rpi_logger.modules.VOG.vog_core.constants import (
    SVOG_VID, SVOG_PID, SVOG_BAUD,
    WVOG_VID, WVOG_PID, WVOG_BAUD,
    WVOG_DONGLE_VID, WVOG_DONGLE_PID,
    COMMAND_DELAY, CONFIG_RESPONSE_WAIT,
    determine_device_type_from_vid_pid,
)

# Config loading
from rpi_logger.modules.VOG.vog_core.config.config_loader import load_config_file
```

### GUI Classes
```python
# Main GUI
from rpi_logger.modules.VOG.vog_core.interfaces.gui.tkinter_gui import VOGTkinterGUI, VOGDeviceTab

# Config dialog (canonical version supporting both sVOG and wVOG)
from rpi_logger.modules.VOG.vog_core.interfaces.gui.config_window import VOGConfigWindow

# Plotter
from rpi_logger.modules.VOG.vog_core.interfaces.gui.vog_plotter import VOGPlotter
```

### VMC Integration (requires vmc module)
```python
# VMC runtime
from rpi_logger.modules.VOG.vog.runtime import VOGModuleRuntime

# VMC view
from rpi_logger.modules.VOG.vog.view import VOGView, VOGTkinterGUI as VMCVOGTkinterGUI
```

### Base Classes (from rpi_logger.modules.base)
```python
from rpi_logger.modules.base import (
    BaseSystem,
    RecordingStateMixin,
    USBDeviceConfig,
    USBDeviceMonitor,
    USBSerialDevice,
)
from rpi_logger.modules.base.storage_utils import ensure_module_data_dir
```

---

## Class Responsibilities

### VOGSystem (vog_core/vog_system.py)
- Inherits from `BaseSystem`, `RecordingStateMixin`
- Manages USB monitors for sVOG and wVOG devices
- Creates `VOGHandler` instances on device connection
- Coordinates recording across all devices
- **New methods (Phase 2):**
  - `start_session()` / `stop_session()` - experiment control (exp>1/exp>0)
  - `start_trial()` / `stop_trial()` - trial control (trl>1/trl>0)
  - `get_config(port)` - request device config
  - `set_output_dir(path)` - update handler output directories
  - `session_active` property - check if session is running

### VOGHandler (vog_core/vog_handler.py)
- Per-device serial communication
- Uses protocol abstraction for command formatting
- Manages data callback for events
- Creates `VOGDataLogger` for CSV output
- **Key methods:**
  - `start_experiment()` / `stop_experiment()`
  - `start_trial()` / `stop_trial()`
  - `peek_open(lens)` / `peek_close(lens)`
  - `get_device_config()`
  - `get_config()` - returns copy of config dict

### VOGDataLogger (vog_core/data_logger.py)
- Extracted from VOGHandler (Phase 6)
- Handles CSV file creation and logging
- Uses protocol's `format_csv_row()` for device-specific output
- **Key methods:**
  - `start_recording()` / `stop_recording()`
  - `log_trial_data(packet, trial_number, label)`

### VOGModuleRuntime (vog/runtime.py)
- VMC-compatible runtime
- Manages USB monitors (parallel to VOGSystem)
- Handles model observation and view binding
- Dispatches commands from VMC
- **Key differences from VOGSystem:**
  - Observes VMC model changes (`model.subscribe()`)
  - Notifies VMC view of events
  - Separate session/recording state tracking

---

## Cleanup Phases & Status

### ✅ Phase 1: Extract Shared Constants (COMPLETE)
**Files Modified:**
- `vog_core/constants.py` - Added device VID/PID/baud constants, timing constants
- All files updated to import from constants

**Constants centralized:**
```python
SVOG_VID = 0x16C0
SVOG_PID = 0x0483
SVOG_BAUD = 115200
WVOG_VID = 0xF057
WVOG_PID = 0x08AE
WVOG_BAUD = 57600
WVOG_DONGLE_VID = 0x0403
WVOG_DONGLE_PID = 0x6015
COMMAND_DELAY = 0.05
CONFIG_RESPONSE_WAIT = 0.5

def determine_device_type_from_vid_pid(vid, pid) -> str:
    """Shared utility function for device type detection."""
```

---

### ✅ Phase 4: Fix Encapsulation Violations (COMPLETE)
**Problem:** `config_window.py` accessed `handler._config` directly

**Solution:**
- Added `get_config()` public method to VOGHandler (returns copy of config dict)
- Updated `config_window.py` to use `handler.get_config()`
- Replaced magic number `0.5` with `CONFIG_RESPONSE_WAIT` constant

---

### ✅ Phase 6: Extract Logging from VOGHandler (COMPLETE)
**Problem:** VOGHandler._log_trial_data() was 73 lines doing file I/O, CSV formatting, event dispatching

**Solution:**
- Created `vog_core/data_logger.py` with `VOGDataLogger` class (170 lines)
- VOGHandler creates `self._data_logger` instance
- VOGHandler calls `self._data_logger.log_trial_data(packet, trial_number, label)`
- VOGHandler reduced from 519 to 464 lines

---

### ✅ Phase 2: Consolidate Duplicate Systems (COMPLETE)
**Problem:** Two classes doing the same thing:
- `VOGSystem` in `vog_core/vog_system.py` (415 lines)
- `VOGModuleRuntime` in `vog/runtime.py` (496 lines)

**Solution Implemented:**
1. **Added session control to VOGSystem** - `start_session()`, `stop_session()`, `start_trial()`, `stop_trial()`
2. **Added shared utility function** - `determine_device_type_from_vid_pid()` in constants.py
3. **Added `get_config()` method to VOGSystem**
4. **Added `set_output_dir()` method to VOGSystem**
5. **Added `session_active` property to VOGSystem**
6. **Cleaned up VOGModuleRuntime** - Better organization, uses shared utility

**Key Insight:** Full delegation wasn't practical because:
- VOGSystem inherits from BaseSystem (standalone lifecycle with `run()`)
- VOGModuleRuntime implements VMC ModuleRuntime (VMC lifecycle)
- USB monitoring callbacks differ (view notifications vs mode callbacks)

**Remaining Duplication (acceptable):**
- USB monitor setup (~30 lines each) - different callbacks needed
- Session/trial control (~60 lines each) - nearly identical but different state variables

---

### ✅ Phase 3: Consolidate Config Dialogs (COMPLETE)
**Problem:** Two config dialog implementations:
- `vog_core/interfaces/gui/config_window.py` (379 lines) - supports sVOG AND wVOG
- `vog/config_dialog.py` (216 lines) - sVOG only, uses callback pattern

**Solution:**
1. Updated `vog/view.py` to import and use `VOGConfigWindow` from `vog_core.interfaces.gui.config_window`
2. Removed config response handling from `VOGTkinterGUI.on_device_data()` (VOGConfigWindow loads config directly)
3. Deleted `vog/config_dialog.py`

**Key changes to view.py:**
- Import changed from `.config_dialog.VOGConfigDialog` to `..vog_core.interfaces.gui.config_window.VOGConfigWindow`
- `_on_configure_clicked()` now creates `VOGConfigWindow(root, port, self.system, device_type)` directly
- Removed `self._config_dialog` instance variable (dialog is modal, self-contained)
- Removed `_dispatch_config_action()` callback (not needed)
- Removed config/version response handling in `on_device_data()` (VOGConfigWindow handles internally)

---

### ✅ Phase 5: Consolidate Trial Number Logic (COMPLETE)
**Problem:** Three sources of trial numbers with confusing fallback:
- `VOGSystem.active_trial_number`
- `VOGHandler._trial_number`
- `packet.trial_number` from device

**Solution:**
1. `VOGSystem` is now the single source of truth for trial numbers
2. `VOGSystem.start_session()` resets `active_trial_number` to 0
3. `VOGSystem.start_trial()` increments `active_trial_number` before calling handlers
4. Removed `VOGHandler._trial_number` internal counter entirely
5. Simplified `_determine_trial_number()` with clear priority:
   - Primary: `system.active_trial_number`
   - Fallback: `model.trial_number` (VMC context)
   - Final: `packet.trial_number` (standalone/device-reported)

**Files Modified:**
- `vog_core/vog_system.py`:
  - `start_session()` now resets `active_trial_number = 0`
  - `start_trial()` now increments `active_trial_number += 1` with rollback on failure
- `vog_core/vog_handler.py`:
  - Removed `self._trial_number` instance variable
  - Removed trial number reset from `start_experiment()`
  - Removed trial number increment from `start_trial()`
  - Simplified `_determine_trial_number()` with clearer logic and documentation

---

### ✅ Phase 7: Eliminate Device Type Branching (COMPLETE)
**Problem:** ~17 occurrences of device type branching scattered across handler, logger, and GUI.

**Solution:**
Added polymorphic methods to protocol classes to eliminate branching in core logic:

1. **New abstract methods in `BaseVOGProtocol`:**
   - `get_config_commands()` - list of commands to retrieve config
   - `format_set_config(param, value)` - format set config operation
   - `update_config_from_response(response, config)` - update config dict from response
   - `get_extended_packet_data(packet)` - get device-specific packet fields
   - `format_csv_row(packet, label, unix_time, ms_since_record)` - format CSV row

2. **Implemented in `SVOGProtocol` and `WVOGProtocol`**

3. **Replaced branching in:**
   - `vog_handler.py:get_device_config()` - uses `protocol.get_config_commands()`
   - `vog_handler.py:set_config_value()` - uses `protocol.format_set_config()`
   - `vog_handler.py:_handle_response()` - uses `protocol.update_config_from_response()`
   - `vog_handler.py:_process_data_response()` - uses `protocol.get_extended_packet_data()`
   - `data_logger.py:log_trial_data()` - uses `protocol.format_csv_row()`
   - `data_logger.py:_dispatch_logged_event()` - uses `protocol.get_extended_packet_data()`

**Remaining branching (acceptable - 11 occurrences):**
- Protocol instantiation (runtime.py, vog_system.py) - necessary to select correct class
- UI differences (view.py, tkinter_gui.py, config_window.py) - legitimate UI variations
- Handler filtering by type (vog_system.py) - utility method

**Reduction:** 17 → 11 occurrences (6 eliminated from core logic)

---

### 🔲 Phase 8: Simplify Callback Chain (OPTIONAL/FUTURE)
**Problem:** 7 levels of callbacks from handler to plotter:
```
Handler._dispatch_data_event()
  → VOGSystem._on_device_data()
    → GUIMode.on_device_data()
      → async_bridge.call_in_gui()
        → window.after()
          → VOGTkinterGUI.on_device_data()
            → VOGDeviceTab.update_data()
              → VOGPlotter.update_trial_data()
```

**Status:** Defer until core cleanup complete. High risk, lower priority.

---

## Key Code Locations

### Device Detection Logic
- `vog_core/constants.py:100-112` - `determine_device_type_from_vid_pid()` (SHARED)
- `vog_system.py:168-179` - `_determine_device_type()` (uses shared function)
- `vog/runtime.py:32-45` - `_determine_device_type()` (uses shared function)
- `vog_handler.py:62-76` - `_detect_protocol()` (could also use shared function)

### Session/Trial Control
- `vog_system.py:338-493` - `start_session()`, `stop_session()`, `start_trial()`, `stop_trial()`
- `vog/runtime.py:328-470` - `_start_session()`, `_stop_session()`, `_start_recording()`, `_stop_recording()`

### Trial Number Logic (consolidated in Phase 5)
- `vog_system.py:44` - `active_trial_number` (single source of truth)
- `vog_system.py:340-361` - `start_session()` resets trial number
- `vog_system.py:420-474` - `start_trial()` increments trial number
- `vog_handler.py:447-473` - `_determine_trial_number()` reads from system

### Config Dialog Usage
- `vog_core/interfaces/gui/tkinter_gui.py:227-228` - uses VOGConfigWindow
- `vog/view.py:464-482` - uses VOGConfigWindow (consolidated in Phase 3)

### Data Logging
- `vog_core/data_logger.py:1-170` - VOGDataLogger class
- `vog_handler.py:390-420` - uses VOGDataLogger

---

## Recommended Execution Order

1. ~~Phase 1: Constants~~ ✅
2. ~~Phase 4: Encapsulation~~ ✅
3. ~~Phase 6: Extract Logger~~ ✅
4. ~~Phase 2: Consolidate Systems~~ ✅
5. ~~Phase 3: Config Dialogs~~ ✅
6. ~~Phase 5: Trial Numbers~~ ✅
7. ~~Phase 7: Device Branching~~ ✅
8. Phase 8: Callbacks (optional/future)

---

## Files Created During Cleanup
- `vog_core/data_logger.py` - NEW (Phase 6)

## Files Deleted During Cleanup
- `vog/config_dialog.py` - DELETED (Phase 3)

---

## Testing Notes

### Import Test
```bash
python3 -c "from rpi_logger.modules.VOG.vog_core.vog_handler import VOGHandler; from rpi_logger.modules.VOG.vog_core.data_logger import VOGDataLogger; from rpi_logger.modules.VOG.vog_core.constants import determine_device_type_from_vid_pid; print('OK')"
```

### Full Module Test (requires hardware)
```bash
python3 -m rpi_logger.modules.VOG.main_vog --mode gui
```

### VMC Runtime Test (requires vmc module)
```bash
cd /home/joel/Development/RPi_Logger/rpi_logger/modules/VOG
python3 -m py_compile vog/runtime.py && echo "Syntax OK"
```

---

## Original Issues Identified

1. **CRITICAL: Duplicate Architecture** - VOGSystem vs VOGModuleRuntime - ✅ ADDRESSED (shared utilities, consistent APIs)
2. **CRITICAL: Device Constants Duplicated 4x** - ✅ FIXED
3. **VOGHandler God Class** - ✅ ADDRESSED (extracted logging, polymorphic protocol methods)
4. **Device Type Branching ~15 places** - ✅ FIXED (Phase 7) - reduced to 11, core logic uses polymorphism
5. **Config Dialog Duplicated** - ✅ FIXED (Phase 3)
6. **Trial Number Logic Messy** - ✅ FIXED (Phase 5)
7. **GUI Encapsulation Violations** - ✅ FIXED
8. **7-Level Callback Chain** - Pending Phase 8 (optional/future)

---

## Related Documentation

- `VOG_PORT_PLAN.md` - Original port plan from RS_Logger, includes protocol details
- `rpi_logger/modules/DRT/` - Reference implementation for similar module patterns
- `rpi_logger/modules/base/` - Base classes (BaseSystem, USBDeviceMonitor, etc.)

---

## Git History (Recent Relevant Commits)

```bash
git log --oneline -10 -- rpi_logger/modules/VOG/
```

Latest commit: `3da3c19` - refactor(VOG): consolidate constants and add session control (Phase 1, 2, 4, 6)
