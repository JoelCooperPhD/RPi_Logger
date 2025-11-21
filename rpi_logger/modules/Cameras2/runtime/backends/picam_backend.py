"""
Pi camera backend specification.

- Purpose: wrap Picamera2/libcamera capture for CSI cameras; provide async-friendly control over modes and frame retrieval.
- Responsibilities: apply requested resolution/FPS, deliver frames to preview/record pipelines, query capabilities, and handle sensor hot-unplug if reported.
- Logging: pipeline init/shutdown, mode selection, frame errors, and capability probing.
- Picamera2 adherence: follow Picamera2 configuration flow (create/configure cameras, start with request loops, use Picamera2 controls where possible) and mirror its terminology in logs. Avoid custom mode negotiation outside what Picamera2 exposes.
- Constraints: avoid blocking loop; ensure clean teardown to free camera resources.
- API sketch:
  - `probe(sensor_id) -> CameraCapabilities` using Picamera2 mode lists.
  - `open(sensor_id, mode, stream=\"preview\"|\"record\") -> handle` with `async for frame in handle.frames(): ...`, `apply_controls(dict)`, `stop()`.
  - `supports_shared_streams(capabilities, preview_mode, record_mode) -> bool` helper to inform router.
  - Convert Picamera2 buffers to common frame struct (array + timestamp + format) without blocking Tk loop.
"""
