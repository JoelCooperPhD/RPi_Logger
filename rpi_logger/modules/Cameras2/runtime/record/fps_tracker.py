"""
Record FPS tracker specification.

- Purpose: monitor effective save FPS, detect stalls, and feed metrics panel/telemetry; complement timing module.
- Logging: low FPS warnings, sustained stalls, and periodic summaries.
- Constraints: lightweight, asyncio-safe.
"""
