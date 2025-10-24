# RPi Logger - Architecture Overview

This is a logger system that will be used in a car. It has 2 interaction modes: GUI or command line. GUI mode launches either through the direct use of any one of the Modules (they are standalone) or through the use of the main logger.

## System Architecture

The RPi Logger follows a **layered architecture** with clear separation of concerns:

```
┌─────────────────────────────────────────────────────┐
│                   main_logger.py                    │
│              (Entry Point & Coordination)           │
└──────────────────────┬──────────────────────────────┘
                       │
           ┌───────────┴───────────┐
           │    LoggerSystem       │
           │     (Facade)          │
           └───────────┬───────────┘
                       │
       ┌───────────────┼───────────────┐
       │               │               │
┌──────▼──────┐ ┌─────▼──────┐ ┌─────▼──────┐
│   Module    │ │  Session   │ │  Window    │
│   Manager   │ │  Manager   │ │  Manager   │
└─────────────┘ └────────────┘ └────────────┘
```

### Core Components

#### 1. **LoggerSystem** (Facade Pattern)
**File:** `logger_core/logger_system.py`

Thin coordinator that provides a unified API to the UI. Delegates all operations to specialized managers.

**Responsibilities:**
- Initialize and coordinate managers
- Provide unified API for UI
- Handle callbacks from modules
- Manage event logging

**Lines of Code:** 377 (reduced from 643 after refactoring)

#### 2. **ModuleManager**
**File:** `logger_core/module_manager.py`

Manages module discovery, selection, and lifecycle.

**Responsibilities:**
- Discover available modules
- Track module selection state
- Start/stop module processes
- Handle module configuration

**Key Methods:**
- `get_available_modules()` - List discovered modules
- `start_module()` - Launch module process
- `stop_module()` - Terminate module process
- `load_enabled_modules()` - Load selection from config

#### 3. **SessionManager**
**File:** `logger_core/session_manager.py`

Controls recording sessions and trials across all modules.

**Responsibilities:**
- Coordinate session start/stop
- Control trial recording
- Track recording state
- Synchronize recording across modules

**Key Methods:**
- `start_session_all()` - Begin session on all modules
- `record_all()` - Start recording trial
- `pause_all()` - Pause recording
- `get_status_all()` - Query module states

#### 4. **ShutdownCoordinator**
**File:** `logger_core/shutdown_coordinator.py`

Ensures graceful, race-condition-free shutdown.

**Responsibilities:**
- Single shutdown entry point
- Execute cleanup callbacks in order
- Prevent duplicate shutdown attempts
- Track shutdown state

**Shutdown Flow:**
1. Trigger → `initiate_shutdown(source)`
2. State: RUNNING → REQUESTED → IN_PROGRESS → COMPLETE
3. Execute registered cleanup callbacks
4. Components cleaned up in correct order

#### 5. **WindowManager**
**File:** `logger_core/window_manager.py`

Handles window layout and geometry.

**Responsibilities:**
- Calculate tiling layouts
- Save/restore window positions
- Manage screen real estate

#### 6. **ConfigManager**
**File:** `logger_core/config_manager.py`

Centralized configuration management with async support.

**Responsibilities:**
- Read/write config files
- Type-safe config access (get_str, get_int, get_bool)
- Async file I/O to avoid blocking

## Path Management

**File:** `logger_core/paths.py`

All paths centralized in one location:

```python
PROJECT_ROOT = Path(__file__).parent.parent
CONFIG_PATH = PROJECT_ROOT / "config.txt"
LOGS_DIR = PROJECT_ROOT / "logs"
DATA_DIR = PROJECT_ROOT / "data"
STATE_FILE = DATA_DIR / "running_modules.json"
```

Benefits:
- Single source of truth
- OS-agnostic paths
- Easy to modify
- No hard-coded path strings

## Async/Await Pattern

The system uses **async initialization** to avoid blocking I/O:

```python
# Synchronous construction
logger_system = LoggerSystem(session_dir, ...)

# Async initialization (must be called)
await logger_system.async_init()
```

**Why?**
- `__init__` cannot be async
- File I/O during init would block event loop
- Async pattern keeps UI responsive

