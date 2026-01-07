# Phase 6: Settings UI

## Quick Reference

| Task | Status | Dependencies | Effort | Spec |
|------|--------|--------------|--------|------|
| P6.1 Settings window | available | P5.2 | Medium | `specs/gui.md` |
| P6.2 Camera controls | available | P6.1, P1.4 | Medium | `specs/gui.md` |
| P6.3 Apply config handler | available | P6.1, P4.3 | Small | `specs/commands.md` |

## Goal

Build settings dialog for resolution, FPS, and camera controls.

---

## P6.1: Settings Window

### Deliverables

| File | Contents |
|------|----------|
| `app/widgets/camera_settings_window.py` | CameraSettingsWindow class |

### Implementation

```python
# app/widgets/camera_settings_window.py
import tkinter as tk
from tkinter import ttk
from typing import Callable
from ...camera_core.types import CameraCapabilities, CapabilityMode

class CameraSettingsWindow:
    def __init__(
        self,
        parent: tk.Widget,
        capabilities: CameraCapabilities,
        current_settings: dict,
        on_apply: Callable[[dict], None]
    ):
        self._parent = parent
        self._capabilities = capabilities
        self._current = current_settings
        self._on_apply = on_apply
        self._control_vars: dict[str, tk.Variable] = {}

        self._window = tk.Toplevel(parent)
        self._window.title("Camera Settings")
        self._window.transient(parent)
        self._window.grab_set()

        self._build_ui()

        # Center on parent
        self._window.geometry("+%d+%d" % (
            parent.winfo_rootx() + 50,
            parent.winfo_rooty() + 50
        ))

    def _build_ui(self) -> None:
        main = ttk.Frame(self._window, padding=10)
        main.pack(fill=tk.BOTH, expand=True)

        # Preview section
        preview_frame = ttk.LabelFrame(main, text="Preview", padding=5)
        preview_frame.pack(fill=tk.X, pady=5)

        self._preview_res_var = tk.StringVar(value=self._current.get("preview_resolution", "640x480"))
        self._preview_fps_var = tk.StringVar(value=str(self._current.get("preview_fps", 15)))

        ttk.Label(preview_frame, text="Resolution:").grid(row=0, column=0, sticky=tk.W, pady=2)
        preview_res_combo = ttk.Combobox(
            preview_frame,
            textvariable=self._preview_res_var,
            values=self._get_preview_resolutions(),
            state="readonly",
            width=15
        )
        preview_res_combo.grid(row=0, column=1, pady=2, padx=5)

        ttk.Label(preview_frame, text="FPS:").grid(row=1, column=0, sticky=tk.W, pady=2)
        preview_fps_combo = ttk.Combobox(
            preview_frame,
            textvariable=self._preview_fps_var,
            values=["5", "10", "15", "20", "30"],
            state="readonly",
            width=15
        )
        preview_fps_combo.grid(row=1, column=1, pady=2, padx=5)

        # Recording section
        record_frame = ttk.LabelFrame(main, text="Recording", padding=5)
        record_frame.pack(fill=tk.X, pady=5)

        self._record_res_var = tk.StringVar(value=self._current.get("record_resolution", "1280x720"))
        self._record_fps_var = tk.StringVar(value=str(self._current.get("record_fps", 30)))

        ttk.Label(record_frame, text="Resolution:").grid(row=0, column=0, sticky=tk.W, pady=2)
        record_res_combo = ttk.Combobox(
            record_frame,
            textvariable=self._record_res_var,
            values=self._get_record_resolutions(),
            state="readonly",
            width=15
        )
        record_res_combo.grid(row=0, column=1, pady=2, padx=5)

        ttk.Label(record_frame, text="FPS:").grid(row=1, column=0, sticky=tk.W, pady=2)
        record_fps_combo = ttk.Combobox(
            record_frame,
            textvariable=self._record_fps_var,
            values=self._get_fps_values(),
            state="readonly",
            width=15
        )
        record_fps_combo.grid(row=1, column=1, pady=2, padx=5)

        # Camera controls section (placeholder, filled by P6.2)
        self._controls_frame = ttk.LabelFrame(main, text="Camera Controls", padding=5)
        self._controls_frame.pack(fill=tk.X, pady=5)

        # Options section
        options_frame = ttk.LabelFrame(main, text="Options", padding=5)
        options_frame.pack(fill=tk.X, pady=5)

        self._overlay_var = tk.BooleanVar(value=self._current.get("overlay", True))
        ttk.Checkbutton(
            options_frame,
            text="Timestamp overlay",
            variable=self._overlay_var
        ).pack(anchor=tk.W)

        # Buttons
        btn_frame = ttk.Frame(main)
        btn_frame.pack(fill=tk.X, pady=10)

        ttk.Button(btn_frame, text="Cancel", command=self._window.destroy).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_frame, text="Apply", command=self._apply).pack(side=tk.RIGHT)

        # Escape to close
        self._window.bind('<Escape>', lambda e: self._window.destroy())

    def _get_preview_resolutions(self) -> list[str]:
        modes = [m for m in self._capabilities.modes if m.width <= 640 and m.height <= 480]
        if not modes:
            modes = self._capabilities.modes[:5]
        seen = set()
        result = []
        for m in modes:
            res = f"{m.width}x{m.height}"
            if res not in seen:
                seen.add(res)
                result.append(res)
        return result

    def _get_record_resolutions(self) -> list[str]:
        seen = set()
        result = []
        for m in sorted(self._capabilities.modes, key=lambda x: x.width * x.height, reverse=True):
            res = f"{m.width}x{m.height}"
            if res not in seen:
                seen.add(res)
                result.append(res)
        return result

    def _get_fps_values(self) -> list[str]:
        fps_set = sorted(set(int(m.fps) for m in self._capabilities.modes))
        return [str(f) for f in fps_set]

    def _apply(self) -> None:
        settings = {
            "preview_resolution": self._parse_resolution(self._preview_res_var.get()),
            "preview_fps": int(self._preview_fps_var.get()),
            "record_resolution": self._parse_resolution(self._record_res_var.get()),
            "record_fps": int(self._record_fps_var.get()),
            "overlay": self._overlay_var.get(),
            "controls": self._get_control_values()
        }
        self._on_apply(settings)
        self._window.destroy()

    def _parse_resolution(self, res: str) -> tuple[int, int]:
        w, h = res.split('x')
        return (int(w), int(h))

    def _get_control_values(self) -> dict:
        return {name: var.get() for name, var in self._control_vars.items()}
```

