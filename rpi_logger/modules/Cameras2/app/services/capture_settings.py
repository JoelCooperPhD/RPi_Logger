"""
Capture settings service specification.

- Purpose: manage application of per-camera resolution/FPS/format defaults derived from capabilities or known camera cache.
- Functions: resolve requested preview/record configs, validate against capabilities, clamp to safe ranges, and persist per-camera prefs.
- Integration: invoked by controller when user selects options or when a cached camera is restored; updates runtime.registry/state.
- Stub (codex) alignment: persist through ModulePreferences/config.txt keys similar to stub preview/save settings; honor saved defaults on startup; avoid custom file formats.
- Async/logging: non-blocking, heavy logging on mismatches or clamping; surface warnings if requested mode unsupported.
"""
