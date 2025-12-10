"""Enhanced IMU stream viewer with horizon indicator, motion state, and sparkline."""

from __future__ import annotations

import logging
import math
from collections import deque
from typing import TYPE_CHECKING, Any, Optional

try:
    import tkinter as tk
    from tkinter import ttk
except Exception:
    tk = None  # type: ignore
    ttk = None  # type: ignore

try:
    from rpi_logger.core.ui.theme.colors import Colors

    HAS_THEME = True
except ImportError:
    HAS_THEME = False
    Colors = None  # type: ignore

from .base_viewer import BaseStreamViewer

if TYPE_CHECKING:
    pass

# Constants for visualization
GRAVITY_MPS2 = 9.81  # m/s²
HORIZON_SIZE = 80  # pixels
SPARKLINE_WIDTH = 180
SPARKLINE_HEIGHT = 40

# Colors (aviation-inspired)
SKY_COLOR = "#87CEEB"
GROUND_COLOR = "#8B5A2B"
HORIZON_LINE_COLOR = "#FFFFFF"
AIRCRAFT_COLOR = "#FFD700"

# Motion state colors
STATE_STILL_COLOR = "#22C55E"  # Green
STATE_MOVING_COLOR = "#EAB308"  # Yellow
STATE_RAPID_COLOR = "#EF4444"  # Red

# Thresholds (g deviation from 1g) - tuned for subtle head movements
STILL_THRESHOLD = 0.02  # Very still head
RAPID_THRESHOLD = 0.08  # Significant head movement


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
        math.degrees(pitch),
        math.degrees(roll),
        math.degrees(yaw),
    )


