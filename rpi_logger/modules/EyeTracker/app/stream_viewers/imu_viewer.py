"""Enhanced IMU stream viewer with horizon indicator, motion state, and sparkline."""

from __future__ import annotations

import logging
import math
import time
from collections import deque
from typing import Any, Optional

try:
    import tkinter as tk
    from tkinter import ttk
except Exception:
    tk = None  # type: ignore
    ttk = None  # type: ignore

try:
    from rpi_logger.core.ui.theme import colors as _theme_colors  # noqa: F401

    HAS_THEME = True
    del _theme_colors
except ImportError:
    HAS_THEME = False

from .base_viewer import BaseStreamViewer

# Constants for visualization
GRAVITY_MPS2 = 9.81  # m/s²
HORIZON_SIZE = 80  # pixels
SPARKLINE_WIDTH = 180

# Colors (instrument-grade, muted professional palette)
SKY_COLOR = "#2a3f5f"  # Dark slate blue
GROUND_COLOR = "#4a3728"  # Dark brown
HORIZON_LINE_COLOR = "#c0c0c0"  # Silver/gray
AIRCRAFT_COLOR = "#e0e0e0"  # Light gray


def quaternion_to_euler(w: float, x: float, y: float, z: float) -> tuple[float, float, float]:
    """Convert quaternion to Euler angles (pitch, roll, yaw) in degrees.

    Uses aerospace/aviation convention:
    - Pitch: nose up (+) / down (-) - rotation around lateral axis
    - Roll: bank right (+) / left (-) - rotation around longitudinal axis
    - Yaw: turn right (+) / left (-) - rotation around vertical axis

    Args:
        w, x, y, z: Quaternion components (w is scalar part)

    Returns:
        Tuple of (pitch, roll, yaw) in degrees
    """
    # Roll (x-axis rotation)
    sinr_cosp = 2.0 * (w * x + y * z)
    cosr_cosp = 1.0 - 2.0 * (x * x + y * y)
    roll = math.atan2(sinr_cosp, cosr_cosp)

    # Pitch (y-axis rotation)
    sinp = 2.0 * (w * y - z * x)
    if abs(sinp) >= 1:
        # Use 90 degrees if out of range (gimbal lock)
        pitch = math.copysign(math.pi / 2, sinp)
    else:
        pitch = math.asin(sinp)

    # Yaw (z-axis rotation)
    siny_cosp = 2.0 * (w * z + x * y)
    cosy_cosp = 1.0 - 2.0 * (y * y + z * z)
    yaw = math.atan2(siny_cosp, cosy_cosp)

    # Convert to degrees
    return (
        math.degrees(roll),
        math.degrees(pitch),
        math.degrees(yaw),
    )


