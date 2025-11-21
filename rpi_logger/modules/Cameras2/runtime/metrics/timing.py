"""
Frame timing specification.

- Purpose: track capture -> preview/record latency, detect slow frames/drops, and provide aggregates for UI/telemetry.
- Responsibilities: per-camera timers, moving averages, thresholds for warnings; integrate with FPS counters and overlay metadata.
- Logging: warn when latency exceeds thresholds; record timing stats periodically for debugging.
- Constraints: lock-free, asyncio-safe; minimal overhead to avoid perturbing timing.
"""
