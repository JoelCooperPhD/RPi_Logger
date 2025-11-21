"""
Discovery policy specification.

- Purpose: decide when to trust cache vs reprobe, how often to refresh capabilities, and how to respond to device errors (retry/backoff/disable).
- Responsibilities: provide policy hooks for controller/registry, including thresholds for revalidation and behavior on repeated failures.
- Logging: policy decisions (cache used vs probe), backoff actions, disables, and recoveries.
- Constraints: pure logic; no blocking IO; deterministic for reproducibility.
- Suggested policy knobs:
  - `max_failures_before_backoff` (default 3), exponential backoff capped at e.g., 60s.
  - `capabilities_refresh_interval_ms` (e.g., 10 minutes) or on cache schema bump.
  - `prefer_cache_until_reboot` boolean for stable devices; default false for USB, true for Pi cam.
  - `ignore_flapping_threshold_ms` to skip rapid plug/unplug noise.
  - Headless CLI and GUI share the same policy + cache files; cached capabilities/configs must be honored regardless of launch mode so a GUI-configured layout carries into CLI recording runs.
- API sketch: `should_probe(descriptor, cache_entry) -> bool`; `next_probe_delay_ms(failure_count) -> int`; `should_disable(camera_id, failure_count) -> bool`.
"""
