# Device Connection State Management - Refactor Plan

## Current Problem

When a user clicks on a device (e.g., `DRT(USB):ACM0`) to connect or disconnect, the status indicator (light) should accurately reflect the state of the module process. Currently, the system has race conditions and gaps in state tracking that cause:

1. **Stuck on yellow (CONNECTING)**: User clicks to connect, light goes yellow, but never turns green even though the module is running
2. **Immediate reconnect failure**: User closes module window, immediately clicks to reconnect - light goes yellow but module doesn't start because the old process is still shutting down
3. **False green**: Light turns green before module has actually connected to the device
4. **No recovery**: If something fails during connection, the light may stay yellow forever

## Desired Behavior

### Visual States
- **Off (dark)**: Device discovered but not connected, module not running
- **Yellow (CONNECTING)**: Connection in progress - module starting up or shutting down
- **Green (CONNECTED)**: Module running and device successfully assigned

### User Interactions
1. **Click on disconnected device (dark)** → Yellow → Green (or back to dark on failure)
2. **Click on connected device (green)** → Yellow → Dark (module shuts down)
3. **Click on connecting device (yellow)** → Cancel attempt → Dark
4. **Close module window via X button** → Yellow → Dark

### Timing Expectations
- Yellow → Green: Should happen within 1-2 seconds on success
- Yellow → Dark (on failure): Should happen within 2-3 seconds
- Yellow should never persist more than 5 seconds without resolution

---

## Current Architecture

### Components Involved

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Main Logger Process                          │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  ┌──────────────┐    ┌──────────────────┐    ┌───────────────────┐  │
│  │ DevicesPanel │───▶│ DeviceUIController│───▶│ DeviceSelectionModel│
│  │   (UI)       │    │                  │    │  (State: DISCOVERED,│
│  │              │    │                  │    │   CONNECTING,       │
│  │ StatusIndicator   │                  │    │   CONNECTED, ERROR) │
│  │ (off/yellow/green)│                  │    │                     │
│  └──────────────┘    └──────────────────┘    └───────────────────┘  │
│         │                                              ▲             │
│         │ click                                        │             │
│         ▼                                              │             │
│  ┌──────────────────────────────────────────────────────┐           │
│  │                   LoggerSystem                        │           │
│  │                                                       │           │
│  │  - connect_and_start_device(device_id)               │           │
│  │  - stop_and_disconnect_device(device_id)             │           │
│  │  - start_module_instance(module_id, instance_id)     │           │
│  │  - _module_status_callback(process, status)          │           │
│  │  - _gracefully_quitting_modules: set                 │           │
│  │  - _device_instance_map: dict                        │           │
│  └──────────────────────────────────────────────────────┘           │
│         │                                              ▲             │
│         │ subprocess                                   │ stdout      │
│         │ stdin (commands)                             │ (status)    │
│         ▼                                              │             │
├─────────────────────────────────────────────────────────────────────┤
│                       Module Process (e.g., DRT)                     │
├─────────────────────────────────────────────────────────────────────┤
│  ┌──────────────────────────────────────────────────────┐           │
│  │                  ModuleProcess                        │           │
│  │  - Wraps subprocess                                   │           │
│  │  - Reads stdout for StatusMessage JSON               │           │
│  │  - Writes stdin for CommandMessage JSON              │           │
│  └──────────────────────────────────────────────────────┘           │
│         │                                                            │
│         ▼                                                            │
│  ┌──────────────────────────────────────────────────────┐           │
│  │              DRTModuleRuntime                         │           │
│  │  - handle_command("assign_device", ...)              │           │
│  │  - Creates transport, handler                         │           │
│  │  - StatusMessage.send("device_ready", {device_id})   │           │
│  │  - StatusMessage.send("device_error", {device_id})   │           │
│  │  - StatusMessage.send("quitting")                    │           │
│  └──────────────────────────────────────────────────────┘           │
└─────────────────────────────────────────────────────────────────────┘
```

### Current Message Flow

#### Connect Flow (User clicks dark indicator)
```
1. User clicks device row
2. DevicesPanel._on_click()
   → calls on_toggle_connect(True)
