# Cameras2 Build Plan

- [x] Scaffold core contracts: dataclasses/enums in `runtime.state`, logging helpers/constants, async task manager honoring stub shutdown, config/prefs IO via ModulePreferences.
- [x] Storage layer: async `session_paths`, `metadata`, `known_cameras` cache with schema/versioning, `retention` pruning (with dry-run hooks), and `disk_guard` checks/monitoring.
- [x] Discovery/backends: USB/Pi (Picamera2-aligned) backends with async probe/open/read; capability normalization; discovery cache/policy/combiner with hotplug/backoff.
- [x] Registry/router: state machine for discover/select/preview/record/unplug, cache merge, backend attach/detach; router deciding shared vs split capture, queues, backpressure rules.
- [x] Metrics/telemetry: FPS and timing counters plus telemetry emitters consumed by UI/healthcheck.
- [x] Pipelines/recording: preview pipeline + UI-safe worker; record pipeline with overlay, recorder, CSV logger, FPS tracker, segmentation/rotation, disk guard gating, clean cancellation/backpressure.
- [x] App layer: controller/model/view wiring; services (capture_settings, telemetry); widgets (camera tab, settings panel, status strip); views (adapter, config dialog, metrics panel) honoring Tk thread safety and prefs/geometry persistence.
- [x] Bridge/CLI: ModuleRuntime bridge, supervisor preset/retry policy, `main_cameras2.py` CLI bootstrap with config precedence and headless/GUI parity.
- [ ] Tests/integration: flesh out unit and smoke tests per specs (storage, discovery/backends, registry/router, pipelines, CLI), run and iterate to green.
- [ ] Next work (in progress):
  - Replace placeholder UI with real Tk view using stub view hooks: camera tabs with preview canvas, metrics panel, status strip, config dialog, settings panel.
  - Expand runtime to handle real USB/Pi backends with backpressure, overlays, telemetry/metrics wiring.
  - Broaden tests: registry transitions, router backpressure, pipelines, disk guard/retention, CLI/runtime smoke under stub supervisor.
