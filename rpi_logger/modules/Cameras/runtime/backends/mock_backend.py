"""
Mock backend specification.

- Purpose: provide synthetic camera source for development/testing with deterministic frames and timing.
- Responsibilities: emit frames at controlled FPS, simulate hotplug, and allow fault injection (drops, latency) to test robustness.
- Logging: start/stop, simulated faults, and timing stats.
- Constraints: pure asyncio; no real IO; configurable to mimic USB/Pi characteristics.
"""
