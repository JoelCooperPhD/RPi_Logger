# Testing: Stress Tests

## Quick Reference

| Status | Depends On | Effort | Key Specs |
|--------|------------|--------|-----------|
| available | P7.3 | Large | `reference/mission.md` (success metrics) |

## Goal

Validate system stability under sustained load and adverse conditions.

---

## Stress Scenarios

### S1. Long Duration Capture (`tests/stress/test_long_capture.py`)

**Duration**: 1 hour continuous capture

| Metric | Target | Measurement |
|--------|--------|-------------|
| Frame drop rate | < 0.1% | `(expected_frames - actual_frames) / expected_frames` |
| Memory growth | < 50MB | `psutil.Process().memory_info().rss` delta |
| CPU average | < 30% | `psutil.cpu_percent(interval=60)` |

```python
async def test_1_hour_capture():
    runtime = CamerasRuntime(config)
    await runtime.assign_device(camera_id, descriptor)
    await runtime.start_recording(session_prefix, trial=1)

    start_mem = psutil.Process().memory_info().rss
    await asyncio.sleep(3600)  # 1 hour
    await runtime.stop_recording()

    end_mem = psutil.Process().memory_info().rss
    assert (end_mem - start_mem) < 50 * 1024 * 1024  # 50MB
```

### S2. Rapid Start/Stop Cycles (`tests/stress/test_rapid_cycles.py`)

**Cycles**: 100 start/stop in succession

| Metric | Target |
|--------|--------|
| Success rate | 100% |
| Resource leaks | None (fds, threads) |
| Time per cycle | < 2s |

```python
async def test_100_start_stop_cycles():
    runtime = CamerasRuntime(config)
    await runtime.assign_device(camera_id, descriptor)

    for i in range(100):
        await runtime.start_recording(f"cycle_{i}", trial=1)
        await asyncio.sleep(0.5)
        await runtime.stop_recording()

    # Check no leaked threads
    assert threading.active_count() <= initial_thread_count + 1
```

### S3. Queue Saturation (`tests/stress/test_queue_saturation.py`)

**Scenario**: Consumer slower than producer

| Metric | Target |
|--------|--------|
| Behavior | Drops oldest frames (not blocks) |
| Memory | Bounded (< 50MB for queue) |
| Producer | Never blocks |

```python
async def test_queue_saturation():
    cap = USBCapture("/dev/video0", 1280, 720, 60)
    await cap.start()

    # Slow consumer - only consume every 100ms
    frames_received = 0
    dropped = 0
    async for frame in cap:
        await asyncio.sleep(0.1)  # Slow consumer
        frames_received += 1
        if frame.frame_index > frames_received + 10:
            dropped = frame.frame_index - frames_received
        if frames_received >= 100:
            break

    await cap.stop()
    assert dropped > 0  # Should have dropped frames
    assert cap._queue.qsize() <= 3  # Queue stayed bounded
```

### S4. Disk Full Handling (`tests/stress/test_disk_full.py`)

**Scenario**: Disk fills during recording

| Metric | Target |
|--------|--------|
| Behavior | Graceful stop, partial files valid |
| Error | EncoderError raised |
| Recovery | Can start new recording after space freed |

```python
async def test_disk_full_recovery(tiny_ramdisk):
    # tiny_ramdisk is 10MB tmpfs
    runtime = CamerasRuntime(config)
    await runtime.assign_device(camera_id, descriptor)

    with pytest.raises(EncoderError):
        await runtime.start_recording(tiny_ramdisk / "test", trial=1)
        await asyncio.sleep(60)  # Will fill disk

    # Verify partial file is valid
    assert (tiny_ramdisk / "test_camera.avi").exists()
```

### S5. Camera Disconnect (`tests/stress/test_disconnect.py`)

**Scenario**: Camera unplugged during capture

| Metric | Target |
|--------|--------|
| Detection | < 1s to raise DeviceLost |
| State | Clean shutdown, files finalized |
| Recovery | Can assign new camera |

### S6. Multi-Camera Load (`tests/stress/test_multi_camera.py`)

**Scenario**: 2+ cameras capturing simultaneously

| Metric | Target |
|--------|--------|
| Per-camera FPS | Within 10% of target |
| Total CPU | < 60% (for 2 cameras) |
| Memory | < 400MB total |

---

## Performance Benchmarks

### Capture Latency

| Measurement | Target |
|-------------|--------|
| Frame read time | < 33ms (at 30fps) |
| Queue put time | < 1ms |
| Consumer get time | < 1ms |

```python
async def benchmark_capture_latency():
    cap = USBCapture("/dev/video0", 1280, 720, 30)
    await cap.start()

    latencies = []
    async for frame in cap:
        latency = time.monotonic() - frame.timestamp_mono
        latencies.append(latency)
        if len(latencies) >= 300:
            break

    await cap.stop()

    p50 = np.percentile(latencies, 50)
    p99 = np.percentile(latencies, 99)
    assert p50 < 0.020  # 20ms p50
    assert p99 < 0.050  # 50ms p99
```

### Encoding Throughput

| Resolution | Target FPS | CPU Budget |
|------------|------------|------------|
| 640x480 | 60 | < 15% |
| 1280x720 | 30 | < 25% |
| 1920x1080 | 30 | < 40% |

---

## Test Execution

```bash
# Run stress tests (takes 1+ hours)
pytest tests/stress/ -v --tb=short -x

# Run specific duration test
pytest tests/stress/test_long_capture.py -v --duration=3600

# Run benchmarks only
pytest tests/stress/ -v -m "benchmark"
```

---

## Validation Checklist

- [ ] All stress tests created in `tests/stress/`
- [ ] 1-hour capture completes with < 0.1% frame drop
- [ ] 100 start/stop cycles complete without leaks
- [ ] Queue saturation handled gracefully (no OOM)
- [ ] Disk full produces valid partial files
- [ ] Multi-camera maintains target FPS

## Completion Criteria

Stress tests pass with:
- Frame drop rate < 0.1% over 1 hour
- Memory growth < 50MB over 1 hour
- CPU usage < 30% at 1080p30
- No resource leaks after 100 cycles
- Graceful degradation under adverse conditions
