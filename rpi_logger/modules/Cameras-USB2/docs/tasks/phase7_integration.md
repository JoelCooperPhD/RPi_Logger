# Phase 7: Integration & Entry Point

## Quick Reference

| Task | Status | Dependencies | Effort | Spec |
|------|--------|--------------|--------|------|
| P7.1 Main entry point | available | P4.4 | Small | - |
| P7.2 CameraView composition | available | P5.3, P6.3 | Medium | `specs/gui.md` |
| P7.3 End-to-end testing | available | P7.1, P7.2 | Medium | - |

## Goal

Wire everything together and validate complete functionality.

---

## P7.1: Main Entry Point

### Deliverables

| File | Contents |
|------|----------|
| `main_cameras.py` | Module entry point |
| `__init__.py` | Package exports |

### Implementation

```python
# main_cameras.py
import asyncio
import argparse
from pathlib import Path

MODULE_DISPLAY_NAME = "Cameras-USB2"
MODULE_ID = "cameras_usb2"

def parse_args():
    parser = argparse.ArgumentParser(description=MODULE_DISPLAY_NAME)
    parser.add_argument("--config", type=Path, help="Config file path")
    parser.add_argument("--output-dir", type=Path, help="Output directory")
    parser.add_argument("--session-prefix", type=str, default="recording")
    parser.add_argument("--no-console", action="store_true", help="Disable console logging")
    return parser.parse_args()

async def main():
    args = parse_args()

    # Load configuration
    from .config import CamerasConfig
    config = CamerasConfig.from_preferences({}, {
        "output_dir": args.output_dir,
    })

    # Create runtime
    from .bridge import CamerasRuntime
    runtime = CamerasRuntime(config=config)

    # Initialize
    await runtime.initialize()

    # If running standalone (not under supervisor), run event loop
    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        await runtime.shutdown()

def run():
    asyncio.run(main())

if __name__ == "__main__":
    run()
```

```python
# __init__.py
from .bridge import CamerasRuntime
from .config import CamerasConfig

__all__ = ["CamerasRuntime", "CamerasConfig"]
```

### CLI Usage

```bash
# Standalone
python -m rpi_logger.modules.Cameras-USB2.main_cameras

# With options
python -m rpi_logger.modules.Cameras-USB2.main_cameras \
    --config /path/to/config.txt \
    --output-dir /data/recordings \
    --session-prefix experiment_001
```

### Validation

- [ ] Module runs standalone
- [ ] CLI arguments parsed correctly
- [ ] Config loaded from file
- [ ] Clean shutdown on Ctrl+C

---

## P7.2: CameraView Composition

### Deliverables

Complete view integration in runtime.

### Implementation

```python
# In main_cameras.py - GUI mode

import tkinter as tk

async def main_gui():
    args = parse_args()

    # Create Tkinter root
    root = tk.Tk()
    root.title(MODULE_DISPLAY_NAME)
    root.geometry("800x600")

    # Load configuration
    from .config import CamerasConfig
    config = CamerasConfig.from_preferences({}, {
        "output_dir": args.output_dir,
    })

    # Create view
    from .app.view import CameraView

    def on_settings(settings: dict):
        asyncio.create_task(runtime.handle_command("apply_config", settings))

    def on_control_change(control: str, value: int):
        asyncio.create_task(runtime.handle_command("control_change", {
            "control": control,
            "value": value
        }))

    view = CameraView(
        parent=root,
        on_settings=on_settings,
        on_control_change=on_control_change
    )
    view.build_ui().pack(fill=tk.BOTH, expand=True)

    # Create runtime with view
    from .bridge import CamerasRuntime

    async def status_callback(status: str, payload: dict):
        if status == "device_ready":
            view.set_camera_name(payload.get("name", "Camera"))
            view.set_capabilities(runtime._state.capabilities)
        elif status == "recording_started":
            view.set_recording_state(True)
        elif status == "recording_stopped":
            view.set_recording_state(False)

    runtime = CamerasRuntime(
        config=config,
        view=view,
        status_callback=status_callback
    )

    await runtime.initialize()

    # Tkinter/asyncio integration
    async def tk_update():
        while True:
            try:
                root.update()
                await asyncio.sleep(0.016)  # ~60 Hz
            except tk.TclError:
                break

    try:
        await tk_update()
    finally:
        await runtime.shutdown()

def run_gui():
    asyncio.run(main_gui())

if __name__ == "__main__":
    run_gui()
```

