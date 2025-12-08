# DRT Module Deep Refactoring Plan

## Executive Summary

This plan addresses the significant code redundancy between sDRT and wDRT handlers while preserving the distinct protocol behaviors of each device type. The refactoring introduces a **Protocol Strategy Pattern** that separates "what varies" (protocol specifics) from "what's shared" (lifecycle, logging, event dispatch).

**Estimated code reduction**: ~500 lines (60% of handler code)
**Risk level**: Medium - requires careful testing of both device types
**Breaking changes**: Internal only - public API preserved

---

## Critical Constraints

### This is Greenfield Code
All new files in this plan are **greenfield implementations**. We are not modifying existing handler logic in-place - we are building new abstractions alongside the existing code, then switching over once validated.

### Device Protocol Contracts are IMMUTABLE
The sDRT and wDRT devices have **fixed firmware protocols** that cannot change. The following device behaviors are hardware constraints that MUST be preserved exactly:

| Constraint | sDRT | wDRT | Why It Matters |
|------------|------|------|----------------|
| **Command format** | `exp_start\n\r` | `trl>1\n` | Firmware expects exact strings |
| **Response format** | `trl>ts,trial,rt` | `dta>blk,trl,clk,rt,bat,utc` | Firmware sends these exact formats |
| **RT units from device** | milliseconds | microseconds | Hardware clock differences |
| **Click reporting** | Cumulative count | Per-event count | Firmware implementation |
| **Line endings** | `\n\r` | `\n` | Firmware serial config |
| **CSV output format** | 7 fields | 9 fields | Data analysis scripts depend on this |

**The protocol layer encapsulates these differences - it does NOT change them.**

### Data Flow Direction
```
┌──────────────┐                    ┌──────────────┐                    ┌──────────────┐
│   DEVICE     │ ──── IMMUTABLE ──► │   PROTOCOL   │ ──── NORMALIZE ──► │    VIEW      │
│  (firmware)  │      contract      │    LAYER     │    for internal    │  (plotter)   │
│              │                    │   (new code) │       use          │              │
└──────────────┘                    └──────────────┘                    └──────────────┘

- LEFT SIDE: Device sends what device sends. We parse it exactly as-is.
- MIDDLE: Protocol layer translates device-specific → normalized internal format
- RIGHT SIDE: View receives normalized events, doesn't know device type
```

### What We CAN Normalize (Internal Only)
- Internal event payloads (e.g., always pass RT in ms to plotter)
- Handler method signatures
- Code structure and organization

### What We CANNOT Change
- Bytes sent to device (command strings, line endings)
- How we parse bytes from device (response formats)
- CSV file output format (external tools depend on this)
- Any timing or sequencing behavior

---

## Current Architecture Problems

### 1. Parallel Handler Implementations
```
BaseDRTHandler (ABC)
    ├── SDRTHandler (405 lines)      ← 62% redundant
    └── WDRTBaseHandler (323 lines)  ← 62% redundant
            ├── WDRTUSBHandler (41 lines)
            └── WDRTWirelessHandler (48 lines)
```

### 2. Device-Specific Differences (What Actually Varies)

| Aspect | sDRT | wDRT |
|--------|------|------|
| **Command format** | `exp_start\n\r` | `trl>1\n` |
| **RT units** | milliseconds | microseconds |
| **Click tracking** | Cumulative (delta calc) | Per-event |
| **Trial logging trigger** | On stimulus OFF | On `dta>` packet |
| **CSV fields** | 7 fields | 9 fields (+ battery, device_utc) |
| **ISO preset** | Individual set commands | Single `dev>iso` command |
| **Session control** | External only | Device can trigger via `exp>` |
| **Extra features** | None | Battery, RTC sync |

### 3. View Layer Complexity
The view has 6+ device-type branches that translate device-specific events to a device-agnostic plotter.

---

## Proposed Architecture

