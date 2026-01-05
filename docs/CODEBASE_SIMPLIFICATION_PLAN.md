# Codebase Simplification Plan

## Executive Summary

This document outlines a comprehensive plan to simplify the Logger codebase (~78,000 lines of Python) while maintaining **zero breaking changes**. The plan is structured to enable parallel agent execution across independent chunks of work.

### Key Metrics
- **Total Python Files**: ~200+ files
- **Total Lines of Code**: ~78,000 (excluding `.venv`)
- **Largest Files**: `logger_system.py` (1138 LOC), `camera_settings_window.py` (1110 LOC), `events_viewer.py` (1006 LOC)
- **Modules**: 10 domain modules (Audio, Cameras, CSICameras, DRT, EyeTracker, GPS, Notes, VOG, vmc, stub)

---

## Guiding Principles

### 1. Zero Breaking Changes (CRITICAL)
- All public APIs must remain unchanged
- All configuration file formats must remain compatible
- All command-line interfaces must behave identically
- All inter-process communication protocols must remain stable
- Module process communication must be backwards compatible

### 2. Testing Requirements
Every change must include:
- Unit tests validating the change works correctly
- Integration tests proving no regressions
- Manual testing checklist where automated tests are insufficient

### 3. Simplification Types Allowed
- **Dead code removal**: Unused imports, unreferenced functions, orphaned files
- **Deduplication**: Consolidating identical/near-identical code
- **Interface extraction**: Moving shared patterns to base classes
- **Internal refactoring**: Restructuring private implementations
- **Documentation removal**: Removing stale/incorrect comments (not adding new ones)

### 4. Simplification Types NOT Allowed
- Changing public method signatures
- Renaming exported symbols
- Modifying configuration file formats
- Changing command-line argument parsing
- Altering network/IPC protocols
- Adding new features or "improvements"

---

## Codebase Architecture Overview

```
rpi_logger/
├── app/                    # Application entry point
├── cli/                    # CLI utilities
├── core/                   # Core framework (HIGHEST RISK)
│   ├── commands/           # Command protocol
│   ├── connection/         # Connection coordination
│   ├── devices/            # Device management (28 files)
│   ├── observers/          # Observer pattern impl
│   └── ui/                 # Core UI components
├── modules/                # Domain modules (PARALLEL TARGETS)
│   ├── Audio/              # Audio recording
│   ├── Cameras/            # USB camera capture
│   ├── CSICameras/         # CSI camera capture
│   ├── DRT/                # DRT device handling
│   ├── EyeTracker/         # Eye tracking integration
│   ├── GPS/                # GPS data logging
│   ├── Notes/              # Session notes
│   ├── VOG/                # VOG device handling
│   ├── vmc/                # Module runtime framework
│   ├── stub (codex)/       # DUPLICATE of vmc (!!!)
│   └── base/               # Shared module utilities
└── tools/                  # Standalone tools
```

---

## Parallel Work Chunks

The following chunks can be assigned to parallel agents. Dependencies between chunks are explicitly noted.

---

### CHUNK 1: Dead Code Elimination (Priority: HIGH)

**Agent Assignment**: `dead-code-agent`
**Risk Level**: LOW
**Dependencies**: None (can start immediately)

#### 1.1 Remove `stub (codex)/vmc` Duplication
**Files**: `rpi_logger/modules/stub (codex)/vmc/`
**Issue**: Near-identical copy of `rpi_logger/modules/vmc/`
**Verification**: `diff -rq` shows only `__pycache__` differences

**Steps**:
1. Verify no imports reference `stub (codex)/vmc` path
2. Remove the entire `stub (codex)` directory
3. Run all tests to confirm no breakage

**Test Plan**:
```bash
# Verify no imports
grep -r "stub (codex)" rpi_logger/ --include="*.py"
grep -r "stub.*codex" rpi_logger/ --include="*.py"
# Should return empty
```

#### 1.2 Identify Unused Imports
**Scope**: All `.py` files
**Tool**: `pyflakes` or manual analysis

**Steps**:
1. Run pyflakes across codebase
2. Remove verified unused imports
3. Test each module independently

#### 1.3 Identify Unreferenced Functions
**Scope**: Private functions (prefixed with `_`)
**Method**: Static analysis of call graphs

