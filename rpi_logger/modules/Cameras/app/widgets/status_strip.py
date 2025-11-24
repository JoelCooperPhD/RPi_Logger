"""
Status strip widget specification.

- Purpose: compact status bar showing discovery state, active cameras, recording indicator, disk space guard status, and last error tooltip.
- Behavior: updates from controller/model signals; shows transient messages (e.g., probing, recording started/stopped, device lost).
- Constraints: Tk-safe updates; no blocking; handles rapid message churn without flicker.
- Stub (codex) alignment: coexist with StubCodexView status/log panels; reuse its logging handler if present; respect preferences keys if stored via ModulePreferences.
- Logging: status transitions and surfaced error messages.
"""