### Validation

- [ ] Window opens as modal dialog
- [ ] Resolutions populated from capabilities
- [ ] FPS options correct
- [ ] Cancel closes without applying
- [ ] Escape key closes window

---

## P6.2: Camera Controls

### Deliverables

Complete camera controls section in settings window.

### Implementation

```python
# In CameraSettingsWindow (app/widgets/camera_settings_window.py)

def _build_controls(self) -> None:
    if not self._capabilities.controls:
        ttk.Label(self._controls_frame, text="No controls available").pack()
        return

    for name, info in self._capabilities.controls.items():
        self._build_control_widget(name, info)

def _build_control_widget(self, name: str, info) -> None:
    frame = ttk.Frame(self._controls_frame)
    frame.pack(fill=tk.X, pady=2)

    # Label
    display_name = name.replace('_', ' ').title()
    ttk.Label(frame, text=f"{display_name}:", width=15).pack(side=tk.LEFT)

    current_value = self._current.get("controls", {}).get(name, info.default_value or 0)

    if info.control_type == "bool":
        var = tk.BooleanVar(value=bool(current_value))
        ttk.Checkbutton(frame, variable=var).pack(side=tk.LEFT)

    elif info.control_type == "menu" and info.menu_items:
        var = tk.StringVar(value=info.menu_items.get(current_value, ""))
        combo = ttk.Combobox(
            frame,
            textvariable=var,
            values=list(info.menu_items.values()),
            state="readonly",
            width=20
        )
        combo.pack(side=tk.LEFT, padx=5)
        # Store reverse mapping for apply
        self._menu_reverse[name] = {v: k for k, v in info.menu_items.items()}

    else:  # int slider
        var = tk.IntVar(value=current_value)

        slider = ttk.Scale(
            frame,
            from_=info.min_value or 0,
            to=info.max_value or 255,
            variable=var,
            orient=tk.HORIZONTAL,
            length=150
        )
        slider.pack(side=tk.LEFT, padx=5)

        # Value label
        value_label = ttk.Label(frame, text=str(current_value), width=5)
        value_label.pack(side=tk.LEFT)

        # Update label on change
        def update_label(val, lbl=value_label, v=var):
            lbl.config(text=str(int(float(val))))
        slider.config(command=update_label)

    self._control_vars[name] = var

def _setup_control_dependencies(self) -> None:
    # Disable manual controls when auto is enabled
    auto_controls = {
        "exposure_auto": "exposure_absolute",
        "focus_auto": "focus_absolute",
        "white_balance_automatic": "white_balance_temperature"
    }

    for auto_name, manual_name in auto_controls.items():
        if auto_name in self._control_vars and manual_name in self._control_vars:
            auto_var = self._control_vars[auto_name]
            # Bind trace to enable/disable manual control
            auto_var.trace_add("write", lambda *args, a=auto_name, m=manual_name:
                self._update_control_state(a, m))
            # Set initial state
            self._update_control_state(auto_name, manual_name)

def _update_control_state(self, auto_name: str, manual_name: str) -> None:
    auto_var = self._control_vars.get(auto_name)
    manual_widget = self._control_widgets.get(manual_name)

    if auto_var and manual_widget:
        is_auto = bool(auto_var.get())
        state = "disabled" if is_auto else "normal"
        manual_widget.config(state=state)
```