**Steps**:
1. Build call graph for private functions
2. Identify functions with zero callers
3. Verify via grep before removal
4. Remove in small batches with tests

---

### CHUNK 2: Module Base Consolidation (Priority: HIGH)

**Agent Assignment**: `base-consolidation-agent`
**Risk Level**: MEDIUM
**Dependencies**: None

#### 2.1 Camera Code Deduplication
**Files**:
- `rpi_logger/modules/base/camera_encoder.py` (530 LOC)
- `rpi_logger/modules/Cameras/camera_core/encoder.py` (525 LOC)
- `rpi_logger/modules/base/camera_types.py` (598 LOC)
- `rpi_logger/modules/Cameras/camera_core/state.py` (contains `RuntimeStatus`, `CameraRuntimeState`)

**Issue**: Parallel implementations of camera encoding and state management

**Steps**:
1. Diff the encoder files to identify exact differences
2. Consolidate to single implementation in `base/`
3. Update all imports (grep for usage patterns)
4. Ensure CSICameras uses consolidated code

**Test Plan**:
```bash
# Current imports to preserve
from rpi_logger.modules.base.camera_encoder import Encoder
from rpi_logger.modules.base.camera_types import ...
# These must continue working after consolidation
```

#### 2.2 Settings Window Deduplication
**Files**:
- `rpi_logger/modules/Cameras/app/widgets/camera_settings_window.py` (1110 LOC)
- `rpi_logger/modules/CSICameras/app/widgets/camera_settings_window.py` (1028 LOC)

**Issue**: Nearly identical settings windows with minor hardware differences

**Steps**:
1. Extract common base class `BaseCameraSettingsWindow`
2. Move shared logic to base class
3. Keep hardware-specific overrides in subclasses
4. Test both USB and CSI camera settings

---

### CHUNK 3: Core Framework Simplification (Priority: MEDIUM)

**Agent Assignment**: `core-simplification-agent`
**Risk Level**: HIGH
**Dependencies**: None, but changes here affect all modules

#### 3.1 Device Scanner Unification
**Files**: `rpi_logger/core/devices/` (28 files, multiple scanners)

**Current Scanners**:
- `USBScanner`
- `AudioScanner`
- `NetworkScanner`
- `CSIScanner`
- `UARTScanner`
- `USBCameraScanner`
- `InternalDeviceScanner`

**Issue**: Each scanner implements similar patterns independently

**Steps**:
1. Identify common scanner interface (already defined in `ScannerProtocol`)
2. Extract common functionality to base class
3. Reduce boilerplate in each scanner
4. Ensure all scanners pass existing tests

**Test Plan**:
- Test each scanner type with real hardware if available
- Test mock scenarios for CI/CD

#### 3.2 Simplify LoggerSystem
**File**: `rpi_logger/core/logger_system.py` (1138 LOC)

**Issue**: Large facade class with many responsibilities

**Steps**:
1. Identify distinct responsibility groups
2. Consider extracting helpers (without changing public API)
3. Consolidate similar device handling code paths

**Constraint**: All public methods must remain unchanged

---

### CHUNK 4: Module-Specific Simplification (PARALLELIZABLE)

These sub-chunks can run in parallel with different agents.

#### 4.1 DRT Module
**Agent Assignment**: `drt-simplification-agent`
**Risk Level**: LOW
**Dependencies**: None

**Files**: `rpi_logger/modules/DRT/` (~15 files)

**Focus Areas**:
- Handler hierarchy simplification (`base_handler.py`, `sdrt_handler.py`, `wdrt_*.py`)
- Runtime consolidation with VOG patterns
- View simplification (`view.py` - 991 LOC)

**Test Plan**:
- Run existing DRT tests
- Manual test with DRT hardware if available

#### 4.2 VOG Module
**Agent Assignment**: `vog-simplification-agent`
**Risk Level**: LOW
**Dependencies**: None

**Files**: `rpi_logger/modules/VOG/` (~15 files)

**Focus Areas**:
- Handler consolidation (`vog_handler.py` - 573 LOC)
- Protocol simplification
- View simplification (`view.py` - 783 LOC)

#### 4.3 EyeTracker Module
**Agent Assignment**: `eyetracker-simplification-agent`
**Risk Level**: LOW
**Dependencies**: None

