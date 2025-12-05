# VOG Module Complete Refactor Plan

## Executive Summary

This document outlines a complete refactor of the VOG module to achieve a clean, logical, and maintainable codebase.

**Important Context:**
- The main logger (`rpi_logger/core/devices/`) handles ALL device discovery centrally
- Modules receive `assign_device(device_id, device_type, port, baudrate)` commands from the main logger
- The VOG module's local `ConnectionManager` and `XBeeManager` are **DEAD CODE** (legacy from before centralization)
- The DRT module is currently broken and should NOT be used as a reference

**Goals:**
1. Delete ~1,500 lines of dead/obsolete code (local scanning code)
2. Simplify `runtime.py` to receive devices via `assign_device` instead of local scanning
3. Keep protocol abstraction for cleaner separation
4. Split God classes into focused components
5. Clean up inconsistent type usage

**Current state:** ~7,461 lines across 20+ files with significant technical debt
**Target state:** ~3,500 lines across well-organized files with clear responsibilities

---

## Current Architecture (Correct)

```
┌──────────────────────────────────────────────────────────────────┐
│                    MAIN LOGGER (rpi_logger/core/)                 │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │ DeviceConnectionManager (core/devices/connection_manager.py)│ │
│  │   ├── USBScanner (core/devices/usb_scanner.py)              │ │
│  │   ├── XBeeManager (core/devices/xbee_manager.py)            │ │
│  │   └── device_registry.py (unified VID/PID registry)        │ │
│  └─────────────────────────────────────────────────────────────┘ │
│                              │                                    │
│              ┌───────────────┼───────────────┐                   │
│              ▼               ▼               ▼                   │
│     assign_device()   assign_device()   assign_device()          │
│              │               │               │                   │
└──────────────│───────────────│───────────────│───────────────────┘
               │               │               │
               ▼               ▼               ▼
        ┌──────────┐    ┌──────────┐    ┌──────────┐
        │ VOG      │    │ DRT      │    │ Other    │
        │ Module   │    │ Module   │    │ Modules  │
        └──────────┘    └──────────┘    └──────────┘
              │
              ▼
        VOGSystem.assign_device() creates VOGHandler
```

**Device Assignment Flow:**
1. Main logger's `DeviceConnectionManager` discovers device via `USBScanner` or `XBeeManager`
2. Main logger identifies device type from `device_registry.py` (unified VID/PID registry)
3. Main logger sends `assign_device` command to VOG module via command protocol
4. `VOGSystem.assign_device()` creates transport and handler for the device
5. When device disconnects, main logger sends `unassign_device`

**Dead Code in VOG Module:**
- `vog_core/connection_manager.py` - Local USB scanning (replaced by `core/devices/`)
- `vog_core/xbee_manager.py` - Local XBee management (replaced by `core/devices/`)
- `vog/runtime.py` uses local `ConnectionManager` - **NEEDS TO BE REFACTORED**

---

## Current Problems (Prioritized)

### Critical Issues (Must Fix)

