"""
CSV logger specification.

- Purpose: record per-frame metadata (timestamps, camera id, mode, FPS estimate, file names) to CSV alongside recordings.
- API sketch:
  - `start(session_paths, schema_version=1) -> handle`; opens CSV with headers including timing metrics.
  - `enqueue(handle, record)` (non-blocking, queued batch writes); `flush(handle)`; `stop(handle)` for graceful close.
- Constraints: async file writes; batching to reduce IO; safe shutdown flush; no blocking; handle partial writes with retry/backoff.
- Logging: CSV open/close, write failures, and batch flush timing; warn on dropped records when queue full.
"""