**Files**: `rpi_logger/modules/EyeTracker/` (~20 files)

**Focus Areas**:
- Stream viewer consolidation (`imu_viewer.py` - 741 LOC, `events_viewer.py` - 1006 LOC)
- Recording manager simplification (`manager.py` - 872 LOC)
- Runtime consolidation

#### 4.4 GPS Module
**Agent Assignment**: `gps-simplification-agent`
**Risk Level**: LOW
**Dependencies**: None

**Files**: `rpi_logger/modules/GPS/` (~20 files)

**Focus Areas**:
- Handler hierarchy review
- Transport simplification
- Parser consolidation

**Test Plan**:
- Run existing GPS tests (`test_*.py` files present)
- Verify NMEA parsing unchanged

#### 4.5 Audio Module
**Agent Assignment**: `audio-simplification-agent`
**Risk Level**: LOW
**Dependencies**: None

**Files**: `rpi_logger/modules/Audio/` (~20 files)

**Focus Areas**:
- Service layer consolidation
- Recording manager simplification
- Device manager cleanup

#### 4.6 Notes Module
**Agent Assignment**: `notes-simplification-agent`
**Risk Level**: VERY LOW
**Dependencies**: None

**Files**: `rpi_logger/modules/Notes/` (~5 files)

**Focus Areas**:
- Runtime simplification (`notes_runtime.py` - 952 LOC)
- Remove any dead code

---

### CHUNK 5: UI Component Consolidation (Priority: LOW)

**Agent Assignment**: `ui-consolidation-agent`
**Risk Level**: MEDIUM
**Dependencies**: Chunks 1, 2, 3, 4 should be complete

#### 5.1 TextHandler Deduplication
**Files with duplicate `TextHandler` class**:
- `rpi_logger/core/ui/main_window.py:27`
- `rpi_logger/modules/vmc/view.py:480`
- `rpi_logger/modules/base/tkinter_gui_base.py:282`

**Steps**:
1. Extract to single location in `base/`
2. Update all usages
3. Test all UI components

#### 5.2 Theme System Simplification
**File**: `rpi_logger/core/ui/theme/styles.py` (564 LOC)

**Steps**:
1. Review for unused styles
2. Consolidate similar definitions
3. Test visual appearance unchanged

---

### CHUNK 6: VMC Framework Cleanup (Priority: LOW)

**Agent Assignment**: `vmc-cleanup-agent`
**Risk Level**: MEDIUM
**Dependencies**: Chunk 1.1 (remove duplicate first)

**Files**: `rpi_logger/modules/vmc/` (~10 files)

**Focus Areas**:
- Model simplification (`model.py` - 654 LOC)
- View simplification (`view.py` - 890 LOC)
- Runtime interface cleanup

**Constraint**: All modules using VMC must continue working

---

## Testing Strategy

### Automated Testing

#### Existing Tests to Run
```bash
# GPS tests
pytest rpi_logger/modules/GPS/tests/

# Camera validator tests
pytest rpi_logger/modules/base/tests/

# Core device tests
pytest tests/core/devices/
```

#### Tests to Add
Each chunk should add tests for:
1. Any new consolidated code
2. Import path verification
3. Basic smoke tests

### Manual Testing Checklist

For each chunk, verify:

- [ ] Application starts without errors
- [ ] All modules appear in Modules menu
- [ ] Module checkboxes toggle correctly
- [ ] Device scanning discovers hardware
- [ ] Recording start/stop works
- [ ] Configuration saves/loads correctly
- [ ] Window geometry persists
- [ ] Session directories created correctly

### Regression Testing

After all chunks complete:

1. Full application startup test
2. Multi-module recording test
3. Device hotplug test
4. Session recovery test
5. Configuration migration test

---

## Chunk Dependency Graph

```
                    CHUNK 1 (Dead Code)
                           |
            +--------------+--------------+
            |              |              |
        CHUNK 2        CHUNK 3        CHUNK 4.*
     (Base Consol)   (Core Simpl)    (Module Specific)
            |              |              |
            +--------------+--------------+
                           |
                       CHUNK 5
                    (UI Consolidation)
                           |
                       CHUNK 6
                    (VMC Cleanup)
```

