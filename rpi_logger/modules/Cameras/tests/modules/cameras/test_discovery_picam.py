"""Test spec for Pi camera discovery.

- Verify: detects CSI cameras, queries modes, handles missing firmware gracefully, and respects cache/policy rules.
- Ensure: async, no blocking; logs probe failures; integrates with registry updates.
- Cases: corrupted Picamera2 install raises descriptive error; capability list matches Picamera2 reported modes; backoff engages after repeated probe failures; stable ids remain consistent across reboots.
"""
