# Testing: Stress Tests

> Long-running stability tests

## Quick Reference

| | |
|-|-|
| **Status** | See [TASKS.md](../TASKS.md) |
| **Task** | T3 |
| **Dependencies** | P6 |
| **Effort** | Small |

## Goal

Verify system stability under extended operation and edge conditions.

---

## Test Scenarios

### 1. Continuous Capture (1 hour)

```bash
# Run capture without recording for 1 hour
python -m pytest tests/stress/test_continuous_capture.py -v --timeout=4000
```

**Success criteria**:
- Zero timestamp gaps (no frames with >2x expected interval)
- Zero buffer overflows
- Memory usage stable (no growth >10%)

### 2. Continuous Recording (1 hour)

```bash
# Run recording for 1 hour
python -m pytest tests/stress/test_continuous_recording.py -v --timeout=4000
```

**Success criteria**:
- Zero frame drops
- All frames in CSV have valid timestamps
- Video file playable
- Disk space used matches expected

### 3. Memory Stability (24 hours)

```bash
# Run with tracemalloc monitoring
python -m pytest tests/stress/test_memory_stability.py -v --timeout=90000
```

**Success criteria**:
- No memory leaks (growth <5% over 24 hours)
- No file descriptor leaks
- No zombie processes

### 4. Rapid Cycling (100 start/stop)

```bash
# Rapid start/stop cycles
python -m pytest tests/stress/test_rapid_cycling.py -v
```

**Success criteria**:
- All 100 cycles complete without error
- No resource leaks between cycles
- Final state clean

---

## Test Files

### tests/stress/test_continuous_capture.py

```python
@pytest.mark.stress
@pytest.mark.timeout(4000)
async def test_continuous_capture_1_hour():
    """Capture frames for 1 hour, verify no gaps."""
    source = PicamSource(camera_index=0)
    await source.start()

    last_ts = 0
    gap_count = 0
    expected_interval_ns = 16_666_667  # 60fps
    max_gap_ns = expected_interval_ns * 2  # 2x tolerance

    start = time.monotonic()
    while time.monotonic() - start < 3600:  # 1 hour
        async for frame in source.frames():
            if last_ts > 0:
                gap = frame.monotonic_ns - last_ts
                if gap > max_gap_ns:
                    gap_count += 1
            last_ts = frame.monotonic_ns

            if time.monotonic() - start >= 3600:
                break

    await source.stop()
    assert gap_count == 0, f"Found {gap_count} timestamp gaps"
```

### tests/stress/test_rapid_cycling.py

```python
@pytest.mark.stress
async def test_rapid_start_stop():
    """100 rapid start/stop cycles."""
    for i in range(100):
        runtime = CSICameraRuntime(RuntimeConfig(camera_index=0))
        await runtime.start()

        await runtime.handle_command({
            "command": "assign_device",
            "device_id": "picam:0",
        })

        await runtime.handle_command({
            "command": "start_recording",
            "session_dir": f"/tmp/stress_test_{i}",
            "trial_number": 1,
        })

        await asyncio.sleep(0.5)

        await runtime.handle_command({"command": "stop_recording"})
        await runtime.handle_command({"command": "unassign_device"})
        await runtime.stop()

        # Cleanup
        shutil.rmtree(f"/tmp/stress_test_{i}", ignore_errors=True)
```

---

## Performance Targets

| Metric | Target | Rationale |
|--------|--------|-----------|
| Capture thread overhead | <100 μs/frame | Must not miss frames at 60fps |
| Timestamp accuracy | <1 ms | Scientific requirement |
| FPS accuracy | ±1% | Reproducibility requirement |
| Preview latency | <50 ms | UI responsiveness |
| Memory per frame | <5 MB | 1456x1088 YUV420 ≈ 2.4 MB |
| Buffer size | 8 frames | ~130 ms buffer at 60fps |

---

## Validation Checklist

- [ ] Continuous capture passes (1 hour, zero gaps)
- [ ] Continuous recording passes (1 hour, zero drops)
- [ ] Memory stable over 24 hours
- [ ] Rapid cycling (100x) no errors

---

## Completion Criteria

When all validation items pass, update [TASKS.md](../TASKS.md).