**Blocking I/O Wrapped:**
- All file reads: `await asyncio.to_thread(file_read)`
- All JSON operations: `await asyncio.to_thread(json.load, ...)`
- Config reads: `await config_manager.read_config_async(...)`

## Module Process Lifecycle

```
STOPPED → STARTING → IDLE → RECORDING → IDLE → STOPPED
           ↓                    ↓
         ERROR              ERROR
```

**States:**
- `STOPPED` - Not running
- `STARTING` - Launching process
- `INITIALIZING` - Process started, initializing
- `IDLE` - Ready, not recording
- `RECORDING` - Actively recording data
- `ERROR` - Encountered error
- `CRASHED` - Process terminated unexpectedly

## Shutdown Sequence

**Coordinated via ShutdownCoordinator:**

1. **Trigger Source:** Signal (Ctrl+C), UI button, or exception
2. **Initiation:** `shutdown_coordinator.initiate_shutdown(source)`
3. **State Check:** Prevents duplicate shutdowns
4. **Cleanup Execution:**
   - Stop active sessions/trials
   - Request geometry from modules
   - Stop all module processes
   - Save running modules state
   - Stop UI timers
   - Save window geometry
   - Close UI
5. **Completion:** State → COMPLETE

**Race Condition Prevention:**
- Single coordinator instance
- State machine (RUNNING → REQUESTED → IN_PROGRESS → COMPLETE)
- Lock-protected state transitions
- Duplicate calls ignored

## Configuration Files

### Main Config: `config.txt`

```ini
# Paths
data_dir = data
session_prefix = session

# Logging
log_level = info
console_output = true

# UI
window_x = 100
window_y = 100
window_width = 800
window_height = 600

# Session restore
last_session_dir = /path/to/last/session
```

### Module Configs: `Modules/*/config.txt`

Each module has its own config with:
- `enabled` - Auto-start on launch
- Window geometry
- Module-specific settings

## State Persistence

### Running Modules State
**File:** `data/running_modules.json`

```json
{
  "timestamp": "2025-10-24T12:34:56",
  "running_modules": ["Cameras", "AudioRecorder"]
}
```

**Purpose:** Restore running modules on next launch

**Lifecycle:**
1. Saved on shutdown (if modules running)
2. Loaded on startup
3. Deleted after loading (one-time use)

## Key Design Patterns

1. **Facade Pattern** - LoggerSystem provides unified API
2. **Delegation Pattern** - LoggerSystem delegates to managers
3. **Singleton Pattern** - ShutdownCoordinator global instance
4. **Observer Pattern** - Module status callbacks
5. **State Pattern** - Module process states

## Best Practices Implemented

✅ **Separation of Concerns** - Each component has single responsibility
✅ **Async/Await** - No blocking I/O in async context
✅ **Type Hints** - Full type annotations throughout
✅ **Path Constants** - Centralized path management
✅ **Error Handling** - Comprehensive try/catch blocks
✅ **Logging** - Detailed logging at appropriate levels
✅ **Documentation** - Docstrings on all public methods

## Recent Improvements (Oct 2024)

**Phase 1: Foundation**
- Created centralized path constants (`paths.py`)
- Removed duplicate config loading code
- Consolidated to single ConfigManager

**Phase 2: Async I/O**
- Wrapped all blocking I/O in `asyncio.to_thread()`
- Implemented async initialization pattern
- Made file operations non-blocking

**Phase 3: Shutdown Coordination**
- Created ShutdownCoordinator
- Single shutdown entry point
- Eliminated race conditions

**Phase 4: Architecture Refactor**
- Split LoggerSystem (643→377 lines)
- Created ModuleManager
- Created SessionManager
- Clear separation of concerns

**Phase 5: Polish**
- Added comprehensive documentation
- Verified type hints
- Documented shutdown sequence

## Testing

Run syntax checks:
```bash
python -m py_compile main_logger.py
python -m py_compile logger_core/*.py
```

Launch the logger:
```bash
python main_logger.py
```

## Future Enhancements

- [ ] Unit tests for managers
- [ ] Config validation at startup
- [ ] Metrics collection
- [ ] Performance profiling
- [ ] Module dependency management
