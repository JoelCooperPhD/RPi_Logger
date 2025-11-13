# Audio

Lightweight audio capture module built entirely on the codex stack. The module
provides a GUI level meter when a Tk view is available and falls back to
command-line interaction otherwise.

## Architecture

- `main_audio.py` handles CLI/config parsing and bootstraps the supervisor
  runtime.
- `config/` contains the shared CLI + file parsing logic (`settings.py`).
- `app/` hosts the high-level `AudioApp` orchestration (`application.py`) and
  the persistence helpers that restore device selections (`startup.py`).
- `domain/` groups immutable constants, the observable state container, and the
  level meter logic.
- `services/` keeps the pure device/session/recorder helpers that interact with
  hardware and the filesystem.
- `ui/` isolates the Tk view + callbacks used by the codex shell.
- `runtime/` bundles the module runtime adapter consumed directly by the
  supervisor.

Only `sounddevice`, `numpy`, and the codex helpers are required.

The module persists the last selected devices in `config.txt` via the
`selected_devices` entry so relaunching the UI keeps the previous layout.