### New Class Hierarchy

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         PROTOCOL LAYER                                  │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  DRTProtocol (ABC)                                                      │
│  ├── commands: Dict[str, str]                                           │
│  ├── responses: Dict[str, str]                                          │
│  ├── line_ending: str                                                   │
│  ├── csv_header: str                                                    │
│  ├── rt_unit_divisor: float  (1.0 for ms, 1000.0 for μs)               │
│  ├── parse_trial_data(line) -> TrialData                                │
│  ├── parse_click(value) -> int                                          │
│  ├── format_csv_line(trial_data, context) -> str                        │
│  └── get_extra_csv_fields() -> List[str]                                │
│                                                                         │
│  SDRTProtocol(DRTProtocol)                                              │
│  └── Implements sDRT-specific parsing and formatting                    │
│                                                                         │
│  WDRTProtocol(DRTProtocol)                                              │
│  └── Implements wDRT-specific parsing and formatting                    │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────┐
│                         HANDLER LAYER                                   │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  BaseDRTHandler (ABC) - unchanged interface                             │
│                                                                         │
│  DRTHandler(BaseDRTHandler)                                             │
│  ├── __init__(device_id, output_dir, transport, protocol: DRTProtocol)  │
│  ├── All shared implementation (send_command, lifecycle, logging)       │
│  └── Delegates protocol-specific work to self.protocol                  │
│                                                                         │
│  WDRTHandler(DRTHandler)  - thin subclass                               │
│  ├── Adds battery_percent property                                      │
│  ├── Adds sync_rtc() method                                             │
│  └── Handles wDRT-specific features                                     │
│                                                                         │
│  WDRTUSBHandler(WDRTHandler) - very thin                                │
│  └── Auto-syncs RTC on start                                            │
│                                                                         │
│  WDRTWirelessHandler(WDRTHandler) - very thin                           │
│  └── Longer battery poll delay                                          │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────┐
│                         DATA LAYER                                      │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  @dataclass                                                             │
│  TrialData:                                                             │
│      timestamp: int           # Device timestamp (ms)                   │
│      trial_number: int                                                  │
│      reaction_time_ms: float  # ALWAYS in milliseconds                  │
│      clicks: int                                                        │
│      is_hit: bool                                                       │
│      battery: Optional[int]   # wDRT only                               │
│      device_utc: Optional[int] # wDRT only                              │
│                                                                         │
│  @dataclass                                                             │
│  NormalizedEvent:                                                       │
│      event_type: str          # 'trial_complete', 'stimulus', etc.      │
│      data: Dict[str, Any]     # Normalized payload                      │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Implementation Steps

### Development Approach: Greenfield Alongside Existing

```
DURING DEVELOPMENT:
┌─────────────────────────────────────────────────────────────────┐
│  Existing Code (unchanged, still works)                        │
│  ├── sdrt_handler.py                                           │
│  ├── wdrt_base_handler.py                                      │
│  └── view.py (current branching logic)                         │
├─────────────────────────────────────────────────────────────────┤
│  New Code (greenfield, built in parallel)                      │
│  ├── protocols/sdrt_protocol.py                                │
│  ├── protocols/wdrt_protocol.py                                │
│  ├── handlers/drt_handler.py                                   │
│  └── handlers/wdrt_handler.py                                  │
└─────────────────────────────────────────────────────────────────┘

AFTER VALIDATION:
- Runtime switches to new handlers
- Old handlers archived/deleted
- View simplified to use normalized events
```

### Phase 1: Data Structures and Protocol Abstraction

#### Step 1.1: Create TrialData dataclass
**File**: `drt_core/data_types.py` (new greenfield file)

```python
from dataclasses import dataclass, field
from typing import Optional

@dataclass
class TrialData:
    """
    Normalized trial data structure for INTERNAL use only.

    This is used to pass data between handler and view layers.
    It does NOT affect device communication or CSV output format.
    """
    timestamp: int = 0                    # Device timestamp in ms
    trial_number: int = 0
    reaction_time_ms: float = -1.0        # Normalized to milliseconds for internal use
    clicks: int = 0
    is_hit: bool = False
    # Optional fields (wDRT only, preserved for CSV output)
    battery: Optional[int] = None
    device_utc: Optional[int] = None

    @property
    def is_miss(self) -> bool:
        return self.reaction_time_ms < 0
```

#### Step 1.2: Create DRTProtocol ABC
**File**: `drt_core/protocols/base_protocol.py` (new greenfield file)

