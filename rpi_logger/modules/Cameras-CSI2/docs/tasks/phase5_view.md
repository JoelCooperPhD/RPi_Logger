# Phase 5: View

> GUI layer - visually identical to current module

## Quick Reference

| | |
|-|-|
| **Status** | See [TASKS.md](../TASKS.md) |
| **Task** | P5 (single task) |
| **Dependencies** | P4 |
| **Effort** | Medium |
| **Key Specs** | [gui.md](../specs/gui.md) |

## Goal

Create a GUI that is **visually identical** to the current CSICameras module.

---

## Deliverables

### view/view.py (~150 lines)

Main view coordinator.

```python
class CSICameraView:
    def __init__(self, parent: tk.Frame, runtime: 'CSICameraRuntime'): ...
    def push_frame(self, ppm_data: bytes) -> None: ...
    def update_metrics(self, metrics: MetricsReport) -> None: ...
    def show_settings(self) -> None: ...
    def on_recording_started(self) -> None: ...
    def on_recording_stopped(self) -> None: ...
```

**UI Elements**:
- Preview canvas (centered image)
- Metrics display row (Cap In/Max, Rec Out/Tgt, Disp/Tgt)
- Settings button

### view/settings_window.py (~100 lines)

Subclass of `CameraSettingsWindowBase`.

```python
class CSICameraSettingsWindow(CameraSettingsWindowBase):
    WINDOW_TITLE_PREFIX = "CSI Camera Settings"
    SUPPORTS_AUDIO = False
    USES_PREVIEW_SCALE = True
    PREVIEW_SCALE_OPTIONS = ["1/2", "1/4", "1/8"]
    PREVIEW_FPS_OPTIONS = ("1", "2", "5", "10")

    IMAGE_CONTROLS = ["Brightness", "Contrast", "Saturation", "Sharpness"]
    EXPOSURE_FOCUS_CONTROLS = ["AeExposureMode", "ExposureTime", "AnalogueGain", ...]
```

**Reuse from base**:
- `CameraSettingsWindowBase` (1050+ lines of UI code)
- Theme integration via `rpi_logger.core.ui.theme`
- `CapabilityValidator` for settings validation

### view/dialogs/ (~60 lines total)

- `sensor_info.py` - Sensor information dialog
- `help.py` - Help dialog

---

## Implementation Notes

### Theme Constants

Use existing theme from `rpi_logger.core.ui.theme`:
- BG_DARK: #2b2b2b
- BG_LIGHT: #3c3c3c
- TEXT: #ffffff
- ACCENT: #4a90d9

### Metrics Display Format

| Field | Label | Format |
|-------|-------|--------|
| Capture | "Cap In/Max" | `{actual_fps:.1f} / {hardware_max:.1f}` |
| Record | "Rec Out/Tgt" | `{actual_fps:.1f} / {target_fps:.1f}` |
| Preview | "Disp/Tgt" | `{actual_fps:.1f} / {target_fps:.1f}` |

### FPS Color Coding

- Green: >= 95% of target
- Orange: >= 80% of target
- Red: < 80% of target

---

## Validation Checklist

- [ ] All files created
- [ ] Visual comparison: Screenshot current vs new, pixel diff
- [ ] Settings window opens and shows all controls
- [ ] Metrics display updates correctly
- [ ] All buttons/controls work identically

---

## Completion Criteria

When all validation items pass, update [TASKS.md](../TASKS.md).
