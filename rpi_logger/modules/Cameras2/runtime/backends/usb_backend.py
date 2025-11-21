"""
USB backend specification.

- Purpose: wrap OpenCV/v4l2 access for USB cameras; provide async-friendly start/read/stop and capability queries.
- Responsibilities: open devices with requested size/FPS, expose non-blocking frame reads (executor or async driver), and surface metadata.
- Logging: open/close, read failures, mode set attempts, and capability results.
- Constraints: avoid blocking event loop; release handles promptly on unplug.
- API sketch:
  - `probe(dev_path) -> CameraCapabilities` (run in executor; cached)
  - `open(dev_path, mode) -> handle` returning object with `read_frame()` coroutine (yields numpy arrays + timestamps + format), `stop()`, `is_alive()`.
  - `set_controls(handle, controls)` mapping v4l2 names to Picamera2-like names when possible; log unsupported controls.
  - Handles device loss: read_frame raises `DeviceLost` to trigger registry unplug flow.
"""
