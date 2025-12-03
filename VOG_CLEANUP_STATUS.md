# VOG Module Cleanup - Status & Context

**Last Updated:** 2025-12-02
**Purpose:** Track cleanup progress for the VOG module. This file contains all context needed to continue work.

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
│   │   ├── base_protocol.py       # Abstract protocol interface
│   │   ├── svog_protocol.py       # sVOG implementation
│   │   ├── wvog_protocol.py       # wVOG implementation
│   │   └── __init__.py
│   ├── config/
│   │   └── config_loader.py       # Config file loading
│   ├── commands/
│   │   └── handler.py             # Command handling
│   ├── modes/
│   │   ├── gui_mode.py
│   │   └── simple_mode.py
│   └── interfaces/gui/
│       ├── tkinter_gui.py         # Main GUI (412 lines)
│       ├── config_window.py       # Config dialog - CANONICAL (379 lines)
│       └── vog_plotter.py         # Real-time plotting
└── vog/                           # VMC integration layer
    ├── runtime.py                 # ✅ REFACTORED - VMC wrapper (570 lines, was 496)
    ├── view.py                    # View factory (686 lines)
    ├── config_dialog.py           # Config dialog - DUPLICATE, sVOG only (216 lines)
    └── __init__.py
```

---

## Cleanup Phases & Status

### ✅ Phase 1: Extract Shared Constants (COMPLETE)
**Files Modified:**
- `vog_core/constants.py` - Added device VID/PID/baud constants, timing constants
- `vog_core/config/config_loader.py` - Now imports from constants
- `vog_core/vog_handler.py` - Now imports from constants
- `vog_core/vog_system.py` - Now imports from constants
- `vog_core/protocols/svog_protocol.py` - Now imports SVOG_BAUD
- `vog_core/protocols/wvog_protocol.py` - Now imports WVOG_BAUD
- `vog/runtime.py` - Now imports from constants
- `main_vog.py` - Now imports from constants

**Constants now centralized in `vog_core/constants.py`:**
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
- Updated `config_window.py` lines 232, 239 to use `handler.get_config()`
- Replaced magic number `0.5` with `CONFIG_RESPONSE_WAIT` constant

---

### ✅ Phase 6: Extract Logging from VOGHandler (COMPLETE)
**Problem:** VOGHandler._log_trial_data() was 73 lines doing file I/O, CSV formatting, event dispatching

**Solution:**
- Created `vog_core/data_logger.py` with `VOGDataLogger` class (170 lines)
- VOGHandler now creates `self._data_logger` instance
- VOGHandler calls `self._data_logger.log_trial_data(packet, trial_number, label)`
- VOGHandler reduced from 519 to 464 lines

**New file structure:**
```python
class VOGDataLogger:
    def __init__(self, output_dir, port, protocol, event_callback)
    def start_recording() -> None
    def stop_recording() -> None
    async def log_trial_data(packet, trial_number, label) -> Optional[Path]
```

---

### ✅ Phase 2: Consolidate Duplicate Systems (COMPLETE)
**Problem:** Two classes doing the same thing:
- `VOGSystem` in `vog_core/vog_system.py` (415 lines)
- `VOGModuleRuntime` in `vog/runtime.py` (496 lines)

Both managed: USB monitoring, device handlers, recording state, trial numbers.

**Solution Implemented:**
Rather than full delegation (which would require significant BaseSystem changes), we:

1. **Added session control to VOGSystem** - Now has `start_session()`, `stop_session()`, `start_trial()`, `stop_trial()` methods matching VOGModuleRuntime's granular control
2. **Added shared utility function** - `determine_device_type_from_vid_pid()` in constants.py used by both
3. **Added `get_config()` method to VOGSystem** - Matches runtime's config retrieval
4. **Added `set_output_dir()` method to VOGSystem** - For handler directory updates
5. **Added `session_active` property to VOGSystem** - Exposes session state
6. **Cleaned up VOGModuleRuntime** - Better organization, clear sections, improved docstrings
7. **Both classes now use shared `determine_device_type_from_vid_pid()`**

**Key Insight:** Full delegation wasn't practical because:
- VOGSystem inherits from BaseSystem (standalone lifecycle)
- VOGModuleRuntime implements VMC ModuleRuntime (VMC lifecycle)
- USB monitoring callbacks differ (view notifications vs mode callbacks)

**Remaining Duplication (acceptable):**
- USB monitor setup (~30 lines each) - different callbacks needed
- Session/trial control (~60 lines each) - nearly identical but different state variables
- These could be further unified with an intermediate helper class if desired

**Files Modified:**
- `vog_core/constants.py` - Added `determine_device_type_from_vid_pid()` function
- `vog_core/vog_system.py` - Added session control, get_config, set_output_dir, session_active
- `vog/runtime.py` - Refactored with better organization, uses shared utility

---

### 🔲 Phase 3: Consolidate Config Dialogs (PENDING)
**Problem:** Two config dialog implementations:
- `vog_core/interfaces/gui/config_window.py` (379 lines) - supports sVOG AND wVOG
- `vog/config_dialog.py` (216 lines) - sVOG only, uses callback pattern

**Decision:** Keep `VOGConfigWindow` (more complete, supports both device types)

**Implementation Plan:**
1. Update `vog/view.py` to use `VOGConfigWindow` instead of `VOGConfigDialog`
2. Delete `vog/config_dialog.py`

**Files to Modify:**
- `vog/view.py` - change import and usage
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
- `vog_core/vog_handler.py` - simplify trial number logic
- `vog_core/vog_system.py` - ensure trial number is always set

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
Import test command:
```bash
python3 -c "from rpi_logger.modules.VOG.vog_core.vog_handler import VOGHandler; from rpi_logger.modules.VOG.vog_core.data_logger import VOGDataLogger; from rpi_logger.modules.VOG.vog_core.constants import determine_device_type_from_vid_pid; print('OK')"
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
