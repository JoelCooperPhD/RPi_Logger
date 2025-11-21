"""
Settings panel widget specification.

- Purpose: UI fragment used inside config dialog (or tab) to present capability-driven dropdowns for preview and record resolutions/FPS, format/quality, overlay toggles.
- Responsibilities: render options from CameraCapabilities, validate selections, signal controller on apply, and display warnings for unsupported choices.
- Logging: selection changes, validation failures, apply success/failure per camera.
- Constraints: Tk-safe; non-blocking; reacts to capability updates in real-time (if discovery refreshes modes).
"""
