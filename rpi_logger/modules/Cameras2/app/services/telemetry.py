"""
Telemetry service specification.

- Purpose: emit structured metrics/events from Cameras2 (discovery counts, FPS, latency, drops, storage status) to the logger's telemetry sink.
- Functions: build payloads from metrics panel/registry, throttle emissions, handle failures gracefully, and collect healthcheck summaries.
- Stub (codex) alignment: can piggyback on StatusMessage/StatusType channels for high-level state, and use stub supervisor logger for detailed telemetry when GUI logging attached.
- Constraints: asyncio, no blocking; logs every emit attempt and error; resilient to downstream telemetry outages.
"""