Define abstract interface that **PRESERVES device-specific behavior**:
- `commands` property - exact command strings as firmware expects
- `responses` property - exact response prefixes as firmware sends
- `line_ending` property - device-specific line ending
- `csv_header` property - **MUST match existing format for data compatibility**
- `rt_to_milliseconds(value: int) -> float` - unit conversion for internal use only
- `parse_response(line: str) -> Tuple[str, str]` - parse device-specific format
- `parse_trial_data(response_type: str, value: str, context: dict) -> Optional[TrialData]`
- `format_csv_line(trial_data: TrialData, device_id: str, label: str) -> str` - **MUST match existing CSV format**

#### Step 1.3: Implement SDRTProtocol
**File**: `drt_core/protocols/sdrt_protocol.py` (new greenfield file)

Key implementations that **PRESERVE all sDRT behavior**:
- Commands: `exp_start`, `exp_stop`, `stim_on`, `stim_off`, etc. (exact strings)
- Line ending: `\n\r` (as firmware expects)
- RT passthrough: device sends ms, returns as-is
- Cumulative click delta tracking via context (preserves firmware behavior)
- CSV format: **Exactly 7 fields** matching current `SDRT_CSV_HEADER`
- Trial parsing: `trl>ts,trial,rt` format exactly as device sends

#### Step 1.4: Implement WDRTProtocol
**File**: `drt_core/protocols/wdrt_protocol.py` (new greenfield file)

Key implementations that **PRESERVE all wDRT behavior**:
- Commands: `trl>1`, `trl>0`, `dev>1`, `dev>0`, etc. (exact strings)
- Line ending: `\n` (as firmware expects)
- RT conversion: device sends μs, convert to ms for internal use only
- Per-event click count (preserves firmware behavior)
- CSV format: **Exactly 9 fields** matching current `WDRT_CSV_HEADER`
- Trial parsing: `dta>blk,trl,clk,rt,bat,utc` format exactly as device sends
- Extra responses: `bty>`, `exp>`, `rt>` (wDRT-specific events preserved)

### Phase 2: Unified Handler Implementation

#### Step 2.1: Create unified DRTHandler
**File**: `drt_core/handlers/drt_handler.py` (new greenfield file)

This is a NEW handler built alongside existing code. It delegates device-specific behavior to the protocol:
- `send_command()` - uses `protocol.commands` and `protocol.line_ending`
- `_process_response()` - unified dispatcher using `protocol.responses`
- `_log_trial_data()` - uses `protocol.format_csv_line()`
- `start_experiment()` / `stop_experiment()` - shared logic
- Event normalization before dispatch

Key design:
```python
class DRTHandler(BaseDRTHandler):
    def __init__(self, device_id, output_dir, transport, protocol: DRTProtocol):
        super().__init__(device_id, output_dir, transport)
        self.protocol = protocol
        self._protocol_context = {}  # For click tracking, etc.

    async def send_command(self, command: str, value: Optional[str] = None) -> bool:
        if command not in self.protocol.commands:
            logger.error("Unknown command: %s", command)
            return False
        cmd_string = self.protocol.commands[command]
        full_cmd = f"{cmd_string}{value}" if value else cmd_string
        return await self.transport.write_line(full_cmd, self.protocol.line_ending)

    def _process_response(self, line: str) -> None:
        response_type, value = self.protocol.parse_response(line)
        if response_type is None:
            return

        # Dispatch to handler methods
        handler_method = getattr(self, f'_handle_{response_type}', None)
        if handler_method:
            handler_method(value)

    def _handle_trial(self, value: str) -> None:
        # Let protocol parse and normalize
        trial_data = self.protocol.parse_trial_data('trial', value, self._protocol_context)
        if trial_data:
            self._dispatch_normalized_trial(trial_data)

    def _dispatch_normalized_trial(self, trial_data: TrialData) -> None:
        """Dispatch normalized trial event - view doesn't need to know device type."""
        self._create_background_task(self._dispatch_data_event('trial_complete', {
            'trial_number': trial_data.trial_number,
            'reaction_time_ms': trial_data.reaction_time_ms,  # ALWAYS ms
            'is_hit': trial_data.is_hit,
            'clicks': trial_data.clicks,
            'battery': trial_data.battery,
        }))
```

#### Step 2.2: Create WDRTHandler subclass
**File**: `drt_core/handlers/wdrt_handler.py` (new greenfield file)

