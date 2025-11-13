# Audio (Stub)

Lightweight audio capture module built entirely on the stub (codex) stack. The
module provides a GUI level meter when a Tk view is available and falls back to
headless operation otherwise.

## Architecture

- `main_audio_stub.py` handles CLI/config parsing and bootstraps the stub
  supervisor runtime.
- `audio_runtime.py` is now a thin shim that re-exports the packaged runtime
  living under `modules/audio_stub/runtime.py`.
- `modules/audio_stub/`
  - `config.py` – shared config loader used by both the CLI parser and runtime.
  - `app.py` – high-level `AudioApp` that wires managers, services, and view.
  - `startup.py` – persists device selections and restores them on launch.
  - `state.py` – observable audio state (devices, selections, session info).
  - `services/` – pure services for device discovery, session coordination, and
    streaming recorders that write directly to disk.
- `view.py` – Tk widgets rendered inside the stub codex window, exposing
  device toggles and level meters.

Only `sounddevice`, `numpy`, and the stub (codex) helpers are required.

The module now persists the last selected devices in `config.txt` via the
`selected_devices` entry so relaunching the UI keeps the previous layout.
