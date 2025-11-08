# Audio (Stub)

Lightweight audio capture module built entirely on the stub (codex) stack. The
module provides a GUI level meter when a Tk view is available and falls back to
headless operation otherwise.

## Architecture

- `main_audio_stub.py` handles CLI/config parsing and bootstraps the stub
  supervisor runtime.
- `audio_runtime.py` wires the stub supervisor to the audio MVC stack.
- `audio_mvc/`
  - `config.py` – normalizes CLI args and config file values.
  - `model.py` – observable audio state (devices, selections, session info).
  - `services/` – pure services for device discovery, session management, and
    sounddevice stream handling.
  - `view.py` – Tk widgets rendered inside the stub codex window, exposing
    device toggles and level meters.
  - `controller.py` – orchestrates services, updates the model, and bridges to
    the stub supervisor.

The implementation no longer imports the legacy `AudioRecorder` package; only
`sounddevice`, `numpy`, and the stub (codex) helpers are required.
