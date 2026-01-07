# GUI Specifications

## CameraView Layout

```
┌─────────────────────────────────────────────────────────┐
│ Menu Bar                                                │
│ [File] [Controls] [Help]                                │
├─────────────────────────────────────────────────────────┤
│                                                         │
│                                                         │
│                  Preview Canvas                         │
│                  (auto-resize)                          │
│                                                         │
│                                                         │
├─────────────────────────────────────────────────────────┤
│ Metrics: Cam: C920 | In: 30.0 | Rec: 29.9 | Q: 0      │
└─────────────────────────────────────────────────────────┘
```

## Menu Structure

### File Menu

| Item | Shortcut | Action |
|------|----------|--------|
| Exit | Ctrl+Q | Close module |

### Controls Menu

| Item | Shortcut | Action |
|------|----------|--------|
| Settings... | Ctrl+, | Open settings window |
| Sensor Info... | - | Show sensor information |

### Help Menu

| Item | Action |
|------|--------|
| Help | Open help dialog |
| About | Show version info |

---

## Settings Window

```
┌──────────────────────────────────────────┐
│ Camera Settings                     [X]  │
├──────────────────────────────────────────┤
│ Preview                                  │
│   Resolution: [640x480      ▼]           │
│   FPS:        [15           ▼]           │
│                                          │
│ Recording                                │
│   Resolution: [1280x720     ▼]           │
│   FPS:        [30           ▼]           │
│                                          │
│ ─────────────────────────────────────    │
│ Camera Controls                          │
│   Brightness:  [====●=====] 128          │
│   Contrast:    [===●======]  32          │
│   Exposure:    [Auto ▼]                  │
│     Value:     [========●=] 166          │
│   Focus:       [Auto ▼]                  │
│     Value:     [●=========]   0          │
│                                          │
│ ─────────────────────────────────────    │
│ Options                                  │
│   [x] Timestamp overlay                  │
│                                          │
├──────────────────────────────────────────┤
│              [Cancel]  [Apply]           │
└──────────────────────────────────────────┘
```

### Resolution Dropdowns

Populated from `CameraCapabilities.modes`:
- Preview: Filter to modes <= 640x480
- Record: All modes, sorted by resolution descending

### FPS Dropdowns

Populated based on selected resolution.

### Camera Controls

Dynamic based on `CameraCapabilities.controls`:

| Control Type | Widget |
|--------------|--------|
| int | Slider with value label |
| bool | Checkbox |
| menu | Dropdown |

### Control Dependencies

| If | Then |
|----|------|
| `exposure_auto = 1` (auto) | Disable exposure slider |
| `focus_auto = 1` (auto) | Disable focus slider |
| `white_balance_auto = 1` | Disable white balance slider |

---

## Metrics Panel

```
Cam: C920 | In: 30.0 | Rec: 29.9 | Q: 0 | Wait: 2ms
```

| Field | Description | Color Logic |
|-------|-------------|-------------|
| Cam | Camera short name | - |
| In | Input FPS (capture) | Green if >= 95% target |
| Rec | Recording FPS | Yellow if 80-95% target |
| Q | Queue depth | Red if > 2 |
| Wait | Frame wait time | Red if > 50ms |

### Color Thresholds

```python
def fps_color(actual: float, target: float) -> str:
    ratio = actual / target
    if ratio >= 0.95:
        return "green"
    elif ratio >= 0.80:
        return "yellow"
    return "red"
```

---

## Preview Canvas

### Behavior

- Auto-resize with window
- Maintain aspect ratio
- Center frame in canvas
- Black letterbox/pillarbox

### Frame Format

PPM (Portable Pixmap) for Tkinter PhotoImage:
```
P6
{width} {height}
255
{RGB data}
```

### Update Rate

Preview updates at `preview_fps` (default 10 FPS), independent of capture FPS.

---

## Sensor Info Dialog

```
┌──────────────────────────────────────────┐
│ Sensor Information                  [X]  │
├──────────────────────────────────────────┤
│ Model: Logitech C920                     │
│                                          │
│ Sensor Type: CMOS                        │
│ Shutter: Rolling                         │
│ Intended Use: Video conferencing         │
│                                          │
│ Capabilities:                            │
│   - Auto exposure                        │
│   - Auto focus                           │
│   - Auto white balance                   │
│   - Digital zoom                         │
│                                          │
│ Notes:                                   │
│   Good low-light performance.            │
│   H.264 encoding available but not used. │
├──────────────────────────────────────────┤
│                   [Close]                │
└──────────────────────────────────────────┘
```

Data source: `camera_models.json` sensor_info field.

---

## Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| Ctrl+Q | Exit |
| Ctrl+, | Open settings |
| Space | Toggle recording (if supported) |
| Escape | Close dialog |
