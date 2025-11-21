"""
Specification for Cameras2 module entry point (no executable code yet).

- Purpose: parse module CLI options, resolve config paths, and bootstrap the Stub (codex) supervisor with Cameras2 runtime factory.
- Constraints: asyncio-based; no blocking IO; heavy logging around argument parsing, config resolution, and supervisor lifecycle.
- Responsibilities: build args (mode/gui/headless, preview + record defaults, retention/disk guards), inject config path, wire RuntimeRetryPolicy, install signal handlers, call supervisor.run()/shutdown().
- Must preserve stub (codex) CLI shape: `--mode`, `--output-dir`, `--session-prefix`, `--enable-commands`, `--window-geometry`, `--log-level`, `--log-file`, `--close-delay-ms`, console toggles (`--console/--no-console`), plus Cameras2 options (`--preview-fps`, `--preview-size`, `--record-fps`, `--record-size`, `--format`, `--no-overlay`, `--disk-threshold`, `--max-sessions`, `--config-path`, `--mock-camera` toggles). Headless runs use the exact same args/prefs as GUI so a user can configure via GUI, quit, and relaunch from CLI without losing camera selections or defaults.
- Apply precedence: CLI overrides config.txt overrides module defaults; log resolved values. When a CLI flag maps to a persisted pref (e.g., preview/record size/FPS/format, overlay toggle, disk thresholds), write back through ModulePreferences-compatible keys so future GUI/headless runs see the same settings. Pass resolved `window_geometry` into model/view args per StubCodexModel patterns even in headless mode to keep prefs consistent.
- Resolve session paths via storage/session_paths to pass to runtime; align `output-dir`/`session-prefix` with base logger expectations.
- Integration: relies on `bridge.py` to expose runtime factory; uses module_display/module_id constants to register with manager; respects window geometry persistence via ModulePreferences handled by StubCodexModel.
- Validation: log parsed args, warn on unsupported combinations, and surface early failures cleanly before the runtime spins up. Validate mutually exclusive options (headless vs ui geometry persistence), supported formats per backend, and FPS caps. Honor `--enable-commands` requirement from stub supervisor.
- Future: once implemented, should include unit coverage for arg parsing defaults and error cases; include smoke test for headless startup with mock backend plus GUI geometry persistence through ModulePreferences.
"""
