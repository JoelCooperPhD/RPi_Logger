# Parent Process Control - Camera Module

## Overview

The camera module can run in two modes:

1. **Standalone Mode**: User interacts directly with the GUI (default)
2. **Parent-Controlled Mode**: Parent process controls the module via JSON commands

This document explains how the parent-controlled mode works and how to integrate it.

## Architecture

### Threading/Async Model

The camera module uses a **single async event loop** running in the main thread:

```
Main Thread (Async Event Loop)
├─ Task 1: GUI updates (100 Hz) - via tkinter root.update()
├─ Task 2: Camera preview updates (10 Hz)
└─ Task 3: Command listener (when parent communication enabled)

Camera I/O: Async tasks in same event loop
Tkinter: Runs in main thread via root.update() (safe)
```

**Thread Safety Guarantees:**
- ✓ All async tasks run in single event loop (no race conditions)
- ✓ Tkinter updates only from main thread (GUI-safe)
- ✓ No blocking calls in async context
- ✓ Frame cache uses atomic reference assignment (lock-free)
- ✓ Commands execute sequentially (no concurrent access)

## Enabling Parent Communication

### Auto-Detection (Recommended)

The module automatically detects when stdin is piped from a parent process:

```bash
# Parent launches module with pipe - command mode auto-enabled
echo '{"command": "get_status"}' | python main_camera.py --mode gui

# Or via subprocess in parent:
process = subprocess.Popen(
    ["python", "main_camera.py", "--mode", "gui"],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    text=True
)
```

### Explicit Enable

You can explicitly enable command mode:

```bash
python main_camera.py --mode gui --enable-commands
```

### Detection Logic

```python
# In camera_system.py
enable_commands = args.enable_commands or (mode == "gui" and not sys.stdin.isatty())
```

If stdin is:
- **TTY** (terminal): Standalone mode (no commands)
- **Pipe/File**: Parent-controlled mode (commands enabled)

## Communication Protocol

### Commands (Parent → Camera)

Commands are JSON objects sent to stdin, one per line:

```json
{"command": "start_recording"}
{"command": "stop_recording"}
{"command": "take_snapshot"}
{"command": "get_status"}
{"command": "toggle_preview", "camera_id": 0, "enabled": true}
{"command": "quit"}
```

### Status Messages (Camera → Parent)

Status updates are JSON objects sent to stdout, one per line:

```json
{"type": "initialized", "data": {"cameras": 2, "session": "session_20251014_123456"}}
{"type": "recording_started", "data": {"session": "...", "files": ["..."]}}
{"type": "recording_stopped", "data": {"session": "...", "files": ["..."]}}
{"type": "snapshot_taken", "data": {"files": ["..."]}}
{"type": "status_report", "data": {...}}
{"type": "error", "data": {"message": "..."}}
{"type": "quitting"}
```

## Example Parent Implementation

See `example_parent_control.py` for a complete working example.

### Basic Pattern

```python
import subprocess
import json

# Launch camera module
process = subprocess.Popen(
    ["python", "main_camera.py", "--mode", "gui"],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    text=True,
    bufsize=1  # Line buffered
)

# Send command
command = {"command": "get_status"}
process.stdin.write(json.dumps(command) + "\n")
process.stdin.flush()

# Read response
response_line = process.stdout.readline()
response = json.loads(response_line)
print(f"Status: {response}")

# Shutdown
command = {"command": "quit"}
process.stdin.write(json.dumps(command) + "\n")
process.stdin.flush()
process.wait(timeout=10)
```

## GUI State Synchronization

When commands are received from parent, the GUI automatically updates:

- **start_recording**: Window title shows "⬤ RECORDING", camera toggles disabled
- **stop_recording**: Window title returns to normal, camera toggles enabled
- **quit**: Window closes, process exits cleanly

This is handled by `_sync_gui_recording_state()` in `gui_mode.py`.

## Process Lifecycle

### Parent Responsibilities

1. **Launch**: Start camera module as subprocess with stdin/stdout pipes
2. **Initialize**: Wait for "initialized" status message (cameras ready)
3. **Control**: Send commands as needed
4. **Monitor**: Read status messages from stdout
5. **Shutdown**: Send "quit" command, wait for process to exit
6. **Cleanup**: Kill process if it doesn't exit gracefully

### Camera Module Lifecycle

1. **Startup**: Initialize cameras, create GUI window
2. **Ready**: Send "initialized" status to parent
3. **Running**: Listen for commands, update GUI, process frames
4. **Shutdown**: On "quit" command or EOF on stdin, cleanup and exit