### Validation

- [ ] Controls rendered based on type
- [ ] Sliders show current value
- [ ] Menu items populated correctly
- [ ] Auto/manual dependencies work
- [ ] Values collected on apply

---

## P6.3: Apply Config Handler

### Deliverables

Integration between settings window and runtime.

### Implementation

```python
# In CamerasRuntime (bridge.py)

async def _apply_config_changes(self, settings: dict) -> None:
    # Check if capture restart needed
    restart_capture = False

    preview_res = settings.get("preview_resolution")
    if preview_res:
        self._preview_width, self._preview_height = preview_res

    record_res = settings.get("record_resolution")
    if record_res and (record_res[0] != self._record_width or record_res[1] != self._record_height):
        self._record_width, self._record_height = record_res
        restart_capture = True

    record_fps = settings.get("record_fps")
    if record_fps and record_fps != self._record_fps:
        self._record_fps = record_fps
        self._capture_fps = record_fps
        restart_capture = True

    # Apply camera controls
    controls = settings.get("controls", {})
    for name, value in controls.items():
        await self._cmd_control_change({"control": name, "value": value})

    # Update overlay setting
    if "overlay" in settings:
        self._overlay_enabled = settings["overlay"]

    # Restart capture if needed
    if restart_capture and self._capture:
        await self._restart_capture()

async def _restart_capture(self) -> None:
    was_recording = self._state.recording

    # Stop capture loop
    self._stop_capture.set()
    if self._capture_task:
        await self._capture_task
        self._capture_task = None

    # Stop capture
    await self._capture.stop()

    # Restart with new settings
    from .camera_core.capture import USBCapture
    self._capture = USBCapture(
        device_path=self._state.descriptor.device_path,
        width=self._record_width,
        height=self._record_height,
        fps=self._capture_fps
    )
    await self._capture.start()

    # Restart loop
    self._stop_capture.clear()
    self._capture_task = asyncio.create_task(self._capture_loop())

    # Note: Recording state is NOT automatically restored
    # User must explicitly restart recording if desired
```

```python
# In CameraView (app/view.py)

def _open_settings(self) -> None:
    if not self._capabilities:
        return

    def on_apply(settings: dict):
        if self._on_settings:
            self._on_settings(settings)

    from .widgets.camera_settings_window import CameraSettingsWindow
    CameraSettingsWindow(
        parent=self._parent,
        capabilities=self._capabilities,
        current_settings=self._get_current_settings(),
        on_apply=on_apply
    )

def set_capabilities(self, capabilities) -> None:
    self._capabilities = capabilities

def _get_current_settings(self) -> dict:
    return {
        "preview_resolution": f"{self._preview_width}x{self._preview_height}",
        "preview_fps": self._preview_fps,
        "record_resolution": f"{self._record_width}x{self._record_height}",
        "record_fps": self._record_fps,
        "overlay": self._overlay_enabled,
        "controls": self._current_controls
    }
```

### Validation

- [ ] Settings window receives current values
- [ ] Apply triggers runtime update
- [ ] Capture restarts when resolution/FPS changes
- [ ] Controls applied without restart
- [ ] Recording NOT auto-resumed after restart
