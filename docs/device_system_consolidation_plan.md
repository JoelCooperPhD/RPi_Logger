# Device System Consolidation Plan

## Overview

This plan consolidates the device management architecture from two parallel systems (OLD `DeviceConnectionManager` and NEW `DeviceSystem`) into a single unified system.

## Current State

### Two Parallel Systems Running

1. **OLD System** (`connection_manager.py`):
   - `DeviceConnectionManager` class
   - `DeviceInfo` with 20+ hardcoded optional fields
   - 8 separate device storage dicts
   - Direct scanner callbacks
   - Used by `LoggerSystem` for lifecycle callbacks

2. **NEW System** (`device_system.py`, `lifecycle.py`, `selection.py`, `catalog.py`):
   - `DeviceSystem` facade
   - `DeviceInfo` with flexible `metadata` dict
   - Single unified device storage
   - Event-based scanner integration via `ScannerEventAdapter`
   - Used by UI (`DevicesPanel`, `DeviceUIController`)

### Key Problems

1. **Two `DeviceInfo` classes** with different structures
2. **`devices/__init__.py` exports OLD DeviceInfo** (line 79)
3. **`LoggerSystem` uses both systems** simultaneously
4. **Compatibility shims** like `get_field()` bridge the two types
5. **Duplicated state tracking** (connected devices, auto-connect, etc.)

---

## Phase 1: Unify DeviceInfo

**Goal**: Single `DeviceInfo` class used everywhere

### Step 1.1: Update `devices/__init__.py` exports

```python
# REMOVE this import:
from .connection_manager import (
    DeviceConnectionManager,
    ConnectionState,
    DeviceInfo,        # <-- REMOVE
    XBeeDongleInfo,
)

# ADD this import:
from .lifecycle import DeviceInfo, ConnectionState
```

### Step 1.2: Add `ConnectionState` to lifecycle.py

The NEW `DeviceInfo` in `lifecycle.py` uses `ConnectionState` from `selection.py`. Ensure it's properly exported.

### Step 1.3: Update all imports

Files that import `DeviceInfo`:
- `rpi_logger/core/logger_system.py` - Already imports from lifecycle
- `rpi_logger/core/ui/device_controller.py` - Check import source
- Any other files using DeviceInfo

### Step 1.4: Remove compatibility shims

Once all code uses lifecycle `DeviceInfo`, remove:
- `get_field()` helper in `_build_assign_device_command_builder()`
- `get_field()` helper in `_build_assign_device_command()`

---

## Phase 2: Migrate LoggerSystem to DeviceSystem

**Goal**: `LoggerSystem` uses only `DeviceSystem`, not `DeviceConnectionManager`

### Step 2.1: Map OLD callbacks to NEW callbacks

| OLD Callback | NEW Equivalent |
|--------------|----------------|
| `set_device_connected_callback()` | `set_on_connect_device()` |
| `set_device_disconnected_callback()` | `set_on_disconnect_device()` |
| `set_save_connection_state_callback()` | Handled by observers |
| `set_load_connection_state_callback()` | Handled by observers |

### Step 2.2: Update LoggerSystem initialization

```python
# BEFORE (current):
self.device_system = DeviceSystem()
self.device_manager = DeviceConnectionManager()
self.device_manager.set_device_connected_callback(self._on_device_connected)
self.device_manager.set_device_disconnected_callback(self._on_device_disconnected)

# AFTER (consolidated):
self.device_system = DeviceSystem()
self.device_system.set_on_connect_device(self._on_device_connected)
self.device_system.set_on_disconnect_device(self._on_device_disconnected)
# Remove device_manager entirely
```

### Step 2.3: Update `_on_device_connected` signature

The NEW system passes `device_id: str`, not `device: DeviceInfo`.

```python
# BEFORE:
async def _on_device_connected(self, device: DeviceInfo) -> None:
    module_id = device.module_id
    ...

# AFTER:
async def _on_device_connected(self, device_id: str) -> None:
    device = self.device_system.get_device(device_id)
    if not device:
        return
    module_id = device.module_id
    ...
```

### Step 2.4: Migrate XBee routing

```python
# BEFORE:
self.device_manager.set_xbee_data_router(self._on_xbee_data)

# AFTER:
self.device_system.set_xbee_data_callback(self._on_xbee_data)
```

### Step 2.5: Migrate connection state persistence

Create observer for DeviceSystem or handle via existing config persistence.

### Step 2.6: Migrate auto-connect logic

```python
# BEFORE:
self.device_manager.set_pending_auto_connect(module_id)

# AFTER:
self.device_system.set_auto_connect_module(module_id)
```

---

## Phase 3: Update DeviceSystem Callbacks

**Goal**: DeviceSystem callbacks match what LoggerSystem needs

### Step 3.1: Add device object to connect callback

Currently `set_on_connect_device` passes only `device_id`. LoggerSystem needs the full device info.

Option A: Change callback signature to pass `DeviceInfo`
Option B: LoggerSystem looks up device (recommended - keeps API simple)

### Step 3.2: Ensure connection state persistence

Add hooks for saving/loading which devices were connected.

---

## Phase 4: Remove DeviceConnectionManager