3. DeviceUIController._handle_device_connect_toggle()
   → calls _on_connect_device callback
4. LoggerSystem.connect_and_start_device(device_id)
   → _notify_device_connecting(device_id)  # Light → Yellow
   → start_module_instance(module_id, instance_id, device)
      → module_manager.start_module_instance()  # Spawns subprocess
      → module_manager.send_command(assign_device)  # Sends to stdin
      → _notify_device_connected(device_id, True)  # Light → Green (IMMEDIATELY)
5. Module process starts, receives assign_device
   → Creates transport, connects to hardware
   → StatusMessage.send("device_ready", {device_id})  # Sent to stdout
6. LoggerSystem._module_status_callback receives "device_ready"
   → _notify_device_connected(device_id, True)  # Already green, no change
```

**Problem**: Step 4 sets green immediately before module confirms. If module fails, light stays green.

#### Disconnect Flow (User clicks green indicator)
```
1. User clicks device row
2. DevicesPanel._on_click()
   → calls on_toggle_connect(False)
3. LoggerSystem.stop_and_disconnect_device(device_id)
   → stop_module_instance(instance_id)
      → module_manager.stop_module_instance()  # Sends quit command
   → _notify_device_connected(device_id, False)  # Light → Dark (IMMEDIATELY)
4. Module receives quit command
   → Cleans up, closes handlers
   → StatusMessage.send("quitting")
   → Process exits
5. LoggerSystem._module_status_callback receives "quitting"
   → Adds to _gracefully_quitting_modules
6. ModuleProcess detects process exit
   → Callback fires with status=None
   → Removes from _gracefully_quitting_modules
```

**Problem**: Light goes dark at step 3, but module is still running until step 6.

#### Window Close Flow (User clicks X on module window)
```
1. User clicks X button on module window
2. Module's Tkinter handles WM_DELETE_WINDOW
   → Initiates shutdown
   → StatusMessage.send("quitting")
   → Process exits
3. LoggerSystem._module_status_callback receives "quitting"
   → _gracefully_quitting_modules.add(instance_id)
   → _notify_instance_disconnected(instance_id)
      → _notify_device_connected(device_id, False)  # Light → Dark
4. ModuleProcess detects process exit
   → Removes from _gracefully_quitting_modules
```

**Problem**: Between steps 2 and 4, if user clicks to reconnect, the old instance is still in `_gracefully_quitting_modules` but `is_module_running()` may return False (process exited but not cleaned up yet), causing confusion.

---

## Root Causes

### 1. State is Distributed and Inconsistent
- `DeviceSelectionModel` tracks UI state (DISCOVERED, CONNECTING, CONNECTED)
- `_gracefully_quitting_modules` tracks shutdown state
- `ModuleProcess.is_running()` tracks process state
- `_device_instance_map` tracks device-to-instance mapping
- These can get out of sync

### 2. No Single Source of Truth for Instance Lifecycle
The lifecycle of a module instance has these states:
```
STOPPED → STARTING → RUNNING → STOPPING → STOPPED
```
But this isn't explicitly tracked. Instead, we infer from:
- `module_manager.is_module_running()` - process exists and running
- `_gracefully_quitting_modules` - received "quitting" status
- Process exit detection - callback when process terminates

### 3. Optimistic UI Updates
The UI is updated before operations complete:
- Green before module confirms device connection
- Dark before module finishes shutting down

### 4. Race Conditions Between Processes
- Module sends status message via stdout
- Logger reads it asynchronously
- Timing depends on process scheduling, buffering, etc.
- Messages can be lost if sent before logger is ready to receive

### 5. No Acknowledgement Protocol
Commands are fire-and-forget:
- Logger sends `assign_device` command
- No guarantee module received it
- No guarantee module will respond
- No timeout handling

---

## Proposed Refactor

### Phase 1: Explicit Instance Lifecycle State

Create a centralized state machine for each module instance:

```python
class InstanceState(Enum):
    """Lifecycle state of a module instance."""
    STOPPED = "stopped"           # Not running
    STARTING = "starting"         # Process spawned, waiting for ready
    RUNNING = "running"           # Process running, no device assigned
    CONNECTING = "connecting"     # Device assignment sent, waiting for ack
    CONNECTED = "connected"       # Device connected and ready
    DISCONNECTING = "disconnecting"  # Unassign sent, waiting for ack
    STOPPING = "stopping"         # Quit sent, waiting for exit

