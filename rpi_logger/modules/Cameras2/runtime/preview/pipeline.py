"""
Preview pipeline specification.

- Purpose: configure and run lo-res preview capture per camera; manage downscaling, color conversion, and frame scheduling to the UI.
- Responsibilities: start/stop per-camera preview tasks, enforce preview FPS caps, drop/skip frames when needed, and emit frames to preview.worker.
  - Accepts input queue/stream from router (shared capture) or direct backend if split.
  - Applies optional color_convert/frame_convert and overlays (lightweight) before pushing to worker queue.
  - Maintains per-camera FPS counter + timing metrics.
- Picamera2 adherence: when the backend is CSI, use Picamera2 preview/config streams directly (or mirrored in async shims) instead of ad-hoc conversions, matching Picamera2 mode semantics for resolution/FPS.
- Constraints: asyncio tasks only; camera IO must be non-blocking or offloaded; avoid starving event loop; handle backend errors gracefully.
- API sketch: `start(camera_state, router_handle, metrics, config) -> task`, `stop(camera_id)`, internal loop reads from Queue, coalesces if worker lagging.
- Logging: pipeline start/stop, frame delivery stats, drops/skips, backend failures, and timing per frame; include queue depth when dropping.
"""
