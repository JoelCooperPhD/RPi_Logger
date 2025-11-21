"""
Router specification.

- Purpose: coordinate frame distribution between preview and record pipelines; optionally share capture source while gating rates per path.

- Modes:
  - Shared capture: single backend reader feeds two asyncio Queues (preview/record) with copy/convert hooks; preferred when backend supports desired dual rates.
  - Split capture: distinct backend captures per path when formats/FPS differ too much or backend cannot fan out.

- Responsibilities:
  - Decide duplication strategy per camera using capabilities + selected configs; fall back to split if shared drops below target FPS.
  - Enforce backpressure policies: bounded queues per path (size defaults preview=2, record=4), drop-oldest for preview when UI lags, pause/resume record ingestion when recorder backpressure signals.
  - Surface errors upstream with camera context; allow isolating preview failures without stopping record unless backend faulty.

- API sketches:
  - `attach(camera_id, backend_handle, configs, metrics)` -> returns router handle.
  - `start(camera_id)` / `stop(camera_id)` -> manage queues/tasks.
  - `get_preview_queue(camera_id)` / `get_record_queue(camera_id)` -> to wire pipelines.
  - `update_configs(camera_id, configs)` -> re-evaluate shared vs split strategy.

- Constraints: asyncio; avoid head-of-line blocking; handle path-specific failures without taking down the other path unless necessary; queues must be awaited with cancellation-friendly loops.
- Logging: routing decisions, drop reasons, and backpressure events; log when switching between shared/split, queue churn, and per-path stall warnings.
"""
