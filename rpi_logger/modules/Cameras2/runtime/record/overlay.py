"""
Overlay specification.

- Purpose: apply overlays/metadata to frames before encoding (timestamps, camera id, FPS, custom text).
- Constraints: lightweight operations to avoid affecting timing; optional disable; asyncio-friendly composition.
- Logging: overlay enable/disable, failures, and timing when overlays exceed budget.
"""
