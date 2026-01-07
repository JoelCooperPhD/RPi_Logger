# Command Protocol

> Communication between parent logger and module

## Inbound Commands

Commands sent from parent logger via stdin (JSON, one per line).

| Command | Parameters | Action |
|---------|------------|--------|
| `assign_device` | `device_id`, `camera_type`, `camera_stable_id`, etc. | Initialize camera |
| `unassign_device` | - | Release camera |
| `start_recording` | `session_dir`, `trial_number`, `trial_label` | Begin recording |
| `stop_recording` | - | End recording |
| `start_session` | `session_dir` | Set session directory |
| `stop_session` | - | Stop any recording |

### Command Format

```json
{
  "command": "start_recording",
  "command_id": "rec_20260106_143052_001",
  "session_dir": "/data/session_xxx",
  "trial_number": 1,
  "trial_label": ""
}
```

---

## Outbound Status Messages

Status updates sent to parent logger via stdout (JSON, one per line).

| Status | Payload | When |
|--------|---------|------|
| `ready` | - | Runtime initialized |
| `device_ready` | `device_id` | Camera assigned and first frame captured |
| `device_error` | `device_id`, `error` | Assignment failed |
| `recording_started` | `video_path`, `camera_id` | Recording begun |
| `recording_stopped` | `camera_id` | Recording ended |

### Status Format

```json
{
  "status": "device_ready",
  "in_reply_to": "assign_20260106_143050_001",
  "device_id": "picam:0"
}
```

---

## Trace ID Contract

**Every command MUST have a `command_id`**:
```json
{
  "command": "start_recording",
  "command_id": "rec_20260106_143052_001",
  ...
}
```

**Every response MUST reference the `command_id`**:
```json
{
  "status": "recording_started",
  "in_reply_to": "rec_20260106_143052_001",
  ...
}
```

**ID Format**: `{action}_{timestamp}_{sequence}`
- Human-readable, grep-friendly
- Timestamp enables rough ordering
- Sequence handles rapid commands

---

## Deferred Device Ready

**Critical**: `device_ready` is sent AFTER first frame is successfully captured, not immediately after camera initialization. This prevents the parent from releasing CSI locks too early.

```python
async def _handle_assign_device(self, cmd: dict) -> None:
    command_id = cmd.get("command_id")
    device_id = cmd["device_id"]

    # Initialize camera
    await self._source.start()

    # Wait for first frame
    async for frame in self._source.frames():
        break  # Got first frame

    # NOW send device_ready
    await self._send_status("device_ready", {
        "device_id": device_id
    }, in_reply_to=command_id)
```

---

## Error Handling

When a command fails, send `device_error` or appropriate error status:

```json
{
  "status": "device_error",
  "in_reply_to": "assign_20260106_143050_001",
  "device_id": "picam:0",
  "error": "Camera not found"
}
```
