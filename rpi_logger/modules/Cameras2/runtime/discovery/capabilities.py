"""
Capabilities probing specification.

- Purpose: shared helpers to query and normalize per-camera supported resolutions/FPS and formats across backends.
- Responsibilities: probe modes (possibly in background), sanitize/limit to safe options, cache results, and cross-check against known camera cache.
- Constraints: no blocking; heavy logging of probe durations and failures; provide fallbacks when probing unsupported.
- Details:
  - Normalize pixel formats to canonical set: RGB, BGR, YUV420, MJPEG; map backend-specific strings accordingly.
  - Drop modes below minimum safe FPS (e.g., 5 fps) unless explicitly requested.
  - Include per-mode control hints (exposure/gain auto flags) when provided by backend to inform UI validation.
  - Provide helper `select_default_modes(capabilities)` returning preview + record defaults (prefer 640x480@30 preview, highest 16:9 <=30 fps record).
- API sketch: `probe_usb(dev_path)`, `probe_picam(sensor_id)`, `normalize_modes(raw_modes)` returning CameraCapabilities and timing info for logging.
"""