class IMUViewer(BaseStreamViewer):
    """Enhanced IMU viewer with horizon indicator, motion state badge, and sparkline.

    Components:
    - Artificial horizon (pitch/roll visualization)
    - Orientation text with directional arrows
    - Motion state badge (Still/Moving/Rapid)
    - Motion history sparkline (10-second rolling window)
    - Raw numeric values (accelerometer, gyroscope)
    """

    def __init__(
        self,
        parent: "tk.Frame",
        logger: logging.Logger,
        *,
        row: int = 0,
        sparkline_duration_sec: float = 10.0,
        update_rate_hz: float = 10.0,
    ) -> None:
        """Initialize the enhanced IMU viewer.

        Args:
            parent: Parent tkinter frame
            logger: Logger instance
            row: Grid row position
            sparkline_duration_sec: Duration of motion history to display
            update_rate_hz: Expected update rate for buffer sizing
        """
        super().__init__(parent, "imu", logger, row=row)

        # Configuration
        self._sparkline_duration = sparkline_duration_sec
        self._update_rate = update_rate_hz

        # Motion history buffer (sized for sparkline duration)
        buffer_size = int(sparkline_duration_sec * update_rate_hz)
        self._motion_buffer: deque[float] = deque(maxlen=max(buffer_size, 10))

        # UI elements
        self._horizon_canvas: Optional["tk.Canvas"] = None
        self._sparkline_canvas: Optional["tk.Canvas"] = None
        self._state_label: Optional["tk.Label"] = None

        # StringVars for text updates
        self._pitch_var: Optional["tk.StringVar"] = None
        self._roll_var: Optional["tk.StringVar"] = None
        self._yaw_var: Optional["tk.StringVar"] = None
        self._accel_var: Optional["tk.StringVar"] = None
        self._gyro_var: Optional["tk.StringVar"] = None
        self._peak_var: Optional["tk.StringVar"] = None

        # Track peak motion for annotation
        self._peak_motion: float = 0.0

    def build_ui(self) -> "ttk.Frame":
        """Build the enhanced IMU display with horizon, state badge, and sparkline."""
        if ttk is None or tk is None:
            raise RuntimeError("Tkinter not available")

        self._frame = ttk.LabelFrame(self._parent, text="IMU", padding=(8, 4))
        self._frame.columnconfigure(0, weight=0)  # Horizon
        self._frame.columnconfigure(1, weight=0)  # Orientation text
        self._frame.columnconfigure(2, weight=0)  # State badge
        self._frame.columnconfigure(3, weight=1)  # Sparkline (expands)

        label_style = "Inframe.TLabel" if HAS_THEME else None
        value_font = ("Consolas", 9)
        small_font = ("Consolas", 8)

        # === Row 0-1: Main visualization row ===

        # LEFT: Horizon indicator canvas
        self._horizon_canvas = tk.Canvas(
            self._frame,
            width=HORIZON_SIZE,
            height=HORIZON_SIZE,
            bg="#333333",
            highlightthickness=1,
            highlightbackground="#555555",
        )
        self._horizon_canvas.grid(row=0, column=0, rowspan=2, padx=(0, 12), pady=4)
        self._draw_horizon(0.0, 0.0)  # Initial state

        # CENTER-LEFT: Orientation values with arrows
        orient_frame = ttk.Frame(self._frame)
        orient_frame.grid(row=0, column=1, rowspan=2, sticky="nw", padx=(0, 12))

        self._pitch_var = tk.StringVar(value="Pitch: ---° ")
        pitch_label = ttk.Label(orient_frame, textvariable=self._pitch_var, font=value_font)
        if label_style:
            pitch_label.configure(style=label_style)
        pitch_label.grid(row=0, column=0, sticky="w")

        self._roll_var = tk.StringVar(value="Roll:  ---° ")
        roll_label = ttk.Label(orient_frame, textvariable=self._roll_var, font=value_font)
        if label_style:
            roll_label.configure(style=label_style)
        roll_label.grid(row=1, column=0, sticky="w")

        self._yaw_var = tk.StringVar(value="Yaw:   ---° ")
        yaw_label = ttk.Label(orient_frame, textvariable=self._yaw_var, font=value_font)
        if label_style:
            yaw_label.configure(style=label_style)
        yaw_label.grid(row=2, column=0, sticky="w")

        # CENTER: Motion state badge
        state_frame = ttk.Frame(self._frame)
        state_frame.grid(row=0, column=2, rowspan=2, padx=(0, 12), sticky="n", pady=8)

        self._state_label = tk.Label(
            state_frame,
            text="STILL",
            font=("Consolas", 10, "bold"),
            fg="white",
            bg=STATE_STILL_COLOR,
            width=8,
            height=2,
            relief="raised",
            borderwidth=2,
        )
        self._state_label.pack()

        # RIGHT: Sparkline canvas and peak label
        sparkline_frame = ttk.Frame(self._frame)
        sparkline_frame.grid(row=0, column=3, rowspan=2, sticky="nsew", pady=4)

        sparkline_label = ttk.Label(sparkline_frame, text="Motion (10s)", font=small_font)
        if label_style:
            sparkline_label.configure(style=label_style)
        sparkline_label.pack(anchor="w")

        self._sparkline_canvas = tk.Canvas(
            sparkline_frame,
            width=SPARKLINE_WIDTH,
            height=SPARKLINE_HEIGHT,
            bg="#1a1a1a",
            highlightthickness=1,
            highlightbackground="#444444",
        )
        self._sparkline_canvas.pack(fill="x", expand=True)

        self._peak_var = tk.StringVar(value="Peak: ---.-- g")
        peak_label = ttk.Label(sparkline_frame, textvariable=self._peak_var, font=small_font)
        if label_style:
            peak_label.configure(style=label_style)
        peak_label.pack(anchor="e")

        # === Row 2: Raw numeric values ===
        raw_frame = ttk.Frame(self._frame)
        raw_frame.grid(row=2, column=0, columnspan=4, sticky="ew", pady=(8, 0))

        self._accel_var = tk.StringVar(value="Accel: X=---.-- Y=---.-- Z=---.-- m/s²")
        accel_label = ttk.Label(raw_frame, textvariable=self._accel_var, font=small_font)
        if label_style:
            accel_label.configure(style=label_style)
        accel_label.pack(side="left", padx=(0, 20))

        self._gyro_var = tk.StringVar(value="Gyro: X=---.- Y=---.- Z=---.- °/s")
        gyro_label = ttk.Label(raw_frame, textvariable=self._gyro_var, font=small_font)
        if label_style:
            gyro_label.configure(style=label_style)
        gyro_label.pack(side="left")

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

        # Convert roll to radians for rotation (negate for correct visual direction)
        # When head tilts right (positive roll), horizon should tilt left visually
        roll_rad = math.radians(-roll)

        # Pitch shifts the horizon line vertically
        # Looking down (negative pitch) should show more sky (horizon moves down)
        # Looking up (positive pitch) should show more ground (horizon moves up)
        # Negate pitch for correct visual: +pitch -> horizon goes up -> more ground visible
        pitch_offset = (-pitch / 45.0) * radius

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
            outline="#666666", width=2
        )

        # Draw center reference (aircraft symbol) - fixed, doesn't rotate
        # Small wings and center dot
        wing_size = 15
        canvas.create_line(cx - wing_size, cy, cx - 5, cy, fill=AIRCRAFT_COLOR, width=2)
        canvas.create_line(cx + 5, cy, cx + wing_size, cy, fill=AIRCRAFT_COLOR, width=2)
        canvas.create_oval(cx - 3, cy - 3, cx + 3, cy + 3, fill=AIRCRAFT_COLOR, outline="")

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
                canvas.create_line(rlx1, rly1, rlx2, rly2, fill="#FFFFFF", width=1)

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

    def _compute_motion_state(self, accel_magnitude_g: float) -> tuple[str, str]:
        """Classify motion intensity based on acceleration deviation from 1g.

        Args:
            accel_magnitude_g: Acceleration magnitude in g units

        Returns:
            Tuple of (state_name, state_color)
        """
        deviation = abs(accel_magnitude_g - 1.0)

        if deviation < STILL_THRESHOLD:
            return "STILL", STATE_STILL_COLOR
        elif deviation < RAPID_THRESHOLD:
            return "MOVING", STATE_MOVING_COLOR
        else:
            return "RAPID", STATE_RAPID_COLOR

    def _draw_sparkline(self) -> None:
        """Draw the motion history sparkline with auto-scaling.

        Shows deviation from 1g (rest state) rather than absolute magnitude,
        with auto-scaling Y-axis based on recent data range.
        """
        if self._sparkline_canvas is None:
            return

        canvas = self._sparkline_canvas
        canvas.delete("all")

        if not self._motion_buffer:
            return

        # Get canvas dimensions
        width = canvas.winfo_width()
        height = canvas.winfo_height()
        if width <= 1:
            width = SPARKLINE_WIDTH
        if height <= 1:
            height = SPARKLINE_HEIGHT

        padding = 2
        plot_width = width - 2 * padding
        plot_height = height - 2 * padding

        # Convert to deviation from 1g (rest state)
        values = [abs(v - 1.0) for v in self._motion_buffer]
        num_points = len(values)

        if num_points < 2:
            return

        # Auto-scale: find max deviation in buffer, with minimum scale
        max_deviation = max(values) if values else 0.1
        # Ensure minimum scale of 0.05g and add 20% headroom
        scale_max = max(0.05, max_deviation * 1.2)

        # Build line coordinates
        coords = []
        for i, val in enumerate(values):
            x = padding + (i / (num_points - 1)) * plot_width
            # Normalize: 0 deviation = bottom, max = top
            normalized = min(1.0, val / scale_max)
            y = padding + (1.0 - normalized) * plot_height
            coords.extend([x, y])

        # Draw filled area under line
        area_coords = [padding, height - padding] + coords + [width - padding, height - padding]
        canvas.create_polygon(area_coords, fill="#1e3a5f", outline="")

        # Draw the line
        canvas.create_line(coords, fill="#4a90d9", width=1.5, smooth=True)

        # Draw threshold reference lines
        # STILL threshold
        if STILL_THRESHOLD < scale_max:
            still_y = padding + (1.0 - STILL_THRESHOLD / scale_max) * plot_height
            canvas.create_line(padding, still_y, width - padding, still_y,
                             fill=STATE_STILL_COLOR, width=1, dash=(2, 2))

        # RAPID threshold
        if RAPID_THRESHOLD < scale_max:
            rapid_y = padding + (1.0 - RAPID_THRESHOLD / scale_max) * plot_height
            canvas.create_line(padding, rapid_y, width - padding, rapid_y,
                             fill=STATE_RAPID_COLOR, width=1, dash=(2, 2))

        # Show current scale on right edge
        scale_text = f"{scale_max:.3f}g"
        canvas.create_text(width - padding - 2, padding + 2,
                          text=scale_text, anchor="ne",
                          fill="#666666", font=("Consolas", 7))

    def _get_direction_arrow(self, value: float, threshold: float = 5.0) -> str:
        """Get directional arrow character based on value.

        Args:
            value: Angle or rate value
            threshold: Minimum absolute value to show arrow

        Returns:
            Arrow character or space
        """
        if abs(value) < threshold:
            return " "
        elif value > 0:
            return "+"
        else:
            return "-"

    def _get_pitch_arrow(self, pitch: float) -> str:
        """Get pitch direction indicator."""
        if pitch > 5:
            return "▲"  # Looking up
        elif pitch < -5:
            return "▼"  # Looking down
        return " "

    def _get_roll_arrow(self, roll: float) -> str:
        """Get roll direction indicator."""
        if roll > 5:
            return "►"  # Tilted right
        elif roll < -5:
            return "◄"  # Tilted left
        return " "

    def _get_yaw_arrow(self, yaw: float) -> str:
        """Get yaw direction indicator."""
        if yaw > 5:
            return "→"  # Turned right
        elif yaw < -5:
            return "←"  # Turned left
        return " "

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
            pitch, roll, yaw = quaternion_to_euler(qw, qx, qy, qz)

            # Calculate acceleration magnitude in g
            accel_mag = math.sqrt(ax * ax + ay * ay + az * az)
            accel_mag_g = accel_mag / GRAVITY_MPS2

            # Calculate deviation from 1g (rest state)
            accel_deviation = abs(accel_mag_g - 1.0)

            # Update motion buffer (stores raw g for sparkline to compute deviation)
            self._motion_buffer.append(accel_mag_g)

            # Track peak deviation (not absolute g)
            if accel_deviation > self._peak_motion:
                self._peak_motion = accel_deviation

            # Update horizon
            self._draw_horizon(pitch, roll)

            # Update orientation text with arrows
            if self._pitch_var:
                arrow = self._get_pitch_arrow(pitch)
                self._pitch_var.set(f"Pitch: {pitch:+6.1f}° {arrow}")
            if self._roll_var:
                arrow = self._get_roll_arrow(roll)
                self._roll_var.set(f"Roll:  {roll:+6.1f}° {arrow}")
            if self._yaw_var:
                arrow = self._get_yaw_arrow(yaw)
                self._yaw_var.set(f"Yaw:   {yaw:+6.1f}° {arrow}")

            # Update motion state badge (based on deviation, not absolute)
            state_name, state_color = self._compute_motion_state(accel_mag_g)
            if self._state_label:
                self._state_label.configure(text=state_name, bg=state_color)

            # Update sparkline
            self._draw_sparkline()

            # Update peak display (shows deviation from rest, not absolute)
            if self._peak_var:
                self._peak_var.set(f"Peak: {self._peak_motion:.4f} g")

            # Update raw values
            if self._accel_var:
                self._accel_var.set(f"Accel: X={ax:7.2f} Y={ay:7.2f} Z={az:7.2f} m/s²")
            # Convert gyro from rad/s to deg/s for readability
            if self._gyro_var:
                gx_deg = math.degrees(gx)
                gy_deg = math.degrees(gy)
                gz_deg = math.degrees(gz)
                self._gyro_var.set(f"Gyro: X={gx_deg:+6.1f} Y={gy_deg:+6.1f} Z={gz_deg:+6.1f} °/s")

        except Exception as exc:
            self._logger.debug("IMU update failed: %s", exc)

    def reset(self) -> None:
        """Reset display to placeholder values."""
        if self._pitch_var:
            self._pitch_var.set("Pitch: ---°  ")
        if self._roll_var:
            self._roll_var.set("Roll:  ---°  ")
        if self._yaw_var:
            self._yaw_var.set("Yaw:   ---°  ")
        if self._accel_var:
            self._accel_var.set("Accel: X=---.-- Y=---.-- Z=---.-- m/s²")
        if self._gyro_var:
            self._gyro_var.set("Gyro: X=---.- Y=---.- Z=---.- °/s")
        if self._peak_var:
            self._peak_var.set("Peak: ---.-- g")
        if self._state_label:
            self._state_label.configure(text="---", bg="#555555")

        # Clear motion buffer and reset peak
        self._motion_buffer.clear()
        self._peak_motion = 0.0

        # Reset horizon to neutral
        self._draw_horizon(0.0, 0.0)

        # Clear sparkline
        if self._sparkline_canvas:
            self._sparkline_canvas.delete("all")


__all__ = ["IMUViewer"]
