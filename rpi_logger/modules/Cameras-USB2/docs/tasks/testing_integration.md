# Testing: Integration Tests

## Quick Reference

| Status | Depends On | Effort | Key Specs |
|--------|------------|--------|-----------|
| available | P7.1, P7.2 | Medium | `specs/components.md`, `specs/output_formats.md` |

## Goal

Validate component interactions and end-to-end workflows with real hardware.

---

## Test Scenarios

### I1. Camera Discovery (`tests/integration/test_discovery.py`)

**Precondition**: At least one USB camera connected

| Test | Validates |
|------|-----------|
| `test_probe_real_camera` | Probe returns valid capabilities |
| `test_probe_lists_modes` | At least one MJPG mode available |
| `test_probe_lists_controls` | Brightness/contrast present |

```python
async def test_probe_real_camera():
    caps = await probe("/dev/video0")
    assert len(caps.modes) > 0
    assert any(m.pixel_format == "MJPG" for m in caps.modes)
```

### I2. Capture Pipeline (`tests/integration/test_capture_pipeline.py`)

**Precondition**: USB camera connected

| Test | Validates |
|------|-----------|
| `test_capture_100_frames` | 100 frames captured without error |
| `test_capture_timestamps_monotonic` | Each timestamp > previous |
| `test_capture_frame_dimensions` | Width/height match requested |
| `test_capture_stop_cleans_up` | No resource leaks after stop |

```python
async def test_capture_timestamps_monotonic():
    cap = USBCapture("/dev/video0", 1280, 720, 30)
    await cap.start()
    prev_ts = 0
    async for frame in cap:
        assert frame.timestamp_mono > prev_ts
        prev_ts = frame.timestamp_mono
        if frame.frame_index >= 100:
            break
    await cap.stop()
```

### I3. Recording Pipeline (`tests/integration/test_recording.py`)

**Precondition**: USB camera connected, writable temp directory

| Test | Validates |
|------|-----------|
| `test_record_creates_files` | AVI + timing CSV + metadata CSV created |
| `test_record_timing_csv_format` | CSV matches schema |
| `test_record_avi_playable` | OpenCV can read recorded file |
| `test_record_frame_count_matches` | CSV rows = video frames |

```python
async def test_record_creates_files(tmp_path):
    runtime = CamerasRuntime(config, view=None)
    await runtime.assign_device(camera_id, descriptor)
    await runtime.start_recording(str(tmp_path / "test"), trial=1)
    await asyncio.sleep(3)  # Record 3 seconds
    await runtime.stop_recording()

    assert (tmp_path / "test_camera.avi").exists()
    assert (tmp_path / "test_camera_timing.csv").exists()
    assert (tmp_path / "test_camera_metadata.csv").exists()
```

### I4. Command Handling (`tests/integration/test_commands.py`)

| Test | Validates |
|------|-----------|
| `test_cmd_start_recording` | Recording starts on command |
| `test_cmd_stop_recording` | Recording stops, files finalized |
| `test_cmd_apply_config` | Control values applied |
| `test_cmd_unknown` | Unknown command logged, no crash |

### I5. Device Lifecycle (`tests/integration/test_lifecycle.py`)

| Test | Validates |
|------|-----------|
| `test_assign_unassign_cycle` | Assign→Unassign works repeatedly |
| `test_reassign_different_camera` | Can switch cameras |
| `test_unassign_during_recording` | Recording stops cleanly |

### I6. Preview Pipeline (`tests/integration/test_preview.py`)

**Precondition**: Display available (or mock Tk)

| Test | Validates |
|------|-----------|
| `test_preview_receives_frames` | push_frame() called |
| `test_preview_metrics_update` | update_metrics() called |
| `test_preview_no_crash_on_rapid_frames` | 60fps doesn't crash |

---

## Hardware Requirements

| Requirement | Minimum |
|-------------|---------|
| USB cameras | 1 (any UVC compliant) |
| Disk space | 1GB free in /tmp |
| Display | Optional (Tk can be mocked) |

## Test Execution

```bash
# Run all integration tests (requires hardware)
pytest tests/integration/ -v --tb=short

# Run specific test module
pytest tests/integration/test_capture_pipeline.py -v

# Skip if no camera
pytest tests/integration/ -v -m "not requires_camera"
```

---

## Validation Checklist

- [ ] All test files created in `tests/integration/`
- [ ] Tests marked with `@pytest.mark.requires_camera` where applicable
- [ ] `pytest tests/integration/` passes with camera connected
- [ ] No orphaned processes after test suite
- [ ] Temp files cleaned up after tests
- [ ] Recording files are valid (playable, correct schema)

## Completion Criteria

Integration tests pass on hardware with:
- At least one USB camera connected
- 1GB free disk space
- Tests complete in < 60 seconds total
