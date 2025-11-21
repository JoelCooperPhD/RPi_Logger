"""
Metrics panel specification.

- Purpose: visual FPS/drop counters and storage status inside the main view; consumes metrics from runtime.metrics.*.
- Responsibilities: render per-camera preview FPS, record FPS, frame drops/latency stats, storage queue depth, and disk guard status; update periodically without blocking.
- Logging: init timing, update failures, and anomalies (e.g., zero FPS while recording).
- Constraints: Tk-safe scheduling; async data fetch from metrics providers; avoid busy loops.
"""