Thin subclass that adds wDRT-specific features (real hardware differences):
- `battery_percent` property - wDRT has battery, sDRT doesn't
- `sync_rtc()` method - wDRT has RTC, sDRT doesn't
- `get_battery()` method - wDRT-specific command
- `_handle_experiment()` - wDRT devices can autonomously start/stop
- `_handle_reaction_time()` - wDRT sends RT immediately (sDRT sends with trial)

#### Step 2.3: Update WDRTUSBHandler and WDRTWirelessHandler
**Files**: Modify existing thin subclasses to extend new `WDRTHandler`
- WDRTUSBHandler: Auto RTC sync on start (USB can sync immediately)
- WDRTWirelessHandler: Longer battery poll delay (wireless latency), node_id property

#### Step 2.4: Archive old handlers (DO NOT DELETE YET)
During transition period, keep for A/B testing and rollback:
- Rename `sdrt_handler.py` → `sdrt_handler_legacy.py`
- Rename `wdrt_base_handler.py` → `wdrt_base_handler_legacy.py`
- Runtime config flag to switch between legacy/new handlers
- Delete only after full validation with real hardware

### Phase 3: View Simplification

#### Step 3.1: Simplify on_device_data()
Replace device-specific branching with unified event handling:

```python
def on_device_data(self, port: str, data_type: str, data: Dict[str, Any]):
    if data_type == 'stimulus':
        self._handle_stimulus(port, data)

    elif data_type == 'trial_complete':  # NEW: unified event
        # RT is ALWAYS in milliseconds now
        trial_num = data.get('trial_number')
        rt_ms = data.get('reaction_time_ms')
        is_hit = data.get('is_hit', True)
        clicks = data.get('clicks')
        battery = data.get('battery')

        # Update UI
        if trial_num is not None and self._trial_n:
            self._trial_n.set(str(trial_num))
        if clicks is not None and self._click_count:
            self._click_count.set(str(clicks))
        if rt_ms is not None:
            self._rt_var.set(f"{rt_ms:.0f}" if is_hit else "Miss")
            if self._plotter:
                self._plotter.update_trial(port, rt_ms, is_hit=is_hit)
        if battery is not None and self._battery_var:
            self._battery_var.set(f"{battery}%")

    elif data_type == 'click':
        # Same as before
        ...
```

#### Step 3.2: Remove device-type config branching
Unify config upload by having handlers expose a common `set_config_params()` method:

```python
# In handler
async def set_config_params(self, params: Dict[str, int]) -> bool:
    """Set configuration parameters - protocol handles the details."""
    return await self.protocol.upload_config(self, params)

# In view - no more branching
def _on_config_upload(self, params: Dict[str, int]):
    handler = self.system.get_device_handler(self._port)
    if handler and self.async_bridge:
        self.async_bridge.run_coroutine(handler.set_config_params(params))
```

### Phase 4: Runtime Updates

#### Step 4.1: Update _create_handler() in runtime.py

```python
def _create_handler(self, device_type: DRTDeviceType, device_id: str, transport) -> Optional[BaseDRTHandler]:
    if device_type == DRTDeviceType.SDRT:
        protocol = SDRTProtocol()
        return DRTHandler(device_id, self.module_data_dir, transport, protocol)
    elif device_type == DRTDeviceType.WDRT_USB:
        protocol = WDRTProtocol()
        return WDRTUSBHandler(device_id, self.module_data_dir, transport, protocol)
    elif device_type == DRTDeviceType.WDRT_WIRELESS:
        protocol = WDRTProtocol()
        return WDRTWirelessHandler(device_id, self.module_data_dir, transport, protocol)
```

---

## File Changes Summary

### New Greenfield Files (built alongside existing code)
| File | Purpose | Est. Lines |
|------|---------|------------|
| `drt_core/data_types.py` | TrialData dataclass (internal use only) | ~50 |
| `drt_core/protocols/__init__.py` | Protocol exports | ~10 |
| `drt_core/protocols/base_protocol.py` | DRTProtocol ABC | ~80 |
| `drt_core/protocols/sdrt_protocol.py` | sDRT protocol (**preserves all sDRT behavior**) | ~120 |
| `drt_core/protocols/wdrt_protocol.py` | wDRT protocol (**preserves all wDRT behavior**) | ~100 |
| `drt_core/handlers/drt_handler.py` | Unified handler (shared orchestration only) | ~250 |
| `drt_core/handlers/wdrt_handler.py` | wDRT-specific features (battery, RTC, etc.) | ~60 |