class InstanceInfo:
    """Tracks the complete state of a module instance."""
    instance_id: str
    device_id: Optional[str]
    state: InstanceState
    state_entered_at: float  # For timeout detection
    process: Optional[ModuleProcess]
```

### Phase 2: State Transitions with Timeouts

Each state transition has:
1. An **action** that triggers the transition
2. An **expected confirmation** from the module
3. A **timeout** if confirmation doesn't arrive
4. A **fallback** action on timeout

```
STOPPED --[start_instance]--> STARTING
    Expected: process spawns successfully
    Timeout: 5s → STOPPED (failed to start)

STARTING --[process running + ready signal]--> RUNNING
    Expected: module sends "ready" status
    Timeout: 5s → STOPPED (kill process)

RUNNING --[assign_device]--> CONNECTING
    Expected: module sends "device_ready"
    Timeout: 3s → check if process alive, retry or fail

CONNECTING --[device_ready received]--> CONNECTED

CONNECTED --[unassign_device]--> DISCONNECTING
    Expected: module sends "device_unassigned"
    Timeout: 2s → proceed to RUNNING anyway

CONNECTED --[quit command]--> STOPPING
    Expected: module sends "quitting" then exits
    Timeout: 5s → kill process

STOPPING --[process exit]--> STOPPED

Any State --[process crash]--> STOPPED
```

### Phase 3: Status Messages from Module

Standardize the status messages modules send:

```python
# Module startup
StatusMessage.send("ready")  # Module initialized, ready for commands

# Device assignment
StatusMessage.send("device_ready", {"device_id": "ACM0"})
StatusMessage.send("device_error", {"device_id": "ACM0", "error": "..."})

# Device unassignment
StatusMessage.send("device_unassigned", {"device_id": "ACM0"})

# Shutdown
StatusMessage.send("quitting")  # Clean shutdown initiated
```

### Phase 4: Command Acknowledgement

Add optional ack for critical commands:

```python
# Logger sends command with request_id
command = CommandMessage.assign_device(
    device_id="ACM0",
    request_id="req_123",  # New field
    ...
)

# Module responds with ack
StatusMessage.send("command_ack", {
    "request_id": "req_123",
    "success": True,
    "error": None
})
```

### Phase 5: Instance State Manager

New component to centralize instance lifecycle:

```python
class InstanceStateManager:
    """Manages lifecycle state for all module instances."""

    def __init__(self, logger_system: LoggerSystem):
        self._instances: Dict[str, InstanceInfo] = {}
        self._state_observers: List[Callable] = []

    async def start_instance(self, instance_id: str, device: DeviceInfo) -> bool:
        """Start an instance and wait for it to be ready."""
        # Set state to STARTING
        # Spawn process
        # Wait for "ready" with timeout
        # Transition to RUNNING or STOPPED

    async def connect_device(self, instance_id: str, device: DeviceInfo) -> bool:
        """Assign device to instance and wait for connection."""
        # Set state to CONNECTING
        # Send assign_device command
        # Wait for "device_ready" with timeout
        # Transition to CONNECTED or back to RUNNING

    async def stop_instance(self, instance_id: str) -> bool:
        """Stop an instance and wait for exit."""
        # Set state to STOPPING
        # Send quit command
        # Wait for process exit with timeout
        # Kill if needed
        # Transition to STOPPED

    def on_status_message(self, instance_id: str, status: StatusMessage):
        """Handle status message from module."""
        # Update state based on message
        # Notify observers

    def on_process_exit(self, instance_id: str):
        """Handle process termination."""
        # Transition to STOPPED
        # Notify observers

    def get_ui_state(self, device_id: str) -> ConnectionState:
        """Get the UI state for a device."""
        # Map instance state to UI state:
        # STOPPED → DISCOVERED
        # STARTING, RUNNING, CONNECTING → CONNECTING
        # CONNECTED → CONNECTED
        # DISCONNECTING, STOPPING → CONNECTING
