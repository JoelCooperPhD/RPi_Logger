# Module State Synchronization Architecture Plan

**Status: IMPLEMENTED**

This document describes the new module state management architecture that has been
implemented to solve synchronization issues between multiple sources of truth.

---

## Current State Analysis (BEFORE)

### The Problem

There are multiple sources of truth for module state that can become desynchronized:

1. **`running_modules.json`** - Persists which modules were running at last shutdown (for restart)
2. **Module `config.txt` files** - Each module has `enabled = true/false`
3. **`module_enabled_state` dict** - In-memory state in ModuleManager
4. **`module_processes` dict** - Actually running processes
5. **GUI checkbox state** - `module_vars[name].get()` in MainWindow

### Current Flow (and Issues)

```
Startup:
1. LoggerSystem.__init__()
2. ModuleManager discovers modules
3. async_init() -> _load_enabled_modules()
   - If running_modules.json exists:
     - Load module names, set module_enabled_state[name] = True
     - DELETE the file immediately  <-- PROBLEM: file deleted before modules actually start
   - Else: load from module config.txt files
4. MainWindow.build_ui() creates checkboxes from module_enabled_state
5. auto_start_modules() iterates module_enabled_state and starts enabled modules

Shutdown:
1. save_running_modules_state() writes currently running modules to running_modules.json
2. cleanup() stops all modules
3. update_running_modules_state_after_cleanup() rewrites excluding forcefully stopped
```

### Identified Synchronization Issues

1. **State File Deleted Too Early**: `running_modules.json` is deleted after reading, before modules actually start. If the app crashes during startup, the state is lost.

2. **Config `enabled` Field Diverges from Running State**:
   - VOG config: `enabled = false`
   - DRT config: `enabled = false`
   - But `running_modules.json` says both should restart
   - These are never reconciled

3. **No Atomic State Transitions**: The sequence `toggle_module_enabled()` (writes config) + `set_module_enabled()` (starts process) can partially fail.

4. **GUI Checkbox Updated on Callback, Not Immediately**: When module crashes, `_status_callback` updates the checkbox asynchronously, but there's a window where state is inconsistent.

5. **No Periodic Health Check**: If a module dies (SIGSEGV, OOM-killed), it's only detected when the stdout reader fails.

6. **Multiple Sources of "Should This Module Run" Truth**:
   - `running_modules.json` (session recovery)
   - `config.txt` `enabled` field (user preference)
   - `module_enabled_state` dict (runtime)

---

## Proposed Architecture

### Core Principle: Single Source of Truth

**The `module_enabled_state` dictionary should be the ONLY runtime source of truth.**

All other state (config files, GUI, running_modules.json) should be derived from or synchronized to this single source.

### State Model

```python
class ModuleState(Enum):
    # User-desired states
    DISABLED = "disabled"      # User wants module off
    ENABLED = "enabled"        # User wants module on

    # Transient states
    STARTING = "starting"      # Transitioning to running
    STOPPING = "stopping"      # Transitioning to stopped

    # Running states
    IDLE = "idle"              # Running, not recording
    RECORDING = "recording"    # Running, recording

    # Error states
    ERROR = "error"            # Recoverable error
    CRASHED = "crashed"        # Unexpected termination
```

### Key Design Changes

#### 1. Unified State Manager

Create a new `ModuleStateManager` class that is the single authority:

```python
class ModuleStateManager:
    """Single source of truth for all module states."""

    def __init__(self):
        self._desired_state: Dict[str, bool] = {}  # User wants module enabled?
        self._actual_state: Dict[str, ModuleState] = {}  # What's actually happening
        self._state_lock = asyncio.Lock()
        self._observers: List[Callable] = []  # UI, config writer, etc.

    async def set_desired_state(self, module: str, enabled: bool) -> None:
        """User wants to enable/disable a module."""
        async with self._state_lock:
            self._desired_state[module] = enabled
            await self._notify_observers("desired_changed", module, enabled)
            # Trigger reconciliation
            await self._reconcile(module)

    async def update_actual_state(self, module: str, state: ModuleState) -> None:
        """Process reports its actual state."""
        async with self._state_lock:
            old_state = self._actual_state.get(module)
            self._actual_state[module] = state
            await self._notify_observers("actual_changed", module, state)

            # Handle crash: if crashed but user wanted it enabled, we might retry
            if state == ModuleState.CRASHED and self._desired_state.get(module):
                await self._notify_observers("crash_detected", module)

    async def _reconcile(self, module: str) -> None:
        """Ensure actual state matches desired state."""
        desired = self._desired_state.get(module, False)
        actual = self._actual_state.get(module, ModuleState.DISABLED)

        if desired and actual in (ModuleState.DISABLED, ModuleState.CRASHED):
            # Need to start
            await self._notify_observers("start_requested", module)
        elif not desired and actual not in (ModuleState.DISABLED, ModuleState.STOPPING):
            # Need to stop
            await self._notify_observers("stop_requested", module)
```

