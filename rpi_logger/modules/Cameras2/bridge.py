"""
Cameras2 runtime bridge specification.

- Purpose: expose a ModuleRuntime compatible class for Stub (codex) supervisor, delegating start/shutdown/commands/user-actions to Cameras2 controller/runtime.
- Responsibilities: construct controller with RuntimeContext, forward supervisor callbacks, and provide healthcheck plumbing.
- API shape:
  - class `Cameras2Runtime(ModuleRuntime)`: `__init__(ctx, config_path)`, `start()`, `shutdown()`, `cleanup()`, `handle_command(command)`, `handle_user_action(action)`, `healthcheck()` returning status + metrics.
  - `factory(ctx)` convenience function for supervisor wiring.
- Stub (codex) alignment:
  - Must honor ModuleRuntime contract in `vmc.runtime`: boolean return for `handle_command/handle_user_action` so StubCodexController can fall back or warn on unhandled commands. Map legacy verbs (`record`, `start_record`, `pause`) to Cameras2 actions.
  - Use `ctx.model.preferences` / ModulePreferences snapshot for persisted defaults; avoid custom config loaders. Both GUI and headless launches share the same prefs/config + known-camera cache so state set in GUI remains available to CLI-only recording runs.
  - Gracefully handle `enable_commands=False` (supervisor may shut down if commands unavailable).
  - Wire telemetry/status into stub StatusMessage channels when available.
- Logging: log every entry/exit for start/shutdown/cleanup/command/action/healthcheck with camera counts when available.
- Async constraints: all methods coroutine-friendly; no blocking IO; ensure cleanup awaits downstream tasks and is idempotent.
"""
