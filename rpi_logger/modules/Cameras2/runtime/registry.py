"""
Registry specification.

- Purpose: central state machine tracking cameras from discovery -> selection -> previewing -> recording; handles hotplug and cleanup.

- API surface (async unless noted):
  - `apply_discovery(batch: list[CameraDescriptor|state])` -> diff current set, emit add/remove events, kick capabilities merge with cache.
  - `select_camera(camera_id)` / `deselect_camera(camera_id)` -> drive UI selections and task creation.
  - `attach_backend(camera_id, backend_handle, capabilities)` -> store backend ref, update state, notify router/pipelines.
  - `start_preview(camera_id, config)` / `stop_preview(camera_id)`; `start_record(camera_id, config)` / `stop_record(camera_id)`; all idempotent with retries/backoff hooks.
  - `handle_unplug(camera_id)` -> cancel tasks, drop tabs, clear backend; safe to call repeatedly.
  - `snapshot()` -> lightweight state view for telemetry/health checks.

- Responsibilities:
  - Merge discovered descriptors with known cache, maintain per-camera tasks/handles, notify view adapter of tab add/remove, and coordinate router/pipelines.
  - Enforce state transitions (discovered->selected->previewing->recording) and guard invalid transitions with warnings.
  - Integrate policy decisions (discovery.policy) to decide reuse cache vs reprobe; hand off selected configs to pipelines.
  - Own per-camera task registry (from runtime.tasks) to ensure cancellation on shutdown/unplug; surface leaks.

- Behavior: when device disappears, stop pipelines, drop tab, free backend; when new device appears, create entry and optional tab. Rapid churn should debounce UI/tab creation while ensuring resources are released immediately on unplug.
- Constraints: asyncio; non-blocking updates; thread-safe notifications; resilient to rapid churn; avoid holding locks across awaits.
- Logging: every state transition, cache hits/misses, attach/detach events, invalid transitions, retries, and errors during teardown; include camera id/backend in all records.
"""