### Graceful Shutdown

```python
# Option 1: Send quit command
send_command(process, {"command": "quit"})
process.wait(timeout=10)

# Option 2: Close stdin (signals EOF)
process.stdin.close()
process.wait(timeout=10)

# Option 3: Send SIGTERM signal
process.terminate()
process.wait(timeout=5)

# Last resort: Kill
if process.poll() is None:
    process.kill()
```

## Multi-Module Parent (Logger Example)

A parent logger can control multiple modules simultaneously:

```python
modules = {
    "cameras": launch_camera_module(),
    "eye_tracker": launch_eye_tracker_module(),
    "sensors": launch_sensor_module(),
}

# User toggles modules on/off
if user_enables_cameras:
    modules["cameras"] = launch_camera_module()
else:
    send_command(modules["cameras"], {"command": "quit"})
    modules["cameras"] = None

# Broadcast commands to all modules
def start_recording_all():
    for module in modules.values():
        if module:
            send_command(module, {"command": "start_recording"})

# Monitor status from all modules
def read_all_status():
    for name, module in modules.items():
        response = read_response(module, timeout=0.1)
        if response:
            print(f"[{name}] {response}")
```

## Error Handling

### Parent Side

```python
try:
    # Send command
    send_command(process, {"command": "start_recording"})

    # Read response with timeout
    response = read_response(process, timeout=5.0)

    if response and response.get("type") == "error":
        print(f"Camera error: {response['data']['message']}")

except subprocess.TimeoutExpired:
    print("Camera module not responding, killing...")
    process.kill()

except BrokenPipeError:
    print("Camera module crashed, restarting...")
    process = launch_camera_module()
```

### Camera Side

- **Invalid JSON**: Sends error status, continues running
- **Unknown command**: Sends error status, continues running
- **Command fails**: Sends error status, continues running
- **stdin EOF**: Initiates graceful shutdown
- **Exception in command handler**: Sends error status, continues running

## Security Considerations

1. **Path Sanitization**: Error messages sanitize file paths before sending to parent
2. **Message Length Limits**: Error messages truncated to prevent information leakage
3. **No Arbitrary Code Execution**: Only predefined commands accepted
4. **Input Validation**: All JSON parsed safely, invalid input rejected

## Performance Characteristics

- **Command Latency**: < 10ms (async processing)
- **GUI Update Sync**: < 100ms (next GUI update cycle)
- **Overhead**: Minimal (<1% CPU) when no commands pending
- **Throughput**: Can process 100+ commands/sec

## Testing

### Standalone Mode Test
```bash
# Should work normally without parent
python main_camera.py --mode gui
```

### Parent-Controlled Mode Test
```bash
# Run example parent controller
python example_parent_control.py
```

### Manual Command Test
```bash
# Send commands manually via stdin
echo '{"command": "get_status"}' | python main_camera.py --mode gui --enable-commands
```

## Debugging

### Enable Console Logging

```bash
python main_camera.py --mode gui --enable-commands --console
```

This shows Python logs in stderr (doesn't interfere with JSON on stdout).

### Check Command Listener Status

Look for log messages:
```
GUIMode: Starting GUI mode with parent command support
GUIMode: Command listener started (parent communication enabled)
```

### Verify JSON Protocol

```bash
# Test commands manually
python main_camera.py --mode gui --enable-commands << EOF
{"command": "get_status"}
{"command": "quit"}
EOF
```

## Comparison with Slave Mode

| Feature | GUI Mode | Slave Mode |
|---------|----------|------------|
| Interface | Tkinter GUI | Optional OpenCV windows |
| Parent Control | Optional (via --enable-commands) | Always enabled |
| User Control | GUI buttons + commands | Commands only |
| Use Case | Interactive + parent-controlled | Headless parent-controlled |
| Preview Quality | High (tkinter, aspect ratio) | Basic (OpenCV) |
| Frame Streaming | No | Yes (base64 over JSON) |

**When to use GUI mode with commands:**
- User wants visual GUI for monitoring
- Parent needs to control recording/snapshots
- Combined human + automated control

**When to use Slave mode:**
- Fully headless operation (no user interaction)
- Need frame streaming to parent
- Minimal resource usage (no tkinter)

## Future Enhancements

Possible additions:
- Expose more GUI controls via commands (camera toggle, settings)
- Status updates on GUI events (user clicks button)
- Bidirectional state sync (parent changes → GUI, GUI changes → parent)
- Performance metrics in status messages
- Live frame streaming (like slave mode)
