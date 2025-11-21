"""
Configuration dialog specification.

- Purpose: pop-out window listing all discovered/known cameras with capability-driven selectors (resolution/FPS, formats, overlays, save options).
- Responsibilities: fetch capabilities from registry/cache, apply capture_settings service on save, support defaults/reset, and close cleanly.
- Behavior: dialog may open while discovery is still running; must update dynamically as cameras appear/disappear; applies selections without blocking UI.
- Logging: dialog open/close, apply/cancel actions, validation failures, and applied settings per camera.
- Constraints: Tk-safe updates; asyncio tasks for any IO; no blocking calls; ensure dialog handles disappearing cameras gracefully.
"""
