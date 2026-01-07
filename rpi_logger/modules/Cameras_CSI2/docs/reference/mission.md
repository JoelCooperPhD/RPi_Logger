# Mission Statement

> What we're building and why

## What We Are Building

A **scientific-grade CSI camera capture system** for Raspberry Pi that provides:

- **Frame-perfect timing**: If you request 5 FPS, you get exactly 5 FPS with sub-millisecond precision
- **Hardware-accurate timestamps**: Every frame tagged with the actual sensor exposure time, not software receipt time
- **Zero-compromise capture loop**: The frame acquisition path is stripped to the absolute minimum - no allocations, no locks, no business logic
- **Complete audit trail**: Every frame's journey from sensor to disk is traceable via timing CSV
- **Drop transparency**: Any frame drops are logged with precise timestamps and reasons

---

## What This Is For

Scientific data capture where:

- Frame timing reproducibility is critical for analysis
- Dropped frames must be detected and accounted for
- Timestamps must reflect actual sensor exposure, not software processing delays
- Multi-camera synchronization depends on accurate timing metadata

---

## Non-Goals

- **Real-time video streaming** - we optimize for capture fidelity, not latency
- **Maximum throughput at any cost** - we optimize for timing precision
- **Backwards compatibility with non-scientific use cases**

---

## Success Criteria

| Metric | Target | Rationale |
|--------|--------|-----------|
| Timestamp accuracy | <1 ms | Scientific requirement |
| FPS accuracy | ±1% | Reproducibility |
| Capture thread overhead | <100 μs/frame | Must not miss frames at 60fps |
| Frame drops | Zero under normal operation | Data integrity |

---

## Guiding Principles

1. **The capture loop is sacred** - nothing can slow it down
2. **Timestamps are non-negotiable** - every frame has three timestamps
3. **Time-based frame selection** - not frame counting
4. **Explicit over implicit** - no silent failures
5. **Composition over inheritance** - focused, testable components
