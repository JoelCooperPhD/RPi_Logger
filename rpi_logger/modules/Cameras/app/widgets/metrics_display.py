"""Metrics display component for Cameras IO stub line."""

from __future__ import annotations

from typing import Any, Dict, Optional

from rpi_logger.core.logging_utils import LoggerLike, ensure_structured_logger

try:
    from rpi_logger.core.ui.theme.colors import Colors
    HAS_THEME = True
except ImportError:
    HAS_THEME = False
    Colors = None


def format_fps_value(value: Any) -> str:
    """Format a FPS value for display."""
    try:
        return f"{float(value):5.1f}"
    except (ValueError, TypeError):
        return "   --"


def calculate_fps_color(actual: Any, target: Any) -> Optional[str]:
    """
    Calculate color based on how close actual FPS is to target.

    Returns a color string if theming is available, None otherwise.
    """
    if not HAS_THEME or Colors is None:
        return None

    try:
        if actual is not None and target is not None and float(target) > 0:
            pct = (float(actual) / float(target)) * 100
            if pct >= 95:
                return Colors.SUCCESS   # Green - good
            elif pct >= 80:
                return Colors.WARNING   # Orange - warning
            else:
                return Colors.ERROR     # Red - bad
    except (ValueError, TypeError):
        pass

    return Colors.FG_PRIMARY


class MetricsDisplay:
    """
    Manages the metrics display in the Cameras IO stub line.

    Handles:
    - Creating StringVars and Labels for metrics fields
    - Updating values with proper formatting
    - Applying color based on FPS performance
    - Preserving last known values when metrics are temporarily unavailable
    """

    FIELDS = [
        ("cam", "Cam"),
        ("cap_tgt", "Cap In/Tgt"),
        ("rec_tgt", "Rec Out/Tgt"),
        ("disp_tgt", "Disp/Tgt"),
    ]

    def __init__(self, root: Any, *, logger: LoggerLike = None) -> None:
        self._logger = ensure_structured_logger(logger, fallback_name=__name__)
        self._root = root
        self._fields: Dict[str, Any] = {}  # StringVars
        self._labels: Dict[str, Any] = {}  # Label widgets for color updates
        self._history: Dict[str, Dict[str, str]] = {}  # Last known values per camera
        self._latest_metrics: Dict[str, Dict[str, Any]] = {}
        self._active_camera_id: Optional[str] = None

    def install(self, stub_view: Any, tk: Any, ttk: Any) -> None:
        """Install the metrics display into the stub view's IO content area."""
        builder = getattr(stub_view, "build_io_stub_content", None)
        if not callable(builder):
            return

        # Initialize StringVars
        for key, _ in self.FIELDS:
            self._fields[key] = tk.StringVar(master=self._root, value="-")

        def _builder(frame) -> None:
            # Use themed colors if available
            if HAS_THEME and Colors is not None:
                container = tk.Frame(frame, bg=Colors.BG_FRAME)
            else:
                container = ttk.Frame(frame)
            container.grid(row=0, column=0, sticky="ew")
            for idx in range(len(self.FIELDS)):
                container.columnconfigure(idx, weight=1, uniform="iofields")

            for col, (key, label_text) in enumerate(self.FIELDS):
                if HAS_THEME and Colors is not None:
                    name = tk.Label(
                        container, text=label_text, anchor="center",
                        bg=Colors.BG_FRAME, fg=Colors.FG_SECONDARY
                    )
                    val = tk.Label(
                        container, textvariable=self._fields[key], anchor="center",
                        bg=Colors.BG_FRAME, fg=Colors.FG_PRIMARY, font=("TkFixedFont", 9)
                    )
                else:
                    name = ttk.Label(container, text=label_text, anchor="center")
                    val = ttk.Label(container, textvariable=self._fields[key], anchor="center")
                    try:
                        val.configure(font=("TkFixedFont", 9))
                    except Exception:
                        pass
                name.grid(row=0, column=col, sticky="ew", padx=2)
                val.grid(row=1, column=col, sticky="ew", padx=2)
                self._labels[key] = val

        try:
            builder(_builder)
        except Exception:
            self._logger.debug("IO stub content build failed", exc_info=True)

        self._update_display()

    def update_metrics(self, camera_id: str, metrics: Dict[str, Any]) -> None:
        """Update stored metrics for a camera."""
        self._latest_metrics[camera_id] = metrics or {}
        if camera_id == self._active_camera_id:
            self._update_display()

    def set_active_camera(self, camera_id: Optional[str]) -> None:
        """Set the currently active camera for display."""
        self._active_camera_id = camera_id
        self._update_display()

    def clear_camera(self, camera_id: str) -> None:
        """Clear metrics and history for a removed camera."""
        self._latest_metrics.pop(camera_id, None)
        self._history.pop(camera_id, None)
        if self._active_camera_id == camera_id:
            self._update_display()

    def _update_display(self) -> None:
        """Update the display with current metrics."""
        if not self._fields:
            return

        cam_id = self._active_camera_id or "-"
        payload = self._latest_metrics.get(cam_id, {}) if self._active_camera_id else {}

        # Capture metrics: fps_capture vs target_fps
        cap_actual = payload.get("fps_capture")
        cap_target = payload.get("target_fps")
        cap_tgt_str = f"{format_fps_value(cap_actual)} / {format_fps_value(cap_target)}"
        cap_color = calculate_fps_color(cap_actual, cap_target)

        # Record metrics: fps_encode vs target_record_fps
        rec_actual = payload.get("fps_encode")
        rec_target = payload.get("target_record_fps")
        rec_tgt_str = f"{format_fps_value(rec_actual)} / {format_fps_value(rec_target)}"
        rec_color = calculate_fps_color(rec_actual, rec_target)

        # Display metrics: fps_preview vs target_preview_fps
        disp_actual = payload.get("fps_preview")
        disp_target = payload.get("target_preview_fps")
        disp_tgt_str = f"{format_fps_value(disp_actual)} / {format_fps_value(disp_target)}"
        disp_color = calculate_fps_color(disp_actual, disp_target)

        values = {
            "cam": cam_id,
            "cap_tgt": cap_tgt_str,
            "rec_tgt": rec_tgt_str,
            "disp_tgt": disp_tgt_str,
        }
        history = self._history.setdefault(cam_id, {})

        # Update field values, preserving last known values
        for key, var in self._fields.items():
            new_val = values.get(key, "--")
            if self._is_placeholder(new_val) and history.get(key):
                new_val = history[key]
            else:
                history[key] = new_val
            try:
                var.set(new_val)
            except Exception:
                self._logger.debug("Failed to update IO stub field %s", key, exc_info=True)

        # Apply colors to ratio labels
        for key, color in [("cap_tgt", cap_color), ("rec_tgt", rec_color), ("disp_tgt", disp_color)]:
            if key in self._labels and color:
                try:
                    self._labels[key].configure(fg=color)
                except Exception:
                    pass

    @staticmethod
    def _is_placeholder(text: str) -> bool:
        """Check if text is a placeholder value."""
        return text in {"   --", "  --", " --", "--", "-", None} or (text and text.strip() == "--")


__all__ = ["MetricsDisplay", "format_fps_value", "calculate_fps_color"]
