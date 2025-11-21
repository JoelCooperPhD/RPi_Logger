# Cameras2 Module Structure (Spec-Only)

Quick map of the Cameras2 spec files and their roles. Implementation is intentionally absent; each file documents intent and constraints.

## Top-Level Entry
- `rpi_logger/modules/Cameras2/main_cameras2.py` - CLI/options bootstrap, config resolution, stub supervisor wiring.
- `rpi_logger/modules/Cameras2/bridge.py` - ModuleRuntime bridge for the stub stack (start/shutdown/commands/healthcheck).

## App Layer (UI + Supervisor)
- `app/controller.py` - orchestrates discovery, preview/record actions, and command/user-action handling.
- `app/model.py` - UI-facing state/prefs, known cameras cache merge, status signaling.
- `app/view.py` / `app/views/*` / `app/widgets/*` - Tk view integration: dynamic tabs, metrics panel, status strip, config dialog, camera tab/settings widgets, adapter for thread-safe updates.
- `app/supervisor.py` - StubCodexSupervisor preset with retry hooks and view/controller/model wiring.
- `app/media/*` - frame/color conversion specs for preview/record paths.
- `app/services/*` - capture settings resolution and telemetry emission helpers.

## Runtime Core
- `runtime/registry.py` - camera lifecycle state machine (discover -> select -> preview -> record -> teardown).
- `runtime/router.py` - shared vs split capture routing with queue/backpressure policies.
- `runtime/tasks.py` - task ownership and cancellation hygiene.
- `runtime/state.py` - data models for descriptors, capabilities, selected configs, status.
- `runtime/metrics/*` - FPS and timing counters.

## Pipelines and Backends
- `runtime/preview/*` - preview pipeline and UI worker wiring.
- `runtime/record/*` - record pipeline, overlays, recorder, CSV logger, FPS tracker; includes long-run segmentation/rotation note.
- `runtime/backends/*` - USB, Pi (Picamera2), and mock capture backends.

## Discovery
- `runtime/discovery/*` - USB/CSI probing, capability normalization, cache use, policy/backoff, and merge logic.

## Storage
- `storage/*` - disk guard, retention, session path resolution, metadata helpers, known cameras persistence.

## Tests (Spec Coverage)
- `rpi_logger/modules/Cameras2/tests/modules/cameras2/*` - test specs mirroring the runtime/storage/discovery/pipeline components (registry, preview/record pipelines, discovery, disk guard, retention, known cameras).

## Conventions
- All files are spec docstrings only; add implementation under the same paths to keep tests aligned.
- Async-first, Picamera2-aligned for CSI cams, with shared prefs/config between GUI and headless via stub module plumbing.
