# Command Protocol Specification

## Command Format

Commands are received via `handle_command(command: str, payload: dict)`.

---

## Device Commands

### assign_device

Assign a camera to this runtime instance.

```python
command = "assign_device"
payload = {
    "camera_id": {
        "backend": "usb",
        "stable_id": "usb-0000:00:14.0-2"
    },
    "descriptor": {
        "name": "Logitech C920",
        "device_path": "/dev/video0",
        "usb_path": "1-2"
    }
}
```

**Response status**: `"device_ready"` or `"device_error"`

### unassign_device

Release the assigned camera.

```python
command = "unassign_device"
payload = {}
```

**Response status**: `"device_released"`

### unassign_all_devices

Release all devices (bulk operation).

```python
command = "unassign_all_devices"
payload = {}
```

---

## Recording Commands

### start_recording / record

Begin video capture to file.

```python
command = "start_recording"
payload = {
    "session_prefix": "session_001",
    "trial_number": 1,
    "output_dir": "/data/recordings"  # Optional override
}
```

**Response status**: `"recording_started"` with paths:
```python
{
    "status": "recording_started",
    "video_path": "/data/recordings/session_001_camera.avi",
    "timing_path": "/data/recordings/session_001_camera_timing.csv"
}
```

### stop_recording / pause / pause_recording

Stop video capture.

```python
command = "stop_recording"
payload = {}
```

**Response status**: `"recording_stopped"` with stats:
```python
{
    "status": "recording_stopped",
    "frames_recorded": 1847,
    "duration_seconds": 61.57,
    "actual_fps": 29.98
}
```

### resume_recording

Resume paused recording (same session).

```python
command = "resume_recording"
payload = {}
```

---

## Session Commands

### start_session

Mark session boundary (for metadata).

```python
command = "start_session"
payload = {
    "session_id": "exp_2024_01_15_001"
}
```

### stop_session

End session boundary.

```python
command = "stop_session"
payload = {}
```

---

## Configuration Commands

### apply_config

Apply new camera settings.

```python
command = "apply_config"
payload = {
    "preview_resolution": [640, 480],
    "preview_fps": 15,
    "record_resolution": [1920, 1080],
    "record_fps": 30,
    "controls": {
        "brightness": 128,
        "contrast": 32,
        "exposure_auto": 1
    }
}
```

### control_change

Change single camera control.

```python
command = "control_change"
payload = {
    "control": "brightness",
    "value": 140
}
```

### reprobe

Re-discover camera capabilities.

```python
command = "reprobe"
payload = {}
```

---

## Status Messages

Runtime sends status updates via callback or event.

| Status | Meaning | Payload |
|--------|---------|---------|
| `ready` | Runtime initialized | `{}` |
| `device_ready` | Camera assigned | `{"camera_id": ...}` |
| `device_error` | Assignment failed | `{"error": "..."}` |
| `device_released` | Camera unassigned | `{}` |
| `recording_started` | Recording begun | `{"video_path": ..., "timing_path": ...}` |
| `recording_stopped` | Recording ended | `{"frames_recorded": ..., "duration": ...}` |
| `error` | Runtime error | `{"error": "...", "recoverable": bool}` |
| `disk_low` | Disk space warning | `{"free_gb": ...}` |

---

## Error Responses

Errors are reported via status message:

```python
{
    "status": "error",
    "command": "start_recording",
    "error": "No camera assigned",
    "recoverable": True
}
```