class IMUViewer(BaseStreamViewer):
    """Enhanced IMU viewer with horizon indicator, heading tape, and acceleration sparkline.

    Components:
    - Artificial horizon (pitch/roll visualization)
    - Heading tape (yaw visualization)
    - Acceleration sparkline (10-second rolling window)
    - All text data at bottom (orientation, accelerometer, gyroscope)
    """

    def __init__(
        self,
        parent: "tk.Frame",
        logger: logging.Logger,
        *,
        row: int = 0,
        sparkline_duration_sec: float = 10.0,
        yaw_drift_to_zero: bool = True,
        yaw_drift_duration_sec: float = 5.0,
    ) -> None:
        """Initialize the enhanced IMU viewer.

        Args:
            parent: Parent tkinter frame
            logger: Logger instance
            row: Grid row position
            sparkline_duration_sec: Duration of motion history to display
            yaw_drift_to_zero: If True, yaw gradually drifts to zero over time
            yaw_drift_duration_sec: Duration over which yaw drifts to zero
        """
        super().__init__(parent, "imu", logger, row=row)

        # Configuration
        self._sparkline_duration = sparkline_duration_sec
        self._yaw_drift_to_zero = yaw_drift_to_zero
        self._yaw_drift_duration = yaw_drift_duration_sec

        # Yaw drift tracking - stores (timestamp, raw_yaw) for smoothing
        self._yaw_reference: Optional[float] = None  # Reference yaw to subtract
        self._last_yaw_update: float = 0.0
        self._displayed_yaw: float = 0.0  # Current displayed yaw (drifts to zero)

        # Motion history buffer stores (timestamp, value) tuples
        # Use a generous maxlen to handle variable update rates; actual filtering is time-based
        max_samples = int(sparkline_duration_sec * 100)  # Allow up to 100 Hz
        self._motion_buffer: deque[tuple[float, float]] = deque(maxlen=max(max_samples, 100))

        # UI elements
        self._horizon_canvas: Optional["tk.Canvas"] = None
        self._heading_canvas: Optional["tk.Canvas"] = None
        self._sparkline_canvas: Optional["tk.Canvas"] = None

        # StringVars for text display (3 groups)
        self._orientation_var: Optional["tk.StringVar"] = None
        self._accel_var: Optional["tk.StringVar"] = None
        self._gyro_var: Optional["tk.StringVar"] = None

        # Track peak motion for annotation
        self._peak_motion: float = 0.0

    def build_ui(self) -> "ttk.Frame":
        """Build the enhanced IMU display with horizon, heading tape, and sparkline."""
        if ttk is None or tk is None:
            raise RuntimeError("Tkinter not available")

        self._frame = ttk.LabelFrame(self._parent, text="IMU", padding=(8, 4))
        self._frame.columnconfigure(0, weight=0)  # Horizon - fixed size
        self._frame.columnconfigure(1, weight=0)  # Compass - fixed size
        self._frame.columnconfigure(2, weight=1)  # Sparkline - expands

        label_style = "Inframe.TLabel" if HAS_THEME else None
        small_font = ("Consolas", 8)

        # === Row 0: Graphics row (side by side) ===

        # LEFT: Horizon indicator canvas (fixed size)
        self._horizon_canvas = tk.Canvas(
            self._frame,
            width=HORIZON_SIZE,
            height=HORIZON_SIZE,
            bg="#1a1a1a",
            highlightthickness=1,
            highlightbackground="#333333",
        )
        self._horizon_canvas.grid(row=0, column=0, padx=(0, 8), pady=4, sticky="n")
        self._draw_horizon(0.0, 0.0)  # Initial state

        # MIDDLE: Compass (yaw visualization) - fixed size square
        self._heading_canvas = tk.Canvas(
            self._frame,
            width=HORIZON_SIZE,
            height=HORIZON_SIZE,
            bg="#1a1a1a",
            highlightthickness=1,
            highlightbackground="#333333",
        )
        self._heading_canvas.grid(row=0, column=1, padx=(0, 8), pady=4, sticky="n")
        self._draw_heading_tape(0.0)  # Initial state

        # RIGHT: Sparkline canvas (acceleration) - expands horizontally
        self._sparkline_canvas = tk.Canvas(
            self._frame,
            width=SPARKLINE_WIDTH,
            height=HORIZON_SIZE,
            bg="#1a1a1a",
            highlightthickness=1,
            highlightbackground="#333333",
        )
        self._sparkline_canvas.grid(row=0, column=2, pady=4, sticky="nsew")

        # === Row 1: Text data in 3 equally-weighted frames ===
        text_container = ttk.Frame(self._frame)
        text_container.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(4, 0))
        text_container.columnconfigure(0, weight=1)
        text_container.columnconfigure(1, weight=1)
        text_container.columnconfigure(2, weight=1)

        # Orientation frame (P, R, Y)
        self._orientation_var = tk.StringVar(value="P: --.-  R: --.-  Y: --.-")
        orient_label = ttk.Label(text_container, textvariable=self._orientation_var, font=small_font, anchor="center")
        if label_style:
            orient_label.configure(style=label_style)
        orient_label.grid(row=0, column=0, sticky="ew")

        # Acceleration frame (|A|, Pk)
        self._accel_var = tk.StringVar(value="|A|: -.--g  Pk: -.--g")
        accel_label = ttk.Label(text_container, textvariable=self._accel_var, font=small_font, anchor="center")
        if label_style:
            accel_label.configure(style=label_style)
        accel_label.grid(row=0, column=1, sticky="ew")

        # Gyro frame (G x, y, z)
        self._gyro_var = tk.StringVar(value="G: --.-  --.-  --.-")
        gyro_label = ttk.Label(text_container, textvariable=self._gyro_var, font=small_font, anchor="center")
        if label_style:
            gyro_label.configure(style=label_style)
        gyro_label.grid(row=0, column=2, sticky="ew")

        return self._frame

    def _draw_horizon(self, pitch_deg: float, roll_deg: float) -> None:
        """Draw aviation-style artificial horizon.

        Args:
            pitch_deg: Pitch angle in degrees (+ = nose up)
            roll_deg: Roll angle in degrees (+ = bank right)
        """
        if self._horizon_canvas is None:
            return

        canvas = self._horizon_canvas
        canvas.delete("all")

        cx, cy = HORIZON_SIZE / 2, HORIZON_SIZE / 2
        radius = HORIZON_SIZE / 2 - 2

        # Clamp angles for display
        pitch = max(-45, min(45, pitch_deg))
        roll = max(-60, min(60, roll_deg))

        # Convert roll to radians for rotation
        # When head tilts counterclockwise (positive roll), horizon should tilt counterclockwise
        roll_rad = math.radians(roll)

        # Pitch shifts the horizon line vertically
        pitch_offset = (pitch / 45.0) * radius

        # Calculate horizon line endpoints (rotated by roll)
        # Start with horizontal line, then rotate
        half_width = radius * 1.5  # Extend beyond circle for clipping

        # Horizon line points before rotation
        x1, y1 = -half_width, pitch_offset
        x2, y2 = half_width, pitch_offset

        # Rotate points by roll angle
        cos_r, sin_r = math.cos(roll_rad), math.sin(roll_rad)
        rx1 = x1 * cos_r - y1 * sin_r + cx
        ry1 = x1 * sin_r + y1 * cos_r + cy
        rx2 = x2 * cos_r - y2 * sin_r + cx
        ry2 = x2 * sin_r + y2 * cos_r + cy

        # Draw sky (top half) - use a large polygon
        # We need to draw the sky above the rotated horizon line
        sky_points = self._get_half_circle_points(cx, cy, radius, rx1, ry1, rx2, ry2, top=True)
        if sky_points:
            canvas.create_polygon(sky_points, fill=SKY_COLOR, outline="")

        # Draw ground (bottom half)
        ground_points = self._get_half_circle_points(cx, cy, radius, rx1, ry1, rx2, ry2, top=False)
        if ground_points:
            canvas.create_polygon(ground_points, fill=GROUND_COLOR, outline="")

        # Draw horizon line
        canvas.create_line(rx1, ry1, rx2, ry2, fill=HORIZON_LINE_COLOR, width=2)

        # Draw circular border (clips the horizon)
        canvas.create_oval(
            2, 2, HORIZON_SIZE - 2, HORIZON_SIZE - 2,
            outline="#555555", width=1
        )

        # Draw center reference (crosshair) - fixed, doesn't rotate
        wing_size = 12
        canvas.create_line(cx - wing_size, cy, cx - 4, cy, fill=AIRCRAFT_COLOR, width=1)
        canvas.create_line(cx + 4, cy, cx + wing_size, cy, fill=AIRCRAFT_COLOR, width=1)
        canvas.create_oval(cx - 2, cy - 2, cx + 2, cy + 2, fill=AIRCRAFT_COLOR, outline="")

        # Draw pitch reference lines (every 10 degrees)
        for pitch_ref in [-20, -10, 10, 20]:
            ref_offset = (pitch_ref / 45.0) * radius + pitch_offset
            ref_y = ref_offset
            ref_half = 8 if pitch_ref % 20 == 0 else 5

            # Rotate the reference line
            lx1, ly1 = -ref_half, ref_y
            lx2, ly2 = ref_half, ref_y
            rlx1 = lx1 * cos_r - ly1 * sin_r + cx
            rly1 = lx1 * sin_r + ly1 * cos_r + cy
            rlx2 = lx2 * cos_r - ly2 * sin_r + cx
            rly2 = lx2 * sin_r + ly2 * cos_r + cy

            # Only draw if within circle
            if abs(rly1 - cy) < radius - 5:
                canvas.create_line(rlx1, rly1, rlx2, rly2, fill="#888888", width=1)

    def _get_half_circle_points(
        self,
        cx: float,
        cy: float,
        radius: float,
        lx1: float,
        ly1: float,
        lx2: float,
        ly2: float,
        top: bool,
    ) -> list[float]:
        """Get polygon points for half of circle split by a line.

        Args:
            cx, cy: Circle center
            radius: Circle radius
            lx1, ly1, lx2, ly2: Line endpoints
            top: If True, return top half; otherwise bottom half

        Returns:
            List of polygon coordinates [x1, y1, x2, y2, ...]
        """
        points = []

        # Start with the line endpoints (clipped to circle)
        points.extend([lx1, ly1, lx2, ly2])

        # Add arc points
        # Determine angle range based on line orientation
        angle_start = math.atan2(ly2 - cy, lx2 - cx)
        angle_end = math.atan2(ly1 - cy, lx1 - cx)

        if top:
            # Arc from lx2,ly2 counterclockwise to lx1,ly1 through top
            if angle_start > angle_end:
                angle_end += 2 * math.pi
        else:
            # Arc from lx2,ly2 clockwise to lx1,ly1 through bottom
            if angle_end > angle_start:
                angle_start += 2 * math.pi

        # Generate arc points
        num_steps = 20
        if top:
            angles = [angle_start + (angle_end - angle_start) * i / num_steps for i in range(num_steps + 1)]
        else:
            angles = [angle_start - (angle_start - angle_end) * i / num_steps for i in range(num_steps + 1)]

        for angle in angles:
            ax = cx + radius * math.cos(angle)
            ay = cy + radius * math.sin(angle)
            points.extend([ax, ay])

        return points

    def _draw_heading_tape(self, yaw_deg: float) -> None:
        """Draw a simple compass display showing heading direction.

        Uses a minimal design: large heading number with cardinal direction,
        and a simple compass rose indicator.

        Args:
            yaw_deg: Yaw angle in degrees (-180 to +180)
        """
        if self._heading_canvas is None:
            return

        canvas = self._heading_canvas
        canvas.delete("all")

        # Get actual canvas dimensions
        width = canvas.winfo_width()
        height = canvas.winfo_height()
        if width <= 1:
            width = HORIZON_SIZE
        if height <= 1:
            height = HORIZON_SIZE

        # Normalize yaw to 0-360 range
        heading = yaw_deg % 360
        if heading < 0:
            heading += 360

        center_x = width / 2
        center_y = height / 2

        # Compass circle radius (fit within canvas with padding)
        radius = min(width, height) / 2 - 8

        # Draw compass ring
        canvas.create_oval(
            center_x - radius, center_y - radius,
            center_x + radius, center_y + radius,
            outline="#444444", width=1
        )

        # Draw cardinal tick marks (N, E, S, W) - fixed position on ring
        for deg in (0, 90, 180, 270):
            # Calculate position on ring (0° = North = top)
            angle_rad = math.radians(deg - 90)  # -90 to put 0° at top
            outer_x = center_x + radius * math.cos(angle_rad)
            outer_y = center_y + radius * math.sin(angle_rad)
            inner_x = center_x + (radius - 8) * math.cos(angle_rad)
            inner_y = center_y + (radius - 8) * math.sin(angle_rad)

            # Tick mark
            canvas.create_line(outer_x, outer_y, inner_x, inner_y, fill="#666666", width=1)

        # Draw heading pointer (rotates with heading)
        # Points from center outward in the direction we're facing
        pointer_angle = math.radians(heading - 90)  # -90 to put 0° at top
        pointer_len = radius - 4
        pointer_x = center_x + pointer_len * math.cos(pointer_angle)
        pointer_y = center_y + pointer_len * math.sin(pointer_angle)

        # Pointer line
        canvas.create_line(
            center_x, center_y, pointer_x, pointer_y,
            fill="#a0a0a0", width=2, arrow="last", arrowshape=(6, 8, 3)
        )

        # Center dot
        canvas.create_oval(
            center_x - 2, center_y - 2,
            center_x + 2, center_y + 2,
            fill="#808080", outline=""
        )

        # Heading text below compass
        cardinal_name = self._heading_to_cardinal(heading)
        canvas.create_text(
            center_x, height - 4,
            text=f"{heading:.0f}° {cardinal_name}",
            fill="#909090", font=("Consolas", 8), anchor="s"
        )

    def _heading_to_cardinal(self, heading: float) -> str:
        """Convert heading in degrees to cardinal/intercardinal direction name."""
        # 8-point compass: N, NE, E, SE, S, SW, W, NW
        directions = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
        # Each sector is 45°, centered on the cardinal direction
        index = int((heading + 22.5) / 45) % 8
        return directions[index]

    def _draw_sparkline(self) -> None:
        """Draw the acceleration history sparkline with auto-scaling.

        Shows acceleration magnitude in m/s² from 0 to max in the time window,
        with dynamic Y-axis that scales to the highest acceleration in the
        configured duration (default 10 seconds). Scales up for high g's and
        down for low g's, with a minimum of 1g to avoid noise issues.

        Uses actual timestamps to ensure the time window is accurate regardless
        of update rate variations.
        """
        if self._sparkline_canvas is None:
            return

        canvas = self._sparkline_canvas
        canvas.delete("all")

        if not self._motion_buffer:
            return

        # Get actual canvas dimensions (may have expanded)
        width = canvas.winfo_width()
        height = canvas.winfo_height()
        if width <= 1:
            width = SPARKLINE_WIDTH
        if height <= 1:
            height = HORIZON_SIZE

        padding = 2
        plot_width = width - 2 * padding
        plot_height = height - 2 * padding

        # Filter buffer to only include samples within the time window
        now = time.monotonic()
        cutoff = now - self._sparkline_duration
        windowed_data = [(ts, val) for ts, val in self._motion_buffer if ts >= cutoff]

        if len(windowed_data) < 2:
            return

        # Extract just values for scale calculation
        values = [val for _, val in windowed_data]

        # Dynamic auto-scale: both min and max scale to data range
        # Add small padding (5%) to avoid line touching edges
        min_val = min(values)
        max_val = max(values)
        data_range = max_val - min_val

        # Ensure minimum range to avoid division by zero or overly sensitive scaling
        min_range = 0.5  # At least 0.5 m/s² range
        if data_range < min_range:
            # Center the range around the data midpoint
            midpoint = (min_val + max_val) / 2
            scale_min = midpoint - min_range / 2
            scale_max = midpoint + min_range / 2
        else:
            # Add 5% padding on each end
            padding_amt = data_range * 0.05
            scale_min = min_val - padding_amt
            scale_max = max_val + padding_amt

        scale_range = scale_max - scale_min

        # Build line coordinates using relative time position within window
        # Oldest sample at left (x=0), newest at right (x=width)
        coords = []
        window_start = windowed_data[0][0]
        window_end = windowed_data[-1][0]
        time_span = window_end - window_start

        if time_span <= 0:
            # All samples at same timestamp - just draw a flat line
            val = values[0]
            normalized = (val - scale_min) / scale_range
            y = padding + (1.0 - normalized) * plot_height
            coords = [padding, y, width - padding, y]
        else:
            for ts, val in windowed_data:
                # Position based on relative time within the window
                t_fraction = (ts - window_start) / time_span
                x = padding + t_fraction * plot_width
                normalized = (val - scale_min) / scale_range
                y = padding + (1.0 - normalized) * plot_height
                coords.extend([x, y])

        # Draw filled area under line (subtle gradient effect via dark fill)
        area_coords = [padding, height - padding] + coords + [width - padding, height - padding]
        canvas.create_polygon(area_coords, fill="#252525", outline="")

        # Draw the line
        canvas.create_line(coords, fill="#707070", width=1, smooth=False)

        # Draw 1g reference line if within visible range
        if scale_min <= GRAVITY_MPS2 <= scale_max:
            one_g_normalized = (GRAVITY_MPS2 - scale_min) / scale_range
            one_g_y = padding + (1.0 - one_g_normalized) * plot_height
            canvas.create_line(padding, one_g_y, width - padding, one_g_y,
                              fill="#404040", width=1, dash=(2, 2))
            canvas.create_text(padding + 2, one_g_y - 2, text="1g",
                              fill="#505050", font=("Consolas", 7), anchor="sw")

        # Show current scale on right edge (max at top, min at bottom)
        def fmt_scale(v: float) -> str:
            if v < 1:
                return f"{v:.2f}"
            elif v < 10:
                return f"{v:.1f}"
            return f"{v:.0f}"

        canvas.create_text(width - padding - 2, padding + 2,
                          text=fmt_scale(scale_max), anchor="ne",
                          fill="#505050", font=("Consolas", 7))
        canvas.create_text(width - padding - 2, height - padding - 2,
                          text=fmt_scale(scale_min), anchor="se",
                          fill="#505050", font=("Consolas", 7))

    def _compute_display_yaw(self, raw_yaw: float) -> float:
        """Compute the yaw value to display, optionally with drift-to-zero behavior.

        When drift-to-zero is enabled, the display shows relative yaw from the
        current reference point, and that reference gradually shifts toward the
        current raw yaw over time (effectively zeroing the display).

        Uses linear decay: the displayed yaw decreases at a constant rate of
        (initial_offset / drift_duration) degrees per second, reaching zero
        in exactly drift_duration seconds.

        Args:
            raw_yaw: Raw yaw angle from IMU in degrees (-180 to +180)

        Returns:
            Yaw value to display (raw or drift-adjusted)
        """
        if not self._yaw_drift_to_zero:
            return raw_yaw

        now = time.monotonic()

        # Initialize reference on first call
        if self._yaw_reference is None:
            self._yaw_reference = raw_yaw
            self._last_yaw_update = now
            self._displayed_yaw = 0.0
            return 0.0

        # Calculate time delta
        dt = now - self._last_yaw_update
        self._last_yaw_update = now

        # Calculate current displayed yaw (difference from reference), handling wraparound
        self._displayed_yaw = raw_yaw - self._yaw_reference
        # Normalize to -180 to +180
        while self._displayed_yaw > 180:
            self._displayed_yaw -= 360
        while self._displayed_yaw < -180:
            self._displayed_yaw += 360

        # Linear decay: move reference toward raw_yaw at a fixed rate
        # Rate = 180 degrees / drift_duration (max possible delta over the duration)
        # This ensures ANY offset will reach zero within drift_duration seconds
        max_drift_per_sec = 180.0 / self._yaw_drift_duration  # degrees per second
        max_drift_this_frame = max_drift_per_sec * dt

        # Calculate delta from reference to raw_yaw (handling wraparound)
        ref_delta = raw_yaw - self._yaw_reference
        while ref_delta > 180:
            ref_delta -= 360
        while ref_delta < -180:
            ref_delta += 360

        # Move reference toward raw_yaw by at most max_drift_this_frame
        if abs(ref_delta) <= max_drift_this_frame:
            # Close enough - snap to raw_yaw
            self._yaw_reference = raw_yaw
        else:
            # Move in the direction of ref_delta
            self._yaw_reference += math.copysign(max_drift_this_frame, ref_delta)

        # Normalize reference to -180 to +180
        while self._yaw_reference > 180:
            self._yaw_reference -= 360
        while self._yaw_reference < -180:
            self._yaw_reference += 360

        # Recalculate displayed yaw after drift
        self._displayed_yaw = raw_yaw - self._yaw_reference
        while self._displayed_yaw > 180:
            self._displayed_yaw -= 360
        while self._displayed_yaw < -180:
            self._displayed_yaw += 360

        return self._displayed_yaw

    def update(self, imu_data: Any) -> None:
        """Update the IMU display with new data.

        Args:
            imu_data: IMU sample from Pupil Labs API with accel_data, gyro_data,
                     and quaternion, or None if no data available
        """
        if not self._enabled:
            return

        if imu_data is None:
            return

        try:
            # Extract accelerometer values
            accel = getattr(imu_data, "accel_data", None)
            ax, ay, az = 0.0, 0.0, 0.0
            if accel is not None:
                ax = getattr(accel, "x", 0.0)
                ay = getattr(accel, "y", 0.0)
                az = getattr(accel, "z", 0.0)

            # Extract gyroscope values
            gyro = getattr(imu_data, "gyro_data", None)
            gx, gy, gz = 0.0, 0.0, 0.0
            if gyro is not None:
                gx = getattr(gyro, "x", 0.0)
                gy = getattr(gyro, "y", 0.0)
                gz = getattr(gyro, "z", 0.0)

            # Extract quaternion
            quat = getattr(imu_data, "quaternion", None)
            qw, qx, qy, qz = 1.0, 0.0, 0.0, 0.0
            if quat is not None:
                qw = getattr(quat, "w", 1.0)
                qx = getattr(quat, "x", 0.0)
                qy = getattr(quat, "y", 0.0)
                qz = getattr(quat, "z", 0.0)

            # Convert quaternion to Euler angles
            pitch, roll, raw_yaw = quaternion_to_euler(qw, qx, qy, qz)

            # Compute display yaw (with optional drift-to-zero)
            display_yaw = self._compute_display_yaw(raw_yaw)

            # Calculate acceleration magnitude in m/s² for sparkline
            accel_mag = math.sqrt(ax * ax + ay * ay + az * az)

            # Update motion buffer with (timestamp, acceleration magnitude)
            self._motion_buffer.append((time.monotonic(), accel_mag))

            # Track peak acceleration
            if accel_mag > self._peak_motion:
                self._peak_motion = accel_mag

            # Update horizon
            self._draw_horizon(pitch, roll)

            # Update heading tape (uses drift-adjusted yaw when enabled)
            self._draw_heading_tape(display_yaw)

            # Update sparkline
            self._draw_sparkline()

            # Convert gyro to degrees/s
            gx_deg = math.degrees(gx)
            gy_deg = math.degrees(gy)
            gz_deg = math.degrees(gz)

            # Update text displays
            accel_g = accel_mag / GRAVITY_MPS2
            peak_g = self._peak_motion / GRAVITY_MPS2

            if self._orientation_var:
                # Show display yaw (drift-adjusted when enabled)
                self._orientation_var.set(f"P:{pitch:+6.1f}  R:{roll:+6.1f}  Y:{display_yaw:+6.1f}")
            if self._accel_var:
                self._accel_var.set(f"|A|:{accel_g:5.2f}g  Pk:{peak_g:5.2f}g")
            if self._gyro_var:
                self._gyro_var.set(f"G:{gx_deg:+6.1f} {gy_deg:+6.1f} {gz_deg:+6.1f}")

        except Exception as exc:
            self._logger.exception("IMU update failed: %s", exc)

    def reset(self) -> None:
        """Reset display to placeholder values."""
        if self._orientation_var:
            self._orientation_var.set("P: --.-  R: --.-  Y: --.-")
        if self._accel_var:
            self._accel_var.set("|A|: -.--g  Pk: -.--g")
        if self._gyro_var:
            self._gyro_var.set("G: --.-  --.-  --.-")

        # Clear motion buffer and reset peak
        self._motion_buffer.clear()
        self._peak_motion = 0.0

        # Reset yaw drift state
        self._yaw_reference = None
        self._last_yaw_update = 0.0
        self._displayed_yaw = 0.0

        # Reset horizon to neutral
        self._draw_horizon(0.0, 0.0)

        # Reset heading tape to zero
        self._draw_heading_tape(0.0)

        # Clear sparkline
        if self._sparkline_canvas:
            self._sparkline_canvas.delete("all")


__all__ = ["IMUViewer"]
