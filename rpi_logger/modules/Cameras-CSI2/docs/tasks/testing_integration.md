# Testing: Integration Tests

> End-to-end system tests

## Quick Reference

| | |
|-|-|
| **Status** | See [TASKS.md](../TASKS.md) |
| **Task** | T2 |
| **Dependencies** | P6 |
| **Effort** | Medium |

## Goal

Test the complete system with real cameras and full pipeline.

---

## Test Files

### tests/integration/test_capture.py

```python
@pytest.mark.hardware
async def test_capture_1000_frames():
    """Capture 1000 frames, all must have valid timestamps."""
    source = PicamSource(camera_index=0)
    await source.start()

    frames = []
    async for frame in source.frames():
        frames.append(frame)
        if len(frames) >= 1000:
            break

    await source.stop()

    # All frames have valid sensor timestamps
    for frame in frames:
        assert frame.sensor_timestamp_ns > 0

    # Timestamps are monotonically increasing
    for i in range(1, len(frames)):
        assert frames[i].sensor_timestamp_ns > frames[i-1].sensor_timestamp_ns
```

### tests/integration/test_fps_accuracy.py

```python
@pytest.mark.hardware
async def test_fps_gating_accuracy():
    """Gate 60fps to 5fps, verify ±1% accuracy."""
    source = PicamSource(camera_index=0)
    gate = TimingGate(target_fps=5.0)

    await source.start()

    accepted = []
    total = 0
    start_time = time.monotonic()

    async for frame in source.frames():
        total += 1
        if gate.should_accept(frame):
            accepted.append(frame)

        # Run for 10 seconds
        if time.monotonic() - start_time >= 10.0:
            break

    await source.stop()

    # Should have ~50 frames (5fps * 10s)
    assert 49 <= len(accepted) <= 51

    # Verify actual FPS
    duration_ns = accepted[-1].monotonic_ns - accepted[0].monotonic_ns
    actual_fps = (len(accepted) - 1) / (duration_ns / 1e9)
    assert 4.95 <= actual_fps <= 5.05  # ±1%
```

### tests/integration/test_recording.py

```python
@pytest.mark.hardware
async def test_recording_format():
    """Record 10 seconds, verify output format matches current module."""
    runtime = CSICameraRuntime(RuntimeConfig(camera_index=0))
    await runtime.start()

    # Assign camera
    await runtime.handle_command({
        "command": "assign_device",
        "device_id": "picam:0",
        "camera_type": "csi",
    })

    # Start recording
    await runtime.handle_command({
        "command": "start_recording",
        "session_dir": str(tmp_path),
        "trial_number": 1,
    })

    await asyncio.sleep(10)

    # Stop recording
    await runtime.handle_command({"command": "stop_recording"})
    await runtime.stop()

    # Verify output files exist
    video_path = tmp_path / "CSICameras" / "*" / "*.avi"
    csv_path = tmp_path / "CSICameras" / "*" / "*_timing.csv"

    assert len(list(tmp_path.glob("CSICameras/*/*.avi"))) == 1
    assert len(list(tmp_path.glob("CSICameras/*/*_timing.csv"))) == 1

    # Verify CSV header
    csv_file = list(tmp_path.glob("CSICameras/*/*_timing.csv"))[0]
    with open(csv_file) as f:
        header = f.readline().strip()
        assert header == "trial,module,device_id,label,record_time_unix,record_time_mono,frame_index,sensor_timestamp_ns,video_pts"
```

### tests/integration/test_full_cycle.py

```python
@pytest.mark.hardware
async def test_assign_record_stop_unassign():
    """Full lifecycle: assign → record → stop → unassign."""
    runtime = CSICameraRuntime(RuntimeConfig(camera_index=0))
    await runtime.start()

    # Assign
    await runtime.handle_command({
        "command": "assign_device",
        "device_id": "picam:0",
        "camera_type": "csi",
    })

    # Start recording
    await runtime.handle_command({
        "command": "start_recording",
        "session_dir": str(tmp_path),
        "trial_number": 1,
    })

    assert runtime.is_recording
    await asyncio.sleep(2)

    # Stop recording
    await runtime.handle_command({"command": "stop_recording"})
    assert not runtime.is_recording

    # Unassign
    await runtime.handle_command({"command": "unassign_device"})

    await runtime.stop()
```

---

## Comparison Tests

### tests/integration/test_csv_comparison.py

```python
def test_csv_header_byte_compare():
    """CSV header must be byte-identical to current module."""
    current_module_csv = Path("/path/to/reference/timing.csv")
    new_module_csv = Path("/path/to/new/timing.csv")

    with open(current_module_csv, 'rb') as f:
        current_header = f.readline()

    with open(new_module_csv, 'rb') as f:
        new_header = f.readline()

    assert current_header == new_header
```

---

## Validation Checklist

- [ ] All test files created
- [ ] `pytest tests/integration/ -m hardware` passes with camera attached
- [ ] FPS accuracy verified within ±1%
- [ ] Output format matches current module

---

## Completion Criteria

When all validation items pass, update [TASKS.md](../TASKS.md).