### Validation

- [ ] GUI window appears
- [ ] View receives status updates
- [ ] Settings callback wired correctly
- [ ] Clean window close
- [ ] Async/Tkinter integration works

---

## P7.3: End-to-End Testing

### Test Scenarios

#### 1. Device Assignment

```python
async def test_device_assignment():
    runtime = CamerasRuntime(config=CamerasConfig())
    await runtime.initialize()

    # Assign device
    await runtime.handle_command("assign_device", {
        "camera_id": {"backend": "usb", "stable_id": "test"},
        "descriptor": {
            "name": "Test Camera",
            "device_path": "/dev/video0"
        }
    })

    assert runtime._state.camera_id is not None
    assert runtime._state.capturing

    await runtime.shutdown()
```

#### 2. Recording Cycle

```python
async def test_recording_cycle():
    runtime = CamerasRuntime(config=CamerasConfig())
    await runtime.initialize()

    # Assign and start recording
    await runtime.handle_command("assign_device", {...})
    await runtime.handle_command("start_recording", {
        "session_prefix": "test",
        "trial_number": 1
    })

    assert runtime._state.recording

    # Wait for some frames
    await asyncio.sleep(2)

    # Stop recording
    await runtime.handle_command("stop_recording", {})

    assert not runtime._state.recording
    assert runtime._frames_recorded > 0

    await runtime.shutdown()
```

#### 3. Settings Change

```python
async def test_settings_change():
    runtime = CamerasRuntime(config=CamerasConfig())
    await runtime.initialize()
    await runtime.handle_command("assign_device", {...})

    original_fps = runtime._capture_fps

    await runtime.handle_command("apply_config", {
        "record_fps": 15
    })

    assert runtime._capture_fps == 15
    assert runtime._capture_fps != original_fps

    await runtime.shutdown()
```

#### 4. Error Recovery

```python
async def test_device_lost():
    runtime = CamerasRuntime(config=CamerasConfig())
    await runtime.initialize()
    await runtime.handle_command("assign_device", {...})

    # Simulate device disconnect
    # (Would need mock or actual disconnect)

    # Verify graceful handling
    assert not runtime._state.capturing

    await runtime.shutdown()
```

### Integration Checklist

- [ ] Camera discovery works
- [ ] Preview displays at target FPS
- [ ] Recording creates valid AVI file
- [ ] Timing CSV has correct format
- [ ] Settings changes apply correctly
- [ ] Camera controls functional
- [ ] Clean shutdown (no hung threads)
- [ ] Memory stable over long run
- [ ] CPU usage within targets
- [ ] Disk guard stops recording on low disk

### Manual Testing Steps

1. **Start module**: `python -m rpi_logger.modules.Cameras-USB2.main_cameras`
2. **Verify ready**: Check "ready" status reported
3. **Connect camera**: Should auto-detect or assign via supervisor
4. **Check preview**: Live feed visible, metrics updating
5. **Open settings**: Verify controls populated
6. **Change resolution**: Capture should restart
7. **Start recording**: "REC" indicator, files created
8. **Stop recording**: Files finalized, stats reported
9. **Fill disk**: Verify recording stops gracefully
10. **Disconnect camera**: Verify error handling
11. **Close window**: Clean shutdown, no errors

### Performance Benchmarks

| Metric | Target | Measure With |
|--------|--------|--------------|
| Startup to first frame | < 2s | Stopwatch |
| Preview latency | < 100ms | Visual comparison |
| Frame drop rate | < 0.1% | Compare timing CSV count to expected |
| Memory usage | < 200MB | `htop` or `ps aux` |
| CPU usage (1080p30) | < 30% | `htop` |
