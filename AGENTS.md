# Repository Guidelines

## Project Structure & Module Organization
RPi Logger centers on `main.py` for the async eye tracker workflow and `unified_master.py` for multi-sensor orchestration. Sensor-specific code lives in `Modules/`, split into `Cameras/` and `EyeTracker/` packages with runnable entrypoints and helpers. Automated tests sit under `tests/` alongside legacy device smoke checks in top-level `test_*.py`. Runtime artifacts land in `recordings/`, `unified_recordings/`, and `eye_tracking_data/`; keep large captures out of Git by cleaning them after validation.

## Build, Test, and Development Commands
Use `uv` to execute inside the locked environment:
- `uv run main.py --gui` launches the GUI controller; add `--headless --config session.json` for unattended runs.
- `uv run unified_master.py --demo --allow-partial` exercises orchestrated capture without hardware.
- `bash test_all_modules.sh` performs camera and eye-tracker discovery checks; `bash demo_run.sh` walks through the demo scenario.
Ensure the working directory is the repository root before running these commands.

## Coding Style & Naming Conventions
Target Python 3.11 features including `asyncio`, dataclasses, and `pathlib.Path`. Follow 4-space indentation, `snake_case` functions, `UPPER_CASE` constants, and `UpperCamelCase` classes. Keep async flows non-blocking by delegating CPU-heavy work to background tasks or subprocesses. Reuse the structured logging pattern (`logging.getLogger("module")`) and add docstrings plus concise comments only when behavior is non-obvious. Type hints are expected on new public interfaces.

## Testing Guidelines
Pytest with `pytest-asyncio` is the standard. Place new tests in files named `test_*.py` and mark coroutine tests with `@pytest.mark.asyncio`. Run focused suites via `uv run python -m pytest tests/test_eye_tracker.py` and the full set with `uv run python -m pytest`. Use temporary directories (`tmp_path`) for generated media and stub hardware interactions following the `DummyStreamHandler` approach.

## Commit & Pull Request Guidelines
Recent commits favor short, sentence-case subjects (e.g., `Refactor for frame timing v1`). Provide a brief summary in the body covering behavior changes, affected modules, and hardware assumptions. Pull requests should link issues, list the exact commands or scripts you ran, and attach relevant logs or screenshots when altering device streaming, timing, or storage behavior. Mention any deployment or configuration steps reviewers must reproduce.

## Device & Configuration Tips
Default settings assume Raspberry Pi OS 64-bit and connected sensors. Verify writable storage before recording; the system creates timestamped folders under `recordings/` and related directories. Store site-specific credentials or configs outside the repo and pass them via CLI flags or env vars during execution.
