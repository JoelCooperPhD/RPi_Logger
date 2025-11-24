# Cameras Module Specification

This document describes the intended behavior, threading/async constraints, and component boundaries for the Cameras module (stub/codex-based). All text only; no executable code committed yet.

## Goals
- Discover USB and Pi CSI cameras, populate dynamic tabs per camera, and remove tabs when devices vanish.
- Maintain two distinct pipelines per camera: preview (lo-res, UI-facing) and record (full-quality, storage-saving), both non-blocking asyncio.
- Provide a pop-out configuration window to adjust per-camera settings (resolution/FPS/format) with persistence and capability-aware options.
- Enforce robust disk guards, retention, overlay application, and high-quality logging for scientific timing accuracy.
- **Picamera2 alignment:** For CSI/hardwired cameras, adhere closely to Picamera2 idioms (modes, controls, configuration/apply steps, buffers) rather than inventing custom flows. Prefer direct use of Picamera2/libcamera objects wrapped in async-safe shims, and mirror Picamera2 terminology in APIs/logs.

## Constraints
- asyncio everywhere; never block the event loop (no long OpenCV/libcamera calls without threading/async wrappers).
- Detailed logging for discovery, lifecycle transitions, timing, and error paths; logs must help diagnose frame drops and IO stalls.
- Tabs/preview are dynamic: unplug -> tab removed and tasks stopped; plug -> discovered, tab added, preview optional until user selects.

## Structure Overview
See the surrounding files for per-component responsibilities. Key layers:
- `app/`: CLI/supervisor binding, model/controller/view adapters, services, and GUI compositions.
- `runtime/`: device discovery, registry, pipelines, metrics, routing, and backend primitives.
- `storage/`: session paths, retention, disk guards, known camera cache persistence.
- `tests/`: unit scaffolding for discovery, registry, pipelines, and safeguards.

## Stub (codex) integration
- Cameras runs under the stub VMC stack used by `main_stub_codex.py`: use `StubCodexSupervisor`, `StubCodexModel`, and `StubCodexController` wiring patterns (ModuleRuntime/RuntimeContext, lifecycle hooks, retry policies).
- CLI/options should follow stub conventions (`mode`, `output-dir`, `session-prefix`, `enable-commands`, `window-geometry`, `log-level`, `log-file`), with Cameras-specific flags layered on top.
- Config/prefs should flow through `ModulePreferences`/`ModuleConfigContext` (key/value `config.txt`), not bespoke parsers; honor saved `window_geometry` and pass through to the view.
- Commands/user actions must honor the stub verbs (`start_recording`/`stop_recording`/`quit`/`get_status`/`start_session`/`stop_session`) and forward unknowns to the Cameras runtime as needed.
- Healthcheck/retry paths should implement `ModuleRuntime.healthcheck` so the supervisor's retry policy works when cameras are missing/unplugged.
- Logging should attach through stub view hooks when GUI exists; keep loggers child-named for integration (`logger.getChild("Cameras")` etc.).

## Logging and Metrics
- Every lifecycle transition, discovery event, pipeline start/stop, and timing measurement must log with context (camera id, backend, mode, FPS, latency).
- Metrics should be surfaced in the UI (metrics panel) and available for telemetry export.

## Future Implementation Notes
- Add retry/backoff hooks for runtime construction and device health checks.
- Ensure clean cancellation semantics for all tasks to avoid dangling video handles on shutdown or device removal.
- Keep configuration IO small and async-friendly; avoid heavy filesystem work on the main loop.
