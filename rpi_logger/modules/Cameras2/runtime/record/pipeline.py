"""
Record pipeline specification.

- Purpose: configure and run save-quality capture per camera; manage encoding, throttling (save FPS), and queueing to recorder.
- Responsibilities: start/stop per-camera record tasks, apply selected resolution/FPS/format, integrate overlays, and signal recorder for file writes.
- Picamera2 adherence: for CSI cameras, prefer Picamera2's capture/record streams and control APIs to set modes/FPS, keeping inline with Picamera2's buffer lifecycle and terminology.
- Long-run robustness: support configurable file segmentation/rotation by max duration/size with seamless rollover and metadata continuity so multi-hour sessions avoid container/muxer limits and reduce corruption risk on crash; ensure recorder reopens cleanly on segment boundaries and keeps metrics/CSV coherent.
- Constraints: asyncio; heavy IO offloaded or non-blocking; ensure backpressure handling to avoid memory blow-up; respect disk guard results.
- API sketch:
  - `start(camera_state, router_handle, recorder, csv_logger, metrics, config, disk_guard) -> task`; `stop(camera_id)` idempotent.
  - Reads frames from router record queue; applies overlay (timestamp/camera id/FPS) optionally; pushes to recorder queue.
  - Periodically emits fps_tracker updates and timing metrics for telemetry/ui; clamps to target_fps by selective drop with logging.
- Logging: pipeline start/stop, queue depth, encoding errors, frame drop reasons, and timing.
"""
