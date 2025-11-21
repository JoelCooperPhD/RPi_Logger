"""
Controller specification for Cameras2.

Responsibilities:
- Orchestrate discovery start/stop, handle user actions (select camera, enable preview, start/stop recording), and manage config dialog lifecycle.
- Coordinate registry, preview pipeline, record pipeline, router, and backends; ensure per-camera tasks start/stop cleanly when tabs appear/disappear (hotplug behavior).
- Bridge supervisor commands to runtime actions; implement healthcheck by querying pipelines/metrics.
- Apply capture settings via services.capture_settings; emit telemetry via services.telemetry.
- API outline (async unless noted):
  - `start(runtime_ctx)`; `shutdown()` safe to call multiple times.
  - `on_discovery_tick()` to schedule discovery iterations; `on_device_event(event)` for hotplug callbacks.
  - UI actions: `enable_preview(camera_id, mode?)`, `disable_preview(camera_id)`, `start_record(camera_id, mode?)`, `stop_record(camera_id)`, `open_config_dialog()`, `apply_config(camera_id, requested_configs)`.
  - Supervisor hooks: `handle_command(Command)`, `handle_user_action(Action)`, `healthcheck()` returning dict of status + metrics.
  - Metrics/telemetry: `emit_telemetry_snapshot(throttle)`; wires runtime.metrics to ui telemetry service.
- Stub (codex) alignment:
  - Must cooperate with `StubCodexController` command/user-action flow; accept legacy verbs (`start_recording`, `stop_recording`, `get_status`, `quit`) and map to Cameras2 semantics.
  - Expose shutdown request hook so supervisor `request_shutdown` works; honor `enable_commands` gating.
  - Surface StatusMessage updates (INITIALIZING/IDLE/RECORDING/ERROR/QUITTING) consistent with stub, using model state transitions.
  - `handle_command`/`handle_user_action` should return booleans to allow StubCodexController fallbacks/warnings; legacy CLI invocations (headless) must behave identically to GUI-driven actions so a user can configure in GUI then continue via CLI without losing state.

- Picamera2 alignment: when dealing with CSI cameras, drive configuration through Picamera2 APIs (mode selection, controls) via backend shims rather than custom code; keep controller semantics close to Picamera2's lifecycle (configure -> start -> stop) for predictability.
Constraints:
- asyncio-only; guard against blocking camera IO; use background tasks for any hardware interactions.
- Robust hotplug: unplug -> stop pipelines, free handles, drop tab; plug -> probe (or load cache), create tab lazily.
Logging:
- Discovery events, selection changes, pipeline start/stop, errors, retries, and timing for start/stop paths.
"""
