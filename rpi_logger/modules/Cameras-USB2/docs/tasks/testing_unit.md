# Testing: Unit Tests

## Quick Reference

| Status | Depends On | Effort | Key Specs |
|--------|------------|--------|-----------|
| available | P1.1, P2.1 | Medium | `specs/components.md` |

## Goal

Validate individual components in isolation with mocked dependencies.

---

## Test Modules

### T1. Core Types (`tests/unit/test_types.py`)

| Test | Validates |
|------|-----------|
| `test_camera_id_frozen` | CameraId is immutable |
| `test_camera_id_str` | String representation correct |
| `test_capture_frame_fields` | All fields populated correctly |
| `test_capability_mode_equality` | Mode comparison works |

### T2. USB Backend (`tests/unit/test_usb_backend.py`)

| Test | Validates |
|------|-----------|
| `test_probe_success` | Returns CameraCapabilities |
| `test_probe_device_missing` | Raises ProbeError |
| `test_probe_device_busy` | Raises ProbeError with reason |
| `test_set_control_valid` | Control value applied |
| `test_set_control_out_of_range` | Raises ValueError |
| `test_get_control` | Returns current value |

**Mocking strategy**:
```python
@patch("cv2.VideoCapture")
def test_probe_success(mock_cap):
    mock_cap.return_value.isOpened.return_value = True
    mock_cap.return_value.get.side_effect = [1280, 720, 30]
    result = await probe("/dev/video0")
    assert result.modes[0].width == 1280
```

### T3. USB Capture (`tests/unit/test_capture.py`)

| Test | Validates |
|------|-----------|
| `test_capture_start_stop` | Thread lifecycle correct |
| `test_capture_yields_frames` | AsyncIterator produces CaptureFrame |
| `test_capture_device_lost` | Raises DeviceLost on disconnect |
| `test_capture_queue_bounded` | Queue respects max size |
| `test_capture_actual_fps` | FPS property accurate |

**Mocking strategy**:
```python
@patch("cv2.VideoCapture")
async def test_capture_yields_frames(mock_cap):
    mock_cap.return_value.read.return_value = (True, np.zeros((720, 1080, 3)))
    cap = USBCapture("/dev/video0", 1280, 720, 30)
    await cap.start()
    frame = await anext(cap)
    assert frame.width == 1280
    await cap.stop()
```

### T4. Capabilities (`tests/unit/test_capabilities.py`)

| Test | Validates |
|------|-----------|
| `test_build_capabilities` | Normalization correct |
| `test_select_default_preview` | Picks 640x480 if available |
| `test_select_default_record` | Picks highest resolution MJPG |
| `test_empty_modes` | Returns None defaults |

### T5. Session Paths (`tests/unit/test_session_paths.py`)

| Test | Validates |
|------|-----------|
| `test_resolve_paths_creates_dir` | Output directory created |
| `test_resolve_paths_naming` | Filenames match pattern |
| `test_resolve_paths_collision` | Handles existing files |

### T6. Encoder Integration (`tests/unit/test_encoder.py`)

| Test | Validates |
|------|-----------|
| `test_encoder_creates_file` | AVI file created |
| `test_encoder_write_frame` | Frame encoded |
| `test_encoder_close` | File finalized |
| `test_encoder_invalid_codec` | Raises EncoderError |

---

## Validation Checklist

- [ ] All test files created in `tests/unit/`
- [ ] `pytest tests/unit/` passes with 0 failures
- [ ] Coverage > 80% for tested modules
- [ ] Mocks don't leak into other tests (`@patch` scoped correctly)
- [ ] No actual hardware required (all mocked)
- [ ] Tests run in < 10 seconds total

## Completion Criteria

Unit tests pass in CI without hardware access. Coverage report shows >80% for:
- `camera_core/types.py`
- `camera_core/backends/usb_backend.py`
- `camera_core/capture.py`
- `camera_core/capabilities.py`
- `storage/session_paths.py`
