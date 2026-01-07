# Phase 5: Preview System

## Quick Reference

| Task | Status | Dependencies | Effort | Spec |
|------|--------|--------------|--------|------|
| P5.1 Preview frame generation | available | P2.3 | Small | `specs/gui.md` |
| P5.2 Canvas display widget | available | - | Medium | `specs/gui.md` |
| P5.3 Metrics panel | available | P5.2 | Small | `specs/gui.md` |

## Goal

Build real-time preview display with performance metrics.

---

## P5.1: Preview Frame Generation

### Deliverables

Integrated into `bridge.py` capture loop (P2.3).

### Implementation

```python
# In CamerasRuntime (bridge.py)

async def _push_preview(self, frame: CaptureFrame) -> None:
    if not self._view:
        return

    # Get canvas dimensions
    canvas_w, canvas_h = self._view.canvas_size
    if canvas_w <= 0 or canvas_h <= 0:
        return

    # Decode JPEG to numpy array
    import numpy as np
    import cv2

    nparr = np.frombuffer(frame.data, np.uint8)
    img = await asyncio.to_thread(cv2.imdecode, nparr, cv2.IMREAD_COLOR)

    if img is None:
        return

    # Calculate scale to fit canvas while maintaining aspect ratio
    src_h, src_w = img.shape[:2]
    scale = min(canvas_w / src_w, canvas_h / src_h)
    new_w = int(src_w * scale)
    new_h = int(src_h * scale)

    # Resize
    img = await asyncio.to_thread(
        cv2.resize, img, (new_w, new_h), interpolation=cv2.INTER_LINEAR
    )

    # Convert BGR to RGB
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

    # Create PPM format for Tkinter PhotoImage
    ppm_header = f"P6\n{new_w} {new_h}\n255\n".encode('ascii')
    ppm_data = ppm_header + img.tobytes()

    # Push to view (thread-safe via Tkinter's after())
    self._view.push_frame(ppm_data)
```

### Optimization Notes

- Use `cv2.INTER_LINEAR` for speed (not `INTER_CUBIC`)
- PPM format avoids extra encoding overhead
- Resize before color conversion for efficiency

### Validation

- [ ] Frame scaled to canvas size
- [ ] Aspect ratio preserved
- [ ] BGR to RGB conversion correct
- [ ] PPM format valid

---

## P5.2: Canvas Display Widget

### Deliverables

| File | Contents |
|------|----------|
| `app/view.py` | CameraView class |

### Implementation

```python
# app/view.py
import tkinter as tk
from tkinter import ttk

class CameraView:
    def __init__(
        self,
        parent: tk.Widget,
        on_settings: callable = None,
        on_control_change: callable = None
    ):
        self._parent = parent
        self._on_settings = on_settings
        self._on_control_change = on_control_change
        self._photo_image = None
        self._frame_count = 0

    def build_ui(self) -> tk.Frame:
        self._frame = ttk.Frame(self._parent)

        # Menu bar
        self._build_menu()

        # Preview canvas
        self._canvas = tk.Canvas(
            self._frame,
            bg='black',
            highlightthickness=0
        )
        self._canvas.pack(fill=tk.BOTH, expand=True)

        # Bind resize event
        self._canvas.bind('<Configure>', self._on_canvas_resize)

        # Metrics panel
        self._metrics_frame = ttk.Frame(self._frame)
        self._metrics_frame.pack(fill=tk.X, pady=2)
        self._build_metrics_panel()

        return self._frame

    def _build_menu(self) -> None:
        menubar = tk.Menu(self._parent)

        # File menu
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Exit", command=self._parent.quit, accelerator="Ctrl+Q")
        menubar.add_cascade(label="File", menu=file_menu)

        # Controls menu
        controls_menu = tk.Menu(menubar, tearoff=0)
        controls_menu.add_command(
            label="Settings...",
            command=self._open_settings,
            accelerator="Ctrl+,"
        )
        controls_menu.add_command(label="Sensor Info...", command=self._open_sensor_info)
        menubar.add_cascade(label="Controls", menu=controls_menu)

        # Help menu
        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="Help", command=self._open_help)
        help_menu.add_command(label="About", command=self._open_about)
        menubar.add_cascade(label="Help", menu=help_menu)

        self._parent.config(menu=menubar)

        # Keyboard shortcuts
        self._parent.bind('<Control-q>', lambda e: self._parent.quit())
        self._parent.bind('<Control-comma>', lambda e: self._open_settings())

    @property
    def canvas_size(self) -> tuple[int, int]:
        return (self._canvas.winfo_width(), self._canvas.winfo_height())

    def push_frame(self, ppm_data: bytes) -> None:
        # Schedule update on main thread
        self._canvas.after(0, self._update_frame, ppm_data)

    def _update_frame(self, ppm_data: bytes) -> None:
        try:
            self._photo_image = tk.PhotoImage(data=ppm_data)

            # Center image on canvas
            canvas_w = self._canvas.winfo_width()
            canvas_h = self._canvas.winfo_height()
            img_w = self._photo_image.width()
            img_h = self._photo_image.height()

            x = (canvas_w - img_w) // 2
            y = (canvas_h - img_h) // 2

            self._canvas.delete("all")
            self._canvas.create_image(x, y, anchor=tk.NW, image=self._photo_image)

            self._frame_count += 1
        except tk.TclError:
            pass  # Widget destroyed

    def _on_canvas_resize(self, event) -> None:
        # Redraw on resize (frame will be re-scaled by runtime)
        pass

    def _open_settings(self) -> None:
        if self._on_settings:
            self._on_settings()

    def _open_sensor_info(self) -> None:
        pass  # Implemented in phase 6

    def _open_help(self) -> None:
        pass  # Show help dialog

    def _open_about(self) -> None:
        pass  # Show about dialog
```

