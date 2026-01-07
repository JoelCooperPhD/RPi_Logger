# Testing: Unit Tests

> Component-level tests

## Quick Reference

| | |
|-|-|
| **Status** | See [TASKS.md](../TASKS.md) |
| **Task** | T1 |
| **Dependencies** | P1, P2 |
| **Effort** | Small |

## Goal

Create unit tests for core components to ensure correctness.

---

## Test Files

### tests/unit/test_frame.py

```python
def test_captured_frame_immutable():
    """CapturedFrame should be frozen."""
    frame = create_test_frame()
    with pytest.raises(FrozenInstanceError):
        frame.frame_number = 999

def test_captured_frame_timestamps():
    """All timestamp fields must be present and valid."""
    frame = create_test_frame()
    assert frame.sensor_timestamp_ns > 0
    assert frame.monotonic_ns > 0
    assert frame.wall_time > 0
```

### tests/unit/test_timing_gate.py

```python
def test_timing_gate_first_frame_accepted():
    """First frame should always be accepted."""
    gate = TimingGate(target_fps=5.0)
    frame = create_test_frame(monotonic_ns=0)
    assert gate.should_accept(frame) is True

def test_timing_gate_interval():
    """Frames should be accepted at target interval."""
    gate = TimingGate(target_fps=5.0)  # 200ms interval

    # First frame at t=0
    assert gate.should_accept(create_test_frame(monotonic_ns=0)) is True

    # Frame at t=100ms - too early
    assert gate.should_accept(create_test_frame(monotonic_ns=100_000_000)) is False

    # Frame at t=200ms - exactly on target
    assert gate.should_accept(create_test_frame(monotonic_ns=200_000_000)) is True

def test_timing_gate_drift_compensation():
    """Target should anchor to actual accept time."""
    gate = TimingGate(target_fps=5.0)  # 200ms interval

    # Accept at t=0
    gate.should_accept(create_test_frame(monotonic_ns=0))

    # Miss the t=200ms window, accept at t=250ms
    gate.should_accept(create_test_frame(monotonic_ns=250_000_000))

    # Next target should be t=450ms (250+200), not t=400ms (0+200+200)
    assert gate.should_accept(create_test_frame(monotonic_ns=400_000_000)) is False
    assert gate.should_accept(create_test_frame(monotonic_ns=450_000_000)) is True
```

### tests/unit/test_timing_csv.py

```python
def test_csv_header_format():
    """CSV header must match exactly."""
    expected = "trial,module,device_id,label,record_time_unix,record_time_mono,frame_index,sensor_timestamp_ns,video_pts\n"

    writer = TimingCSVWriter(tmp_path / "test.csv", trial_number=1, device_id="picam:0")
    writer.close()

    with open(tmp_path / "test.csv") as f:
        assert f.readline() == expected

def test_csv_data_format():
    """CSV data columns must use correct formats."""
    writer = TimingCSVWriter(tmp_path / "test.csv", trial_number=1, device_id="picam:0")
    writer.write_frame(create_test_frame(), frame_index=1)
    writer.close()

    # Verify format: record_time_unix has 6 decimals, record_time_mono has 9 decimals
```

### tests/unit/test_metrics.py

```python
def test_metrics_fps_calculation():
    """FPS should be calculated from rolling window."""
    metrics = FrameMetrics()

    # Simulate 60fps for 1 second
    for i in range(60):
        frame = create_test_frame(monotonic_ns=i * 16_666_667)  # ~60fps
        metrics.update_capture(frame)

    assert 59 < metrics.capture_fps < 61
```

---

## Test Utilities

### tests/conftest.py

```python
@pytest.fixture
def create_test_frame():
    def _create(
        monotonic_ns: int = 0,
        sensor_timestamp_ns: int = 0,
        wall_time: float = 0.0,
    ) -> CapturedFrame:
        return CapturedFrame(
            data=np.zeros((1088, 1536, 3), dtype=np.uint8),
            frame_number=1,
            sensor_timestamp_ns=sensor_timestamp_ns or monotonic_ns,
            monotonic_ns=monotonic_ns,
            wall_time=wall_time or time.time(),
            color_format="rgb",
            size=(1456, 1088),
            metadata={},
            sequence_number=1,
        )
    return _create
```

---

## Validation Checklist

- [ ] All test files created
- [ ] `pytest tests/unit/` passes
- [ ] Coverage >= 80% for tested components
- [ ] No mocking of internal implementation details

---

## Completion Criteria

When all validation items pass, update [TASKS.md](../TASKS.md).