#### 2. Observer Pattern for Synchronization

Instead of multiple components reading/writing state independently, they observe and react:

```python
# Observers:
1. ConfigPersistenceObserver - Writes enabled state to config.txt when desired changes
2. UIObserver - Updates checkbox when desired or actual state changes
3. ProcessManagerObserver - Starts/stops processes when start/stop requested
4. SessionRecoveryObserver - Updates running_modules.json when actual state changes
```

#### 3. Deferred State File Deletion

Don't delete `running_modules.json` until modules are actually running:

```python
async def _load_enabled_modules(self) -> None:
    if STATE_FILE.exists():
        state = load_state_file()
        running_modules = state.get('running_modules', [])

        for module_name in running_modules:
            self.state_manager.set_desired_state(module_name, True)

        # DON'T delete yet - wait until startup complete
        self._pending_state_file_cleanup = True

async def on_startup_complete(self) -> None:
    """Called after auto_start_modules finishes."""
    if self._pending_state_file_cleanup:
        # Verify modules actually started
        all_started = all(
            self.state_manager.get_actual_state(m) in RUNNING_STATES
            for m in self._startup_modules
        )
        if all_started:
            STATE_FILE.unlink()
            self._pending_state_file_cleanup = False
```

#### 4. Config File Role Clarification

The `config.txt` `enabled` field should represent "user preference for next fresh start", NOT "should auto-restart on crash recovery":

- When user toggles checkbox: Update `config.txt` `enabled` field
- On crash recovery: Use `running_modules.json`, NOT config files
- On fresh start (no running_modules.json): Use `config.txt` `enabled` fields

#### 5. Atomic State Transitions

```python
async def toggle_module(self, module_name: str, enabled: bool) -> bool:
    """Atomically change module state."""
    async with self._transition_lock:
        # 1. Update desired state (notifies observers)
        await self.state_manager.set_desired_state(module_name, enabled)

        # 2. Wait for actual state to match (with timeout)
        try:
            await asyncio.wait_for(
                self._wait_for_state_match(module_name),
                timeout=30.0
            )
            return True
        except asyncio.TimeoutError:
            # Rollback desired state if we couldn't achieve it
            await self.state_manager.set_desired_state(module_name, not enabled)
            return False
```

#### 6. Periodic Health Check

```python
async def _health_check_loop(self) -> None:
    """Periodically verify module processes are healthy."""
    while not self._shutdown:
        await asyncio.sleep(5.0)  # Check every 5 seconds

        for module_name, process in self.module_processes.items():
            if not process.is_alive():
                actual = self.state_manager.get_actual_state(module_name)
                if actual not in (ModuleState.DISABLED, ModuleState.STOPPING):
                    self.logger.warning("Module %s died unexpectedly", module_name)
                    await self.state_manager.update_actual_state(
                        module_name, ModuleState.CRASHED
                    )
```

---

## Implementation Plan

### Phase 1: State Manager Foundation
1. Create `ModuleStateManager` class with desired/actual state tracking
2. Add observer registration and notification
3. Migrate `module_enabled_state` usage to state manager

### Phase 2: Observer Implementation
1. Implement `ConfigPersistenceObserver` for config.txt sync
2. Implement `UIObserver` for checkbox sync
3. Implement `SessionRecoveryObserver` for running_modules.json sync

### Phase 3: Process Management Integration
1. Connect `ModuleProcess` state changes to state manager
2. Implement reconciliation loop
3. Add health check loop

