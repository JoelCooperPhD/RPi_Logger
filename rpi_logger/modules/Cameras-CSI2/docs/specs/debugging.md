# Debugging Infrastructure

> Logging, trace IDs, and metrics for troubleshooting

## The Case for Command Trace IDs

**The current system already has trace IDs** (`command_id`) but doesn't leverage them effectively.

**Current state**:
```python
command_id = command.get("command_id")
# ... later ...
StatusMessage.send("device_ready", {"device_id": device_id}, command_id=command_id)
```

**The problem**: These IDs exist but:
- Not consistently used in all commands/responses
- Not logged in a way that enables tracing
- No tooling to correlate command → response
- When things fail, you read entire logs hoping to find the issue

---

## Trace ID Contract

**Every command MUST have a `command_id`**:
```json
{
  "command": "start_recording",
  "command_id": "rec_20260106_143052_001",
  "session_dir": "/data/session_xxx",
  "trial_number": 1
}
```

**Every response MUST reference the `command_id`**:
```json
{
  "status": "recording_started",
  "in_reply_to": "rec_20260106_143052_001",
  "video_path": "/data/session_xxx/CSICameras/..."
}
```

**ID Format**: `{action}_{timestamp}_{sequence}`
- Human-readable, grep-friendly
- Timestamp enables rough ordering
- Sequence handles rapid commands

---

## Structured Command Log

All commands and responses written to a dedicated JSONL log:

**File**: `logs/commands.jsonl`

**Format** (one JSON object per line):
```json
{"ts": 1704567890.123, "dir": "in", "cmd": "start_recording", "id": "rec_001", "payload": {...}}
{"ts": 1704567890.456, "dir": "out", "status": "recording_started", "reply_to": "rec_001", "payload": {...}}
```

**Benefits**:
- `grep rec_001 commands.jsonl` shows entire command lifecycle
- `jq 'select(.dir=="in")' commands.jsonl` shows all inbound commands
- Easy to write analysis scripts
- Can replay commands for testing

---

## Command Lifecycle Logging

Every command goes through defined states:

```
RECEIVED → PROCESSING → COMPLETED/FAILED
```

Log entry at each transition:
```json
{"ts": 1704567890.123, "id": "rec_001", "state": "received", "cmd": "start_recording"}
{"ts": 1704567890.234, "id": "rec_001", "state": "processing"}
{"ts": 1704567890.456, "id": "rec_001", "state": "completed", "duration_ms": 333}
```

**Timeout detection becomes trivial**:
```bash
# Find commands that were received but never completed
jq -s 'group_by(.id) | map(select(all(.state != "completed")))' commands.jsonl
```

---

## Frame Drop Log

Separate log for frame drops (high-frequency events that shouldn't pollute main log):

**File**: `logs/frame_drops.jsonl`

**Format**:
```json
{"ts": 1704567890.123, "mono_ns": 123456789, "reason": "buffer_full", "frame_num": 1234}
{"ts": 1704567890.456, "mono_ns": 123789012, "reason": "gate_skip", "frame_num": 1235}
```

**Drop reasons**:
- `buffer_full` - Ring buffer was full
- `gate_skip` - TimingGate rejected (expected for FPS control)
- `timeout` - Frame took too long to process

**Analysis**:
```bash
# Count drops by reason
jq -s 'group_by(.reason) | map({reason: .[0].reason, count: length})' frame_drops.jsonl
```

---

## Debug Tap (Optional Unix Socket)

For live debugging, mirror all stdio to a Unix socket:

**Enable**: `--debug-socket /tmp/csi_debug.sock`

**Usage**:
```bash
# Terminal 1: Run module with debug tap
python -m rpi_logger.modules.CSICameras --debug-socket /tmp/csi_debug.sock

# Terminal 2: Watch live traffic
socat - UNIX-CONNECT:/tmp/csi_debug.sock
```

---

## Metrics Endpoint (Optional HTTP)

For dashboards and monitoring, optional read-only HTTP endpoint:

**Enable**: `--metrics-port 9100`

**Endpoints**:
```
GET /metrics         -> Prometheus format
GET /metrics/json    -> JSON format
GET /health          -> Health check
```

**Example JSON response**:
```json
{
  "capture_fps": 60.2,
  "record_fps": 30.0,
  "preview_fps": 5.1,
  "frames_captured": 10234,
  "frames_recorded": 5117,
  "frames_dropped": 0,
  "recording": true,
  "uptime_seconds": 3600
}
```

**Note**: This does NOT affect the capture path. It's read-only status reporting.

---

## Log Rotation

All log files use rotation to prevent unbounded growth:

| Log File | Max Size | Backups | Total Max |
|----------|----------|---------|-----------|
| `csicameras.log` | 10 MB | 5 | 50 MB |
| `commands.jsonl` | 5 MB | 3 | 15 MB |
| `frame_drops.jsonl` | 5 MB | 3 | 15 MB |

---

## Testing Commands

Standalone commands for testing without full logger:

```bash
# Test CSI camera 0 with debug output
cd /home/rs-pi-2/Development/Logger
PYTHONPATH=. python3 -m rpi_logger.modules.Cameras-CSI2 \
    --camera-index 0 \
    --console \
    --debug-socket /tmp/csi_debug.sock

# Run with metrics endpoint
PYTHONPATH=. python3 -m rpi_logger.modules.Cameras-CSI2 \
    --camera-index 0 \
    --metrics-port 9100
```

---

## Debugging Flow

**When something goes wrong**:

1. **Identify the command**: `grep <command_id> logs/commands.jsonl`
2. **Check command lifecycle**: Did it complete? How long did it take?
3. **Check for errors**: `grep -i error logs/csicameras.log | tail -20`
4. **Check frame drops**: `wc -l logs/frame_drops.jsonl` (any drops?)
5. **Live debugging**: Connect to debug socket if running

**Complexity assessment**: Adding trace IDs and structured logging **simplifies** debugging because:
- The infrastructure already exists (just needs consistent use)
- grep/jq become powerful debugging tools
- No need to read entire logs hoping to spot issues
- Timeout and orphan detection become trivial
- Replay testing becomes possible
