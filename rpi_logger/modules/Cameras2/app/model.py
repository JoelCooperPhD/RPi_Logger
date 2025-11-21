"""
Model specification for Cameras2 (UI-facing state container).

Responsibilities:
- Hold discovered cameras, their capabilities (res/FPS), selection status, preview/record activation state, and last-known user configs.
- Persist window geometry and UI preferences (tabs, metrics visibility, config dialog state) using base prefs API. Persist per-camera defaults (preview/record size/FPS/format/overlay) under ModulePreferences-friendly keys so GUI and headless launches reuse the same values when a user configures once in the GUI then records from CLI.
- Expose observable properties/signals for view updates (tab add/remove, status updates, metrics changes).
- Maintain mapping to known cameras cache for rapid startup; merge cached defaults without probing when safe.
- Stub (codex) alignment: either wrap/compose `StubCodexModel` or mirror its responsibilities:
  - Use `ModulePreferences` / `resolve_module_config_path` for config persistence; honor `window_geometry` read/write and saved preview defaults similar to stub.
  - Expose `shutdown_event`, `mark_ready()`, and metrics similar to StubCodexModel so supervisor and controller reuse flow.
  - Integrate with StatusMessage emissions (`INITIALIZING`/`IDLE`/`QUITTING`) through controller.
Constraints:
- asyncio-friendly notifications; no blocking IO; prefer async file writes via base storage utils.
- Thread safety: avoid cross-thread Tk calls; all model updates scheduled on main loop.
Logging:
- State transitions (discovered -> selected -> previewing -> recording), capability loads, preference persistence, and errors.
"""
