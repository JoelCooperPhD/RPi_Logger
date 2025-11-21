"""
Supervisor preset specification for Cameras2.

- Purpose: assemble StubCodexSupervisor with Cameras2 view factory, runtime factory (bridge), retry policy, and lifecycle hooks.
- Hooks: before/after start/shutdown for logging, metrics flush, and resource guards.
- Integration with stub (codex):
  - Use `StubCodexSupervisor` directly; inject Cameras2 view/controller/model factories if customization needed, otherwise rely on defaults by passing module_id/display_name/config_path.
  - Provide `RuntimeRetryPolicy` so supervisor will retry constructing Cameras2 runtime when backends unavailable; hook runtime healthcheck for hotplug cases.
  - Ensure hooks leverage ModulePreferences for window geometry persistence; respect `enable_commands`/`mode` args already parsed by main. Headless runs still load/save the same prefs/cache (window geometry, per-camera defaults, known cameras) so GUI and CLI launches remain interchangeable.
  - Attach view logging handler when GUI enabled; fall back to headless gracefully.
- Async constraints: no blocking; ensure retry monitors run on asyncio tasks with cancellation support.
- Logging: capture construction timing, hook timings, retries, and GUI availability fallbacks.
"""
