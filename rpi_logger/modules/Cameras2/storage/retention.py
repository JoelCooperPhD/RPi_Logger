"""
Retention policy specification.

- Purpose: enforce session retention limits (e.g., keep N sessions), prune old recordings safely, and log actions.
- Constraints: async file operations; avoid blocking on large directories; guard against deleting active sessions.
- API sketch: `prune(base_path, max_sessions, exclude_active=set())` using async filesystem helpers; returns summary for telemetry.
- Defaults: respect config/prefs knobs (`retention.max_sessions` default 10, `retention.prune_on_start` default true) and apply identically in GUI/headless runs so CLI recording after GUI setup uses the same pruning policy.
- Logging: prune decisions, errors, and disk impact; include counts of files/bytes removed; warn if active session detected and skipped.
"""