**Goal**: Complete removal of OLD system

### Step 4.1: Remove from LoggerSystem

```python
# DELETE these lines:
self.device_manager = DeviceConnectionManager()
self.device_manager.set_device_connected_callback(...)
self.device_manager.set_device_disconnected_callback(...)
# etc.
```

### Step 4.2: Update any remaining references

Search codebase for:
- `DeviceConnectionManager`
- `device_manager` (as attribute)
- Imports from `connection_manager`

### Step 4.3: Keep DeviceConnectionManager file (temporarily)

Keep `connection_manager.py` but mark as deprecated. May still be needed for:
- `XBeeDongleInfo` (if used elsewhere)
- Any legacy code paths

### Step 4.4: Final removal

Once confident nothing uses it, delete or archive `connection_manager.py`.

---

## Phase 5: Clean Up Exports

**Goal**: Clean, consistent public API

### Step 5.1: Update `devices/__init__.py`

```python
# Core types
from .device_registry import (
    InterfaceType, DeviceFamily, DeviceType, DeviceSpec,
    ConnectionKey, DEVICE_REGISTRY, ...
)

# NEW architecture (primary)
from .lifecycle import DeviceInfo, ConnectionState
from .device_system import DeviceSystem
from .catalog import DeviceCatalog
from .selection import DeviceSelectionModel

# Scanners (keep as-is)
from .usb_scanner import USBScanner, DiscoveredUSBDevice
...

# DEPRECATED (remove after migration)
from .connection_manager import DeviceConnectionManager, XBeeDongleInfo
```

### Step 5.2: Update `__all__`

Remove `DeviceConnectionManager` and old `DeviceInfo` from `__all__`.

---

## Phase 6: Testing & Validation

### Step 6.1: Test device discovery

- [ ] USB devices discovered and shown in panel
- [ ] Wireless devices discovered via XBee
- [ ] Audio devices discovered
- [ ] Camera devices discovered
- [ ] Internal devices (Notes) available

### Step 6.2: Test device connection

- [ ] Click device -> turns yellow (CONNECTING)
- [ ] Module launches
- [ ] Device acknowledged -> turns green (CONNECTED)
- [ ] Click again -> disconnects, turns dark

### Step 6.3: Test persistence

- [ ] Close app with device connected
- [ ] Reopen app -> device auto-connects
- [ ] Module checkbox state persisted

### Step 6.4: Test error handling

- [ ] Device unplugged while connected -> graceful disconnect
- [ ] Module crash -> state updates correctly
- [ ] Connection timeout -> proper error state

---

## Migration Checklist

### Pre-Migration
- [ ] All tests passing
- [ ] Current functionality working (even with dual systems)

### Phase 1: Unify DeviceInfo
- [ ] Update `devices/__init__.py` to export lifecycle.DeviceInfo
- [ ] Update all imports
- [ ] Remove `get_field()` compatibility shims
- [ ] Verify no runtime errors

### Phase 2: Migrate LoggerSystem
- [ ] Wire DeviceSystem callbacks
- [ ] Update `_on_device_connected` signature
- [ ] Migrate XBee routing
- [ ] Migrate auto-connect logic
- [ ] Verify device connection works end-to-end

### Phase 3: Update DeviceSystem
- [ ] Add any missing callback functionality
- [ ] Ensure persistence works

### Phase 4: Remove OLD System
- [ ] Remove DeviceConnectionManager from LoggerSystem
- [ ] Search for remaining references
- [ ] Mark connection_manager.py as deprecated

### Phase 5: Clean Up
- [ ] Update __init__.py exports
- [ ] Update __all__
- [ ] Remove dead code

### Phase 6: Validate
- [ ] All test scenarios pass
- [ ] No console errors
- [ ] Clean git diff

---

## Files Affected

| File | Changes |
|------|---------|
| `devices/__init__.py` | Update exports |
| `devices/lifecycle.py` | Ensure ConnectionState exported |
| `logger_system.py` | Remove device_manager, use device_system |
| `devices/device_system.py` | May need callback enhancements |
| `devices/connection_manager.py` | Mark deprecated, eventually delete |

---

## Risk Mitigation

1. **Incremental migration**: Each phase can be tested independently
2. **Keep OLD code**: Don't delete until NEW is verified
3. **Feature flags**: Could add config to switch between systems during testing
4. **Rollback plan**: Git makes it easy to revert if issues found

---

## Estimated Effort

| Phase | Effort | Risk |
|-------|--------|------|
| Phase 1: Unify DeviceInfo | Low | Low |
| Phase 2: Migrate LoggerSystem | Medium | Medium |
| Phase 3: Update DeviceSystem | Low | Low |
| Phase 4: Remove OLD | Low | Low |
| Phase 5: Clean Up | Low | Low |
| Phase 6: Testing | Medium | - |

**Total**: ~2-3 hours of focused work

---

## Success Criteria

1. Single `DeviceInfo` class in use everywhere
2. `DeviceConnectionManager` removed from `LoggerSystem`
3. All device operations go through `DeviceSystem`
4. No compatibility shims or type adapters
5. Clean imports in `devices/__init__.py`
6. All existing functionality preserved
