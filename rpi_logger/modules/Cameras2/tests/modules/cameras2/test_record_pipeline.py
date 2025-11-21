"""Test spec for record pipeline.

- Verify: applies selected res/FPS/format, integrates overlays, throttles save FPS, and enforces disk guard.
- Ensure: recorder is called with correct metadata, backpressure handled, and tasks cancel cleanly.
- Cases: router shared vs split feeds, CSV logger receives per-frame info, overlay toggles on/off, queue saturation triggers drop with log, and disk guard block pauses ingestion.
"""
