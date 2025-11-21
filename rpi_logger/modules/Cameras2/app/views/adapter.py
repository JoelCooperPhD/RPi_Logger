"""
View adapter specification.

- Purpose: translate runtime/model events into concrete StubCodexView updates (tab add/remove, preview frame pushes, status messages, metrics updates).
- Responsibilities: manage thread-safe scheduling into Tk loop, coalesce rapid updates, and expose hooks to controller/registry for UI changes.
- Stub (codex) alignment: leverage StubCodexView logging handler attachment and status channels; reuse its scheduling helpers if available; respect preference keys from ModulePreferences when toggling panels.
- Logging: every tab add/remove, preview frame drop, UI error; include camera identifiers and timing.
- Constraints: async-friendly wrapper around Tk; no blocking; defensive against missing view (headless mode).
"""