| # | Problem | Impact | Files Affected | Lines to Remove |
|---|---------|--------|----------------|-----------------|
| 1 | Dead code: ConnectionManager | Confusing, never used | connection_manager.py | 540 |
| 2 | Dead code: XBeeManager | Confusing, never used | xbee_manager.py | 569 |
| 3 | Dead code: modes/ directory | Unused mode implementations | modes/*.py | 214 |
| 4 | God class: VOGHandler | Mixed concerns, hard to test | vog_handler.py | (refactor) |
| 5 | God class: view.py + tkinter_gui.py | UI/logic mixing | vog/view.py, tkinter_gui.py | (refactor) |

### Secondary Issues

| # | Problem | Impact |
|---|---------|--------|
| 6 | Device type inconsistency | Strings vs enums vs protocol.device_type |
| 7 | Constants duplicated | constants.py vs protocol class constants |
| 8 | TransportDeviceAdapter | Unnecessary adapter pattern |
| 9 | Complex trial number logic | Multiple fallback paths |
| 10 | Unclear threading model | Async mixed with thread callbacks |

---

## Files Inventory

### Files to DELETE (Dead Code)

| File | Lines | Reason |
|------|-------|--------|
| `vog_core/connection_manager.py` | 540 | USB scanning now in main logger |
| `vog_core/xbee_manager.py` | 569 | XBee management now in main logger |
| `vog_core/modes/gui_mode.py` | 85 | Unused - VOGSystem handles modes directly |
| `vog_core/modes/simple_mode.py` | 129 | Unused |
| `vog_core/modes/__init__.py` | 1 | Empty |
| `vog_core/transport_device_adapter.py` | 77 | Unnecessary adapter pattern |
| **Total** | **~1,401** | |

### Files to KEEP and REFACTOR

| File | Current Lines | Target Lines | Notes |
|------|---------------|--------------|-------|
| `main_vog.py` | 189 | 100 | Simplify entry point |
| `vog_core/vog_system.py` | 608 | 400 | Remove dead code paths |
| `vog_core/vog_handler.py` | 473 | 350 | Simplify, remove redundancy |
| `vog_core/protocols/base_protocol.py` | 211 | 150 | Clean interface |
| `vog_core/protocols/svog_protocol.py` | 304 | 250 | Keep, clean up |
| `vog_core/protocols/wvog_protocol.py` | 352 | 300 | Keep, clean up |
| `vog_core/transports/usb_transport.py` | 219 | 180 | Simplify |
| `vog_core/transports/xbee_transport.py` | 209 | 180 | Keep for wireless |
| `vog_core/data_logger.py` | 178 | 150 | Minor cleanup |
| `vog_core/interfaces/gui/tkinter_gui.py` | 323 | 250 | Focus on UI only |
| `vog_core/interfaces/gui/config_window.py` | 507 | 350 | Simplify |
| `vog/view.py` | 696 | 400 | Split into components |
| `vog/runtime.py` | 557 | 350 | Remove dead code |
| `vog/plotter.py` | 358 | 300 | Keep mostly as-is |

### Files to KEEP (Minimal Changes)

| File | Lines | Notes |
|------|-------|-------|
| `vog_core/constants.py` | 112 | Consolidate all constants here |
| `vog_core/device_types.py` | 155 | Keep, use consistently |
| `vog_core/transports/base_transport.py` | 94 | Good interface |
| `vog_core/utils/rtc.py` | 39 | Keep |
| `config.txt` | - | Config file |
| `README.md` | - | Documentation |

---

## Target Directory Structure

After refactor, keep the same basic structure but cleaner:

```
rpi_logger/modules/VOG/
├── __init__.py
├── main_vog.py                    # Simplified entry point (~100 lines)
├── config.txt
├── README.md
│
├── vog/                           # Runtime and view integration
│   ├── __init__.py
│   ├── runtime.py                 # VMC ModuleRuntime (~350 lines)
│   ├── view.py                    # VMC View factory (~200 lines)
│   └── plotter.py                 # Matplotlib plotter (~300 lines)
│
└── vog_core/                      # Core functionality
    ├── __init__.py
    ├── constants.py               # ALL constants consolidated (~150 lines)
    ├── device_types.py            # Device type enums (~100 lines)
    ├── vog_system.py              # System coordinator (~400 lines)
    ├── vog_handler.py             # Device handler (~350 lines)
    ├── data_logger.py             # CSV logging (~150 lines)
    │
    ├── protocols/                 # Protocol definitions
    │   ├── __init__.py
    │   ├── base_protocol.py       # Abstract protocol (~150 lines)
    │   ├── svog_protocol.py       # sVOG protocol (~250 lines)
    │   └── wvog_protocol.py       # wVOG protocol (~300 lines)
    │
    ├── transports/                # Transport layer
    │   ├── __init__.py
    │   ├── base_transport.py      # Abstract transport (~100 lines)
    │   ├── usb_transport.py       # USB/Serial transport (~180 lines)
    │   └── xbee_transport.py      # XBee wireless transport (~180 lines)
    │
    ├── gui/                       # GUI components (moved from interfaces/gui)
    │   ├── __init__.py
    │   ├── main_gui.py            # Main GUI controller (~250 lines)
    │   ├── device_tab.py          # Per-device tab widget (~150 lines)
    │   ├── config_dialog.py       # Configuration dialog (~300 lines)
    │   └── controls.py            # Lens control buttons (~100 lines)
    │
    └── utils/
        ├── __init__.py
        └── rtc.py                 # RTC sync utilities (~40 lines)

Deleted:
- vog_core/connection_manager.py   (DELETED - dead code)
- vog_core/xbee_manager.py         (DELETED - dead code)
- vog_core/transport_device_adapter.py (DELETED - unnecessary)
- vog_core/modes/                  (DELETED - unused)
- vog_core/commands/               (MERGED into vog_system.py)
- vog_core/config/                 (MERGED into constants.py)
- vog_core/interfaces/gui/         (MOVED to vog_core/gui/)
```

**Estimated total after refactor: ~3,500 lines** (down from 7,461)

---

## Implementation Phases

### Phase 1: Delete Dead Code

**Goal:** Remove ~1,400 lines of code that is never executed

**Steps:**

1. **Delete ConnectionManager** (`vog_core/connection_manager.py`)
   - 540 lines of USB scanning code
   - Main logger now handles this via `core/devices/`
   - VOG receives devices via `assign_device` command

2. **Delete XBeeManager** (`vog_core/xbee_manager.py`)
   - 569 lines of XBee dongle and network discovery
   - Main logger now handles this via `core/devices/xbee_manager.py`
   - Wireless devices come via `assign_device` with `is_wireless=True`

3. **Delete modes/ directory**
   - `gui_mode.py` (85 lines) - unused
   - `simple_mode.py` (129 lines) - unused
   - VOGSystem handles mode creation directly in `_create_mode_instance`
   - Update `_create_mode_instance` to remove mode imports

4. **Delete TransportDeviceAdapter** (`vog_core/transport_device_adapter.py`)
   - 77 lines of adapter pattern
   - Handler can use transport directly
   - Simplifies device assignment in VOGSystem

5. **Update imports**
   - Remove dead imports from `vog/runtime.py`
   - Remove dead imports from `vog_core/__init__.py`
   - Fix any broken references

**Verification:**
```bash
# After each deletion, verify module still loads
python3 -c "import rpi_logger.modules.VOG"

# Check for import errors
python3 -m py_compile rpi_logger/modules/VOG/vog_core/vog_system.py
python3 -m py_compile rpi_logger/modules/VOG/vog/runtime.py
```

---

### Phase 2: Clean Up VOGSystem

**Goal:** Simplify VOGSystem now that device scanning is removed

**Current Issues:**
- Still references modes that don't exist
- Has `_create_mode_instance` that creates non-existent modes
- Some dead code paths for wireless handling

**Changes:**

1. **Remove mode factory pattern**
   ```python
   # BEFORE (vog_system.py:216-227)
   def _create_mode_instance(self, mode_name: str) -> Any:
       if mode_name == "gui":
           from .modes.gui_mode import GUIMode
           return GUIMode(self, enable_commands=self.enable_gui_commands)
       ...

   # AFTER - Remove this method entirely
   # Mode handling is done by VOGModuleRuntime in vog/runtime.py
   ```

2. **Simplify wireless device path**
   ```python
   # BEFORE (vog_system.py:133-136)
   if is_wireless:
       self.logger.warning("Wireless device assignment not yet implemented")
       return False

   # AFTER - Implement or remove based on whether XBee is needed
   ```

3. **Clean up handler references**
   - Remove `mode_instance` callbacks if unused
   - Simplify `_on_device_data` callback chain

---

### Phase 3: Clean Up VOGHandler

**Goal:** Reduce complexity, focus on single responsibility

**Current Issues:**
- 473 lines mixing communication, parsing, logging, callbacks
- Complex trial number determination logic
- Mixed concerns

**Changes:**

1. **Simplify trial number determination**
   ```python
   # BEFORE (complex fallback chain in _determine_trial_number)
   # Tries: system.active_trial_number -> system.model.trial_number -> packet.trial_number

   # AFTER - Single source of truth
   def _determine_trial_number(self, packet: VOGDataPacket) -> int:
       """Get trial number from system (single source of truth)."""
       if self.system is not None:
           return self.system.active_trial_number or 1
       return packet.trial_number or 1
   ```

2. **Remove redundant device type handling**
   - Protocol already knows its device type
   - Don't store separately in handler

3. **Simplify callback chain**
   - Data flows: Device → Handler → System → Runtime → GUI
   - Each layer should do minimal transformation

---

### Phase 4: Reorganize GUI Components

**Goal:** Split God class (view.py + tkinter_gui.py = 1,019 lines) into focused components

**New Structure:**

```
vog_core/gui/
├── __init__.py           # Exports
├── main_gui.py           # Main GUI controller (from tkinter_gui.py)
├── device_tab.py         # Per-device tab widget (NEW)
├── config_dialog.py      # Config window (from config_window.py)
└── controls.py           # Lens controls (extracted from view.py)
```

**Move from `interfaces/gui/` to `gui/`**:
- `tkinter_gui.py` → `main_gui.py` (rename + simplify)
- `config_window.py` → `config_dialog.py` (rename + simplify)
- `vog_plotter.py` → stays in `vog/plotter.py`

**Split `vog/view.py` (696 lines)**:
- VMC view factory logic → `vog/view.py` (200 lines)
- Tab building logic → `gui/device_tab.py` (150 lines)
- Manual controls → `gui/controls.py` (100 lines)
- Plotter stays in `vog/plotter.py`

---

### Phase 5: Consolidate Constants

**Goal:** Single source of truth for all constants

**Merge into `vog_core/constants.py`:**

```python
# vog_core/constants.py - AFTER

"""VOG module constants - single source of truth."""

# =============================================================================
# Device Hardware
# =============================================================================

# sVOG (Arduino Teensy)
SVOG_VID = 0x16C0
SVOG_PID = 0x0483
SVOG_BAUD = 115200
SVOG_NAME = 'sVOG'

# wVOG (MicroPython Pyboard)
WVOG_VID = 0xF057
WVOG_PID = 0x08AE
WVOG_BAUD = 57600
WVOG_NAME = 'wVOG'

# XBee Coordinator (handled by main logger, but kept for reference)
XBEE_VID = 0x0403
XBEE_PID = 0x6015
XBEE_BAUD = 921600

# =============================================================================
# Protocol Commands - sVOG
# =============================================================================

SVOG_COMMANDS = {
    'experiment_start': '>exp|1<<',
    'experiment_stop': '>exp|0<<',
    'trial_start': '>trl|1<<',
    'trial_stop': '>trl|0<<',
    'peek_open': '>opn|1<<',
    'peek_close': '>opn|0<<',
    'get_config': '>cfg|?<<',
    'set_config': '>cfg|{key}|{val}<<',
}

# =============================================================================
# Protocol Commands - wVOG
# =============================================================================

WVOG_COMMANDS = {
    'experiment_start': 'exp>1',
    'experiment_stop': 'exp>0',
    'trial_start': 'trl>1',
    'trial_stop': 'trl>0',
    'peek_open': '{lens}>1',      # lens: a, b, or x
    'peek_close': '{lens}>0',
    'get_config': 'cfg>?',
    'set_config': 'cfg>{key}>{val}',
    'rtc_sync': 'rtc>{timestamp}',
}

# =============================================================================
# Timing
# =============================================================================

CONFIG_RESPONSE_WAIT = 0.5  # seconds to wait for config response
READ_TIMEOUT = 0.1          # seconds for serial read timeout
WRITE_TIMEOUT = 1.0         # seconds for serial write timeout

# =============================================================================
# CSV Output
# =============================================================================

SVOG_CSV_HEADER = [
    'Device ID', 'Label', 'Unix Time', 'MS Since Record',
    'Trial #', 'Shutter Open', 'Shutter Closed'
]

WVOG_CSV_HEADER = [
    'Device ID', 'Label', 'Unix Time', 'MS Since Record',
    'Trial #', 'Shutter Open', 'Shutter Closed',
    'Total', 'Lens', 'Battery Percent'
]
```

**Remove duplication from:**
- `protocols/svog_protocol.py` - use `SVOG_COMMANDS` from constants
- `protocols/wvog_protocol.py` - use `WVOG_COMMANDS` from constants

---

### Phase 6: Clean Up Transports

**Goal:** Simplify transport layer, remove adapter pattern

**Changes:**

1. **Remove adapter usage in VOGSystem**
   ```python
   # BEFORE (vog_system.py:146-148)
   device_adapter = TransportDeviceAdapter(transport, port)
   handler = VOGHandler(device_adapter, port, ...)

   # AFTER - Handler uses transport directly
   handler = VOGHandler(transport, port, ...)
   ```

2. **Simplify VOGHandler constructor**
   ```python
   # BEFORE
   def __init__(self, device: USBSerialDevice, port: str, ...)

   # AFTER
   def __init__(self, transport: BaseTransport, device_id: str, ...)
   ```

3. **Clean up USBTransport**
   - Remove any adapter-related methods
   - Focus on: `connect()`, `disconnect()`, `write()`, `read_line()`

---

### Phase 7: Update Runtime

**Goal:** Clean up vog/runtime.py after removing dead code

**Current Issues:**
- May still reference ConnectionManager, XBeeManager
- Complex initialization paths

**Changes:**

1. **Remove dead imports**
   ```python
   # REMOVE these if present
   from vog_core.connection_manager import ConnectionManager
   from vog_core.xbee_manager import XBeeManager
   ```

2. **Simplify initialization**
   - VOGModuleRuntime just creates VOGSystem
   - No device scanning - waits for `assign_device` commands

3. **Clean up command handling**
   - Ensure `assign_device` and `unassign_device` work correctly
   - Remove any scanning-related commands

---

### Phase 8: Final Cleanup and Testing

**Goal:** Verify everything works, update documentation

**Steps:**

1. **Run static analysis**
   ```bash
   python3 -m py_compile rpi_logger/modules/VOG/**/*.py
   flake8 rpi_logger/modules/VOG/
   ```

2. **Test module loading**
   ```bash
   python3 -c "from rpi_logger.modules.VOG import VOGSystem"
   python3 -m rpi_logger.modules.VOG --mode gui
   ```

3. **Test with main logger**
   ```bash
   python3 -m rpi_logger
   # Connect USB device, verify it appears in VOG
   ```

4. **Update README.md if needed**

5. **Remove any stale __pycache__ directories**
   ```bash
   find rpi_logger/modules/VOG -type d -name __pycache__ -exec rm -rf {} +
   ```

---

## Migration Checklist

### Phase 1: Delete Dead Code
- [ ] Delete `vog_core/connection_manager.py`
- [ ] Delete `vog_core/xbee_manager.py`
- [ ] Delete `vog_core/modes/` directory
- [ ] Delete `vog_core/transport_device_adapter.py`
- [ ] Update imports in affected files
- [ ] Verify module still imports

### Phase 2: Clean Up VOGSystem
- [ ] Remove `_create_mode_instance` method
- [ ] Clean up wireless device handling
- [ ] Simplify callback chains
- [ ] Test `assign_device` / `unassign_device`

### Phase 3: Clean Up VOGHandler
- [ ] Simplify trial number determination
- [ ] Remove redundant device type storage
- [ ] Simplify callback handling
- [ ] Update to use transport directly (no adapter)

### Phase 4: Reorganize GUI
- [ ] Move `interfaces/gui/` to `gui/`
- [ ] Split `view.py` into components
- [ ] Create `device_tab.py`
- [ ] Create `controls.py`
- [ ] Update imports

### Phase 5: Consolidate Constants
- [ ] Merge all constants into `constants.py`
- [ ] Update protocol classes to use shared constants
- [ ] Remove duplicate constant definitions

### Phase 6: Clean Up Transports
- [ ] Remove adapter pattern from VOGSystem
- [ ] Update VOGHandler constructor
- [ ] Clean up USBTransport

### Phase 7: Update Runtime
- [ ] Remove dead imports
- [ ] Simplify initialization
- [ ] Verify command handling works

### Phase 8: Final Testing
- [ ] Static analysis passes
- [ ] Module loads without errors
- [ ] GUI mode works
- [ ] Device assignment works with main logger
- [ ] Recording produces correct CSV output

---

## Code Deletion Summary

```
Files to DELETE entirely:
├── vog_core/connection_manager.py    540 lines  (USB scanning - now in main logger)
├── vog_core/xbee_manager.py          569 lines  (XBee - now in main logger)
├── vog_core/transport_device_adapter.py  77 lines  (unnecessary adapter)
└── vog_core/modes/
    ├── __init__.py                     1 line
    ├── gui_mode.py                    85 lines   (unused)
    └── simple_mode.py                129 lines   (unused)
                                    ─────────
                          TOTAL:   ~1,401 lines to delete
