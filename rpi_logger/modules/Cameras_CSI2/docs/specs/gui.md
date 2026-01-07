# GUI Specification

> Visual requirements for the user interface

## Visual Requirements

The GUI must be **visually identical** to the current CSICameras module.

- Same dark theme
- Same preview canvas with centered image
- Same metrics display (Cap In/Max, Rec Out/Tgt, Disp/Tgt)
- Same settings window layout
- Same FPS color coding

---

## Theme Constants

Use existing theme from `rpi_logger.core.ui.theme`:

| Constant | Value | Usage |
|----------|-------|-------|
| BG_DARK | #2b2b2b | Main background |
| BG_LIGHT | #3c3c3c | Panel background |
| TEXT | #ffffff | Primary text |
| TEXT_DIM | #999999 | Secondary text |
| ACCENT | #4a90d9 | Highlights, buttons |
| SUCCESS | #4caf50 | Good status (green) |
| WARNING | #ff9800 | Warning status (orange) |
| ERROR | #f44336 | Error status (red) |

---

## Metrics Display

Three columns showing real-time capture statistics:

| Field | Label | Format | Example |
|-------|-------|--------|---------|
| Capture | "Cap In/Max" | `{actual:.1f} / {max:.1f}` | "60.2 / 60.4" |
| Record | "Rec Out/Tgt" | `{actual:.1f} / {target:.1f}` | "30.0 / 30.0" |
| Preview | "Disp/Tgt" | `{actual:.1f} / {target:.1f}` | "5.1 / 5.0" |

### FPS Color Coding

| Condition | Color | Meaning |
|-----------|-------|---------|
| actual >= 95% of target | Green | Healthy |
| actual >= 80% of target | Orange | Warning |
| actual < 80% of target | Red | Problem |

---

## Settings Window

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

### Reuse from Base

- `CameraSettingsWindowBase` (1050+ lines of UI code)
- Theme integration via `rpi_logger.core.ui.theme`
- `CapabilityValidator` for settings validation

### CSI-Specific Overrides

- No audio controls (CSI cameras don't have audio)
- Preview scale options appropriate for high-res sensor
- Exposure controls specific to CSI sensors

---

## Preview Canvas

- Centered image within available space
- Maintains aspect ratio
- Dark background where image doesn't fill

### PPM Format for Tk

```python
header = f"P6\n{width} {height}\n255\n".encode('ascii')
ppm_data = header + rgb.tobytes()
# Use PhotoImage(data=ppm_data) for Tk
```

No PIL required, very fast.

---

## Layout

```
┌────────────────────────────────────────┐
│              Preview Canvas            │
│                                        │
│           [Centered Image]             │
│                                        │
├────────────────────────────────────────┤
│ Cap In/Max: 60.2/60.4  │ Rec: 30.0/30.0│
│            │ Disp: 5.1/5.0  [Settings] │
└────────────────────────────────────────┘
```

---

## Dialogs

### Sensor Info Dialog

Shows camera sensor information:
- Sensor model
- Resolution
- Supported frame rates
- Current settings

### Help Dialog

Shows module help text:
- Controls overview
- Keyboard shortcuts
- Troubleshooting tips