**Legend**:
- Chunks at the same level can run in parallel
- Vertical connections indicate dependencies
- CHUNK 4.* sub-chunks are all parallel with each other

---

## Agent Assignment Summary

| Chunk | Agent ID | Priority | Risk | Parallelizable |
|-------|----------|----------|------|----------------|
| 1 | `dead-code-agent` | HIGH | LOW | Yes (first) |
| 2 | `base-consolidation-agent` | HIGH | MEDIUM | Yes |
| 3 | `core-simplification-agent` | MEDIUM | HIGH | Yes |
| 4.1 | `drt-simplification-agent` | LOW | LOW | Yes |
| 4.2 | `vog-simplification-agent` | LOW | LOW | Yes |
| 4.3 | `eyetracker-simplification-agent` | LOW | LOW | Yes |
| 4.4 | `gps-simplification-agent` | LOW | LOW | Yes |
| 4.5 | `audio-simplification-agent` | LOW | LOW | Yes |
| 4.6 | `notes-simplification-agent` | VERY LOW | VERY LOW | Yes |
| 5 | `ui-consolidation-agent` | LOW | MEDIUM | After 1-4 |
| 6 | `vmc-cleanup-agent` | LOW | MEDIUM | After 5 |

---

## Success Criteria

### Per-Chunk Success
- [ ] All existing tests pass
- [ ] No new warnings introduced
- [ ] Lines of code reduced (measured)
- [ ] All imports still work
- [ ] Manual testing checklist passes

### Overall Success
- [ ] Total LOC reduced by >10%
- [ ] Zero breaking changes verified
- [ ] All modules functional
- [ ] All device types work
- [ ] Recording works end-to-end
- [ ] Configuration backwards compatible

---

## Risk Mitigation

### High-Risk Areas
1. **`logger_system.py`**: Core orchestration - test extensively
2. **`device_system.py`**: Device management - hardware testing required
3. **VMC framework**: Used by all modules - regression test all

### Rollback Strategy
- Each chunk should be a separate PR
- Each PR must be revertable independently
- Keep feature branches until verified in production

### Communication Protocol Changes
- **NEVER** change JSON message formats
- **NEVER** change command protocol
- Document any internal changes thoroughly

---

## Appendix A: Key Files by Size

| File | Lines | Location |
|------|-------|----------|
| `logger_system.py` | 1138 | `core/` |
| `camera_settings_window.py` | 1110 | `Cameras/app/widgets/` |
| `camera_settings_window.py` | 1028 | `CSICameras/app/widgets/` |
| `events_viewer.py` | 1006 | `EyeTracker/app/stream_viewers/` |
| `view.py` | 991 | `DRT/drt/` |
| `bridge.py` | 959 | `Cameras/` |
| `notes_runtime.py` | 952 | `Notes/` |
| `module_manager.py` | 935 | `core/` |
| `view.py` | 903 | `EyeTracker/app/` |
| `view.py` | 890 | `vmc/` |
| `recording/manager.py` | 872 | `EyeTracker/tracker_core/` |
| `bridge.py` | 831 | `CSICameras/` |
| `device_system.py` | 816 | `core/devices/` |

---

## Appendix B: Module Runtime Classes

All modules implement `ModuleRuntime` from `vmc/runtime.py`:

- `AudioRuntime` (Audio)
- `CamerasRuntime` (Cameras)
- `CSICamerasRuntime` (CSICameras)
- `DRTModuleRuntime` (DRT)
- `EyeTrackerRuntime` (EyeTracker)
- `GPSModuleRuntime` (GPS)
- `NotesRuntime` (Notes)
- `VOGModuleRuntime` (VOG)

Any changes to `ModuleRuntime` interface will affect all modules.

---

## Appendix C: Verification Commands

```bash
# Count lines of code
find rpi_logger -name "*.py" -exec wc -l {} + | tail -1

# Find unused imports
pyflakes rpi_logger/

# Find duplicate code
# (requires external tool like PMD-CPD or custom script)

# Run all tests
pytest

# Type check (if types are used)
mypy rpi_logger/

# Verify no broken imports
python -c "import rpi_logger"
```

---

## Document History

- **Created**: 2026-01-05
- **Author**: Claude Code Assistant
- **Status**: Planning Phase
