"""
Recorder specification.

- Purpose: write frames from record pipeline to disk (images/video) with retention and metadata support.
- Responsibilities: manage writers (e.g., MJPEG/MP4 or image sequences), enqueue writes, handle failures, and emit per-frame results to csv_logger/fps_tracker.
- Constraints: asyncio; offload blocking encodes to workers; respect disk_guard; stop cleanly on shutdown or device loss.
- API sketch:
  - `start(camera_id, session_paths, config, metadata, disk_guard) -> handle`
  - `enqueue_frame(handle, frame, timestamp, metadata)` (non-blocking, bounded queue; drops oldest with warning if full)
  - `stop(handle)` flushes outstanding writes with timeout; raises/logs on over-time.
  - Hook for `on_disk_guard_blocked` to pause ingestion and notify pipeline.
- Logging: file open/close, write errors, throughput stats, and storage path decisions; emit warnings when queue exceeds thresholds or when retention prunes active path attempts (should not happen).
"""