### Modified Files (after greenfield validated)
| File | Changes |
|------|---------|
| `drt_core/handlers/__init__.py` | Export new handlers |
| `drt_core/handlers/wdrt_usb_handler.py` | Extend WDRTHandler instead of WDRTBaseHandler |
| `drt_core/handlers/wdrt_wireless_handler.py` | Extend WDRTHandler instead of WDRTBaseHandler |
| `drt/view.py` | Simplify on_device_data() to use normalized events |
| `drt/runtime.py` | Update _create_handler(), add legacy/new toggle |
| `drt_core/protocols.py` | Keep constants (referenced by protocol classes) |

### Archived Files (kept for rollback until validated)
| File | New Name | Reason |
|------|----------|--------|
| `drt_core/handlers/sdrt_handler.py` | `sdrt_handler_legacy.py` | Keep for A/B testing |
| `drt_core/handlers/wdrt_base_handler.py` | `wdrt_base_handler_legacy.py` | Keep for A/B testing |

---

## Migration Strategy

### Backward Compatibility
The refactoring maintains full backward compatibility:
- `BaseDRTHandler` interface unchanged
- View's public methods unchanged
- Runtime command interface unchanged
- CSV output format unchanged

### Testing Checkpoints

**CRITICAL**: Every test must verify device communication and data output are BYTE-FOR-BYTE IDENTICAL to existing code.

1. **After Phase 1**: Unit test protocol classes in isolation
   - **Command strings**: Verify exact bytes sent to device match legacy handler
   - **Response parsing**: Feed captured device output, verify identical parsing
   - **CSV format**: Generate lines, diff against golden files from existing code
   - **RT units**: sDRT passes through ms, wDRT converts μs→ms correctly

2. **After Phase 2**: Integration test handlers with REAL HARDWARE
   - **sDRT device**:
     - Capture serial traffic, byte-compare to legacy handler
     - Run full trial, verify CSV output identical
     - Verify cumulative click tracking matches legacy behavior
   - **wDRT USB device**:
     - Capture serial traffic, byte-compare to legacy handler
     - Run full trial, verify CSV output identical
     - Verify battery/RTC features work
   - **A/B test**: Run legacy and new handlers side-by-side, diff all outputs

3. **After Phase 3**: End-to-end GUI testing
   - Verify plotter updates correctly for both device types
   - Verify RT displayed in correct units (always ms in UI)
   - Verify config dialog works for both device types
   - Verify all UI stats update correctly

4. **After Phase 4**: Full regression + data analysis validation
   - Multi-device scenarios
   - Recording start/stop cycles
   - Session directory changes
   - **Run existing analysis scripts on new CSV output** - must work unchanged

---

## Risk Mitigation

### High-Risk Areas

1. **Click tracking logic** (sDRT cumulative vs wDRT per-event)
   - Mitigation: Extensive unit tests with real device data captures
   - Keep old handlers available during transition for A/B testing

2. **RT unit normalization**
   - Mitigation: Add assertions that RT values are in expected range
   - Log warnings if RT values seem wrong (e.g., > 10000ms)

3. **CSV format changes**
   - Mitigation: Diff test - compare new CSV output against golden files
   - Ensure header and data columns match exactly

### Rollback Plan
Keep old handler files renamed to `*_legacy.py` until full validation complete. Runtime can be configured to use legacy handlers via config flag.

---

## Success Metrics

| Metric | Before | After |
|--------|--------|-------|
| Handler code lines | ~730 | ~310 |
| View branching points | 6+ | 1 |
| Code duplication | ~60% | <10% |
| Device-specific knowledge in view | High | None |
| Adding new DRT variant | ~400 lines | ~100 lines (protocol only) |

---

## Open Questions for User

1. **Preserve legacy handlers?** Should we keep the old handlers available for a transition period, or remove them completely?

2. **Config file format**: The wDRT protocol has different config parameter names internally (`ONTM` vs `stimDur`). Should the new protocol layer also normalize config parameter names, or keep device-specific names?

3. **Event naming**: The new unified event is `trial_complete`. Alternative names considered: `trial_data`, `trial_result`, `normalized_trial`. Preference?

4. **Phased rollout**: Should we implement this in phases with intermediate releases, or as a single large refactor?
