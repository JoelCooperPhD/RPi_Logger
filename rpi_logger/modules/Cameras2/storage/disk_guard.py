"""
Disk guard specification.

- Purpose: check free space before recording starts/continues; block start if below threshold; surface status to UI.
- Constraints: async-friendly filesystem checks; configurable thresholds; no blocking; periodic re-check during recording.
- API sketch: `check_before_start(camera_id, required_bytes) -> bool`, `monitor(handle) -> async iterator/status` returning `ok|blocked|recovering`; emits events to controller/UI.
- Defaults: threshold derived from config/prefs (e.g., `guard.disk_free_gb_min` default 1.0GB, `check_interval_ms` default 5000); same values honored in GUI and CLI. Disk status should round-trip through healthcheck/telemetry so headless runs still publish guard state.
- Logging: guard failures, recoveries, and thresholds used; include free space and required estimates; warn when sustained low space forces drop/stop.
"""