```

---

## Key Architecture Decisions

### D1: Keep Protocol Abstraction

**Decision:** Keep the `BaseVOGProtocol` → `SVOGProtocol`/`WVOGProtocol` pattern

**Rationale:**
- Protocols define command formats and response parsing
- Handler doesn't need to know which protocol it's using
- Makes adding new device types easier
- DRT's approach of separate handler classes is more complex

### D2: Remove Adapter Pattern

**Decision:** Delete `TransportDeviceAdapter`, have handler use transport directly

**Rationale:**
- Adapter was needed when handler expected old `USBSerialDevice` interface
- Now that we control both sides, adapter adds no value
- Simplifies code and reduces layers

### D3: Centralized Device Discovery

**Decision:** VOG module does NOT scan for devices (already implemented)

**Rationale:**
- Main logger handles all USB/XBee scanning
- Devices are assigned via JSON commands
- ConnectionManager and XBeeManager are dead code

### D4: Single Trial Number Source

**Decision:** `VOGSystem.active_trial_number` is the only source of truth

**Rationale:**
- Currently handler has complex fallback logic
- System manages trial lifecycle
- Handler should just use system's number

### D5: Keep Plotter in vog/

**Decision:** Keep `vog/plotter.py` separate from `gui/`

**Rationale:**
- Plotter is matplotlib-based, different from Tkinter
- Used by view.py for display
- Logically separate concern

---

## Risk Assessment

### Low Risk
- Deleting dead code (ConnectionManager, XBeeManager, modes/)
- Consolidating constants
- Reorganizing GUI files

### Medium Risk
- Removing adapter pattern (need to update handler and system)
- Simplifying trial number logic (verify data integrity)
- Splitting view.py (verify all callbacks still work)

### Mitigation
- Make changes incrementally
- Test after each phase
- Keep git history for easy rollback
- Test with actual hardware when possible

---

## Success Metrics

1. **Line count:** ~7,461 → ~3,500 (53% reduction)
2. **Dead code:** 1,401 lines deleted
3. **Max file size:** No file > 400 lines (except plotter)
4. **Imports:** All imports resolve correctly
5. **Functionality:** All existing features work
   - Device assignment via main logger
   - Recording start/stop
   - Lens control (peek open/close)
   - Configuration dialog
   - Real-time plotting