### Validation

- [ ] Canvas fills available space
- [ ] Frame centered with black letterbox
- [ ] Menu items functional
- [ ] Keyboard shortcuts work
- [ ] Thread-safe frame updates

---

## P5.3: Metrics Panel

### Deliverables

Complete metrics panel in `app/view.py`.

### Implementation

```python
# In CameraView (app/view.py)

def _build_metrics_panel(self) -> None:
    # Camera label
    self._cam_label = ttk.Label(self._metrics_frame, text="Cam: --")
    self._cam_label.pack(side=tk.LEFT, padx=5)

    ttk.Separator(self._metrics_frame, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=5)

    # Input FPS
    self._in_label = ttk.Label(self._metrics_frame, text="In: --")
    self._in_label.pack(side=tk.LEFT, padx=5)

    ttk.Separator(self._metrics_frame, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=5)

    # Record FPS
    self._rec_label = ttk.Label(self._metrics_frame, text="Rec: --")
    self._rec_label.pack(side=tk.LEFT, padx=5)

    ttk.Separator(self._metrics_frame, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=5)

    # Queue depth
    self._queue_label = ttk.Label(self._metrics_frame, text="Q: --")
    self._queue_label.pack(side=tk.LEFT, padx=5)

    # Recording indicator (right side)
    self._rec_indicator = ttk.Label(self._metrics_frame, text="")
    self._rec_indicator.pack(side=tk.RIGHT, padx=10)

def set_camera_name(self, name: str) -> None:
    short_name = name[:20] if len(name) > 20 else name
    self._cam_label.config(text=f"Cam: {short_name}")

def update_metrics(
    self,
    capture_fps: float,
    record_fps: float,
    queue_depth: int,
    target_fps: float = 30.0
) -> None:
    # Update labels
    self._in_label.config(
        text=f"In: {capture_fps:.1f}",
        foreground=self._fps_color(capture_fps, target_fps)
    )

    if record_fps > 0:
        self._rec_label.config(
            text=f"Rec: {record_fps:.1f}",
            foreground=self._fps_color(record_fps, target_fps)
        )
    else:
        self._rec_label.config(text="Rec: --", foreground="gray")

    queue_color = "red" if queue_depth > 2 else "black"
    self._queue_label.config(text=f"Q: {queue_depth}", foreground=queue_color)

def _fps_color(self, actual: float, target: float) -> str:
    if target <= 0:
        return "black"
    ratio = actual / target
    if ratio >= 0.95:
        return "green"
    elif ratio >= 0.80:
        return "orange"
    return "red"

def set_recording_state(self, recording: bool) -> None:
    if recording:
        self._rec_indicator.config(text="REC", foreground="red")
    else:
        self._rec_indicator.config(text="")
```

### Validation

- [ ] All metrics displayed
- [ ] FPS color coding works
- [ ] Queue depth warning (red when > 2)
- [ ] Recording indicator visible
- [ ] Updates don't block UI
