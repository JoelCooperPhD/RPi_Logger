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
    ├── view.py                    # View factory (686 lines)
    ├── plotter.py                 # VMC plotter wrapper
    └── config_dialog.py           # Config dialog - DUPLICATE, sVOG only (216 lines) - TO DELETE
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

### 🔲 Phase 3: Consolidate Config Dialogs (PENDING - NEXT)
**Problem:** Two config dialog implementations:
- `vog_core/interfaces/gui/config_window.py` (379 lines) - supports sVOG AND wVOG
- `vog/config_dialog.py` (216 lines) - sVOG only, uses callback pattern

**Decision:** Keep `VOGConfigWindow` (more complete, supports both device types)

**Implementation Plan:**
1. Update `vog/view.py` to use `VOGConfigWindow` instead of `VOGConfigDialog`
2. Delete `vog/config_dialog.py`

**Files to Modify:**
- `vog/view.py` - change import and usage at lines 35-37, 466-478
- `vog/config_dialog.py` - DELETE

---

### 🔲 Phase 5: Consolidate Trial Number Logic (PENDING)
**Problem:** Three sources of trial numbers with confusing fallback:
- `VOGSystem.active_trial_number`
- `VOGHandler._trial_number`
- `packet.trial_number` from device

The `_determine_trial_number()` method in vog_handler.py has complex fallback logic.

**Solution:**
1. System owns trial number, handler reads it
2. Remove `VOGHandler._trial_number` internal counter
3. Simplify `_determine_trial_number()` to just read from system
4. If system not available (standalone mode), use packet.trial_number

**Files to Modify:**
- `vog_core/vog_handler.py:446-464` - simplify `_determine_trial_number()`
- `vog_core/vog_system.py:43` - ensure trial number is always set

---

### 🔲 Phase 7: Eliminate Device Type Branching (PENDING)
**Problem:** ~15 occurrences of:
```python
if self.device_type == 'wvog':
    # wvog-specific
else:
    # svog-specific
```

Scattered across: vog_handler.py, tkinter_gui.py, config_window.py, data_logger.py

**Solution:**
1. Add polymorphic methods to BaseVOGProtocol
2. Subclasses (SVOGProtocol, WVOGProtocol) implement device-specific behavior
3. Replace branching with protocol method calls

Example transformation:
```python
# Before
if self.device_type == 'wvog':
    data['shutter_total'] = packet.shutter_total

# After
data.update(self.protocol.get_extended_data(packet))
```

**Files to Modify:**
- `vog_core/protocols/base_protocol.py` - add abstract methods
- `vog_core/protocols/svog_protocol.py` - implement methods
- `vog_core/protocols/wvog_protocol.py` - implement methods
- `vog_core/vog_handler.py` - use protocol methods
- `vog_core/data_logger.py` - use protocol methods
- `vog_core/interfaces/gui/tkinter_gui.py` - use protocol methods
- `vog_core/interfaces/gui/config_window.py` - use protocol methods

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

### Trial Number Logic (needs consolidation in Phase 5)
- `vog_handler.py:446-464` - `_determine_trial_number()`
- `vog_system.py:43` - `active_trial_number` property

### Config Dialog Usage
- `vog_core/interfaces/gui/tkinter_gui.py:227-228` - uses VOGConfigWindow
- `vog/view.py:466-478` - uses VOGConfigDialog (to be changed in Phase 3)

### Data Logging
- `vog_core/data_logger.py:1-170` - VOGDataLogger class
- `vog_handler.py:390-420` - uses VOGDataLogger

---

## Recommended Execution Order

1. ~~Phase 1: Constants~~ ✅
2. ~~Phase 4: Encapsulation~~ ✅
3. ~~Phase 6: Extract Logger~~ ✅
4. ~~Phase 2: Consolidate Systems~~ ✅
5. **Phase 3: Config Dialogs** ← NEXT
6. Phase 5: Trial Numbers
7. Phase 7: Device Branching
8. Phase 8: Callbacks (optional)

---

## Files Created During Cleanup
- `vog_core/data_logger.py` - NEW (Phase 6)

## Files To Be Deleted
- `vog/config_dialog.py` - After Phase 3

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
3. **VOGHandler God Class** - Partially addressed (extracted logging)
4. **Device Type Branching ~15 places** - Pending Phase 7
5. **Config Dialog Duplicated** - Pending Phase 3
6. **Trial Number Logic Messy** - Pending Phase 5
7. **GUI Encapsulation Violations** - ✅ FIXED
8. **7-Level Callback Chain** - Pending Phase 8 (optional)

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