```

### Phase 6: UI State Derivation

UI state derived from instance state, not set directly:

```python
def _update_ui_state(self, instance_id: str):
    """Update UI based on instance state."""
    info = self._instances.get(instance_id)
    if not info or not info.device_id:
        return

    device_id = info.device_id

    if info.state == InstanceState.CONNECTED:
        self.device_system.set_device_connected(device_id, True)
    elif info.state == InstanceState.STOPPED:
        self.device_system.set_device_connected(device_id, False)
    else:
        # All transitional states show as CONNECTING (yellow)
        self.device_system.set_device_connecting(device_id)
```

---

## Implementation Steps

### Step 1: Add InstanceState and InstanceInfo
- Create new file: `rpi_logger/core/instance_state.py`
- Define `InstanceState` enum
- Define `InstanceInfo` dataclass
- Add state transition validation

### Step 2: Create InstanceStateManager
- Create new file: `rpi_logger/core/instance_manager.py`
- Implement state machine logic
- Add timeout handling with asyncio
- Add observer pattern for state changes

### Step 3: Update ModuleManager
- Add "ready" status emission on module startup
- Ensure "quitting" is always sent on shutdown
- Add process exit detection callback

### Step 4: Update Module Runtimes (DRT, VOG, Audio)
- Emit "ready" on successful initialization
- Emit "device_ready" on successful device connection
- Emit "device_error" on device connection failure
- Ensure "quitting" is sent before exit

### Step 5: Integrate InstanceStateManager into LoggerSystem
- Replace direct `_notify_device_connected` calls
- Replace `_gracefully_quitting_modules` tracking
- Use InstanceStateManager for all state queries

### Step 6: Update UI State Derivation
- DeviceSelectionModel state derived from InstanceStateManager
- Remove direct state setting from LoggerSystem
- Add observer to update UI on state changes

### Step 7: Add Timeout Handling
- Background task to check for stale states
- Configurable timeouts per state transition
- Automatic recovery (retry or fail)

### Step 8: Testing
- Unit tests for state transitions
- Integration tests for connect/disconnect flows
- Race condition tests (rapid click, close+reopen)
- Timeout tests (module hangs, process crash)

---

## Files to Modify

### New Files
- `rpi_logger/core/instance_state.py` - State enum and info class
- `rpi_logger/core/instance_manager.py` - State manager

### Modified Files
- `rpi_logger/core/logger_system.py` - Use InstanceStateManager
- `rpi_logger/core/module_manager.py` - Add ready detection, exit callbacks
- `rpi_logger/core/devices/selection.py` - State derived from instance manager
- `rpi_logger/core/devices/device_system.py` - Integrate with instance manager
- `rpi_logger/modules/DRT/drt/runtime.py` - Add "ready" status
- `rpi_logger/modules/VOG/vog/runtime.py` - Add "ready" status
- `rpi_logger/modules/Audio/runtime/adapter.py` - Add "ready" status

---

## Success Criteria

1. **No stuck states**: Yellow never persists more than 5 seconds
2. **Accurate indication**: Green only when device is truly connected
3. **Rapid toggle works**: Close window, immediately reopen - works reliably
4. **Cancel works**: Click yellow to cancel pending connection
5. **Crash recovery**: Module crash → light goes dark within 2 seconds
6. **Startup recovery**: Module fails to start → light goes dark with error
7. **Logs are clear**: State transitions logged for debugging
