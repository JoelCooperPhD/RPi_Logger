"""
FPS counter specification.

- Purpose: rolling FPS calculators for preview and record paths; supports instantaneous and smoothed rates.
- Responsibilities: per-camera counters, hooks for metrics panel, optional thresholds to flag drops.
- Logging: anomalies (sustained low FPS vs target) and periodic summaries.
- Constraints: minimal overhead; asyncio-safe; no blocking.
"""