### Phase 4: Startup/Shutdown Flow
1. Fix state file deletion timing
2. Implement proper startup verification
3. Ensure atomic shutdown state persistence

### Phase 5: GUI Synchronization
1. Make checkbox updates immediate and synchronous
2. Add visual feedback for state transitions
3. Handle error states in UI

---

## State Transition Diagram

```
                    ┌──────────────────────────────────────────┐
                    │                                          │
                    ▼                                          │
    ┌───────────┐  start   ┌──────────┐  started  ┌──────┐    │
    │ DISABLED  │─────────▶│ STARTING │──────────▶│ IDLE │    │
    └───────────┘          └──────────┘           └──────┘    │
          ▲                      │                    │       │
          │                      │ failed             │record │
          │                      ▼                    ▼       │
          │                ┌─────────┐          ┌───────────┐ │
          │                │  ERROR  │          │ RECORDING │ │
          │                └─────────┘          └───────────┘ │
          │                      │                    │       │
          │                      │                    │pause  │
          │   stop               │                    │       │
          └──────────────────────┴────────────────────┴───────┘
                                 │
                                 │ crash
                                 ▼
                           ┌─────────┐
                           │ CRASHED │
                           └─────────┘
```

---

## File Changes Summary

| File | Changes |
|------|---------|
| `rpi_logger/core/module_state_manager.py` | NEW - Central state management |
| `rpi_logger/core/module_manager.py` | Delegate to state manager |
| `rpi_logger/core/logger_system.py` | Use state manager, fix startup flow |
| `rpi_logger/core/ui/main_controller.py` | Observe state manager |
| `rpi_logger/core/ui/main_window.py` | Observe state manager for checkboxes |
| `rpi_logger/core/observers/*.py` | NEW - Observer implementations |

---

## Questions to Resolve

1. Should crashed modules auto-restart? (Currently: no)
2. What's the retry policy for failed starts?
3. Should we show a "module is starting..." indicator in UI?
4. How long to wait before declaring a start "failed"?

---

## Implementation Summary

The architecture has been implemented with the following components:

### New Files Created

| File | Purpose |
|------|---------|
| `rpi_logger/core/module_state_manager.py` | Central state management with observer pattern |
| `rpi_logger/core/observers/__init__.py` | Observer package exports |
| `rpi_logger/core/observers/config_persistence.py` | Persists enabled state to config.txt |
| `rpi_logger/core/observers/session_recovery.py` | Manages running_modules.json |
| `rpi_logger/core/observers/ui_state.py` | Updates UI checkboxes automatically |

### Modified Files

| File | Changes |
|------|---------|
| `rpi_logger/core/module_manager.py` | Now uses ModuleStateManager, observer pattern |
| `rpi_logger/core/logger_system.py` | Creates and wires observers, new startup flow |
| `rpi_logger/core/ui/main_window.py` | Registers checkboxes with UIStateObserver |
| `rpi_logger/core/ui/main_controller.py` | Calls on_startup_complete() |
| `rpi_logger/core/cli/headless_controller.py` | Calls on_startup_complete() |
| `rpi_logger/core/__init__.py` | Exports new state management classes |

### Key Design Decisions

1. **Single Source of Truth**: `ModuleStateManager` owns all state
2. **Observer Pattern**: Components subscribe to state changes instead of polling
3. **Deferred Cleanup**: `running_modules.json` deleted only after startup succeeds
4. **Health Check Loop**: Periodic verification that processes match expected state
5. **Atomic Transitions**: State changes wait for actual state to match desired

### State Flow

```
User Action (checkbox toggle)
    ↓
MainController.on_module_menu_toggle()
    ↓
LoggerSystem.set_module_enabled()
    ↓
ModuleStateManager.set_desired_state()
    ↓
[Notifies observers]
    ├── ConfigPersistenceObserver → writes to config.txt
    ├── UIStateObserver → updates checkbox
    └── ModuleManager (via START_REQUESTED event)
           ↓
        _start_module_process()
           ↓
        ModuleStateManager.set_actual_state(IDLE)
           ↓
        [Notifies observers]
            └── SessionRecoveryObserver → updates running_modules.json
```
