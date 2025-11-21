"""
Session paths specification.

- Purpose: determine output directories per session/camera, handle naming conventions, and integrate with retention.
- API sketch:
  - `resolve_session_paths(base_path, session_id, camera_id) -> SessionPaths` (root, csv, video, frames, metadata paths).
  - `ensure_dirs(paths)` async mkdirs; handle collisions by suffixing increment; expose hook for retention pre-check.
- Stub (codex) alignment: honor `args.output_dir` and `session-prefix` provided by module manager; prefer basing session_id on StubCodexModel session naming to stay consistent in logs/telemetry. GUI and CLI/headless runs share the same resolver so a session started from GUI can resume recording from CLI without path drift.
- Constraints: async filesystem ops; ensure directories exist without blocking; handle collisions; log path decisions; sanitize camera ids for filesystem.
"""
