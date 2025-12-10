"""Eye events stream viewer with mini-visualizations and counter display.

Provides real-time visualization of eye tracking events for human factors research:
- Blink rate sparkline (fatigue/drowsiness indicator)
- Event timeline (temporal patterns)
- Fixation duration distribution (processing depth)
- Attention heat indicator (cognitive state)
- Saccade velocity gauge (fatigue detection)
- Scan pattern rose (attention distribution)
- Fixation/saccade ratio (task type indicator)
- PERCLOS indicator (drowsiness metric)
"""

from __future__ import annotations

import logging
import math
import time
from collections import deque
from dataclasses import dataclass, field
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


# =============================================================================
# Constants
# =============================================================================

# Event type mappings (Pupil Labs API)
EVENT_TYPE_SACCADE = 0
EVENT_TYPE_FIXATION = 1
EVENT_TYPE_SACCADE_ONSET = 2
EVENT_TYPE_FIXATION_ONSET = 3
EVENT_TYPE_BLINK = 4

# Visualization colors
class VizColors:
    """Colors for mini-visualizations."""
    # Canvas backgrounds
    BG = "#1e1e1e"
    BG_DARK = "#141414"
    BORDER = "#404055"

    # Event colors
    BLINK = "#3498db"      # Blue
    FIXATION = "#2ecc71"   # Green
    SACCADE = "#e67e22"    # Orange
    ONSET = "#9b59b6"      # Purple (for onset events)

    # State colors
    GOOD = "#2ecc71"       # Green
    CAUTION = "#f39c12"    # Yellow/Orange
    WARNING = "#e74c3c"    # Red

    # Text
    TEXT = "#ecf0f1"
    TEXT_DIM = "#7f8c8d"

    # Gauge
    GAUGE_BG = "#2a2a2a"
    GAUGE_ZONE = "#3a5a3a"


def _init_viz_colors() -> None:
    """Initialize colors from theme if available."""
    if Colors is not None:
        VizColors.BG = Colors.BG_CANVAS
        VizColors.BORDER = Colors.BORDER
        VizColors.GOOD = Colors.SUCCESS
        VizColors.CAUTION = Colors.WARNING
        VizColors.WARNING = Colors.ERROR
        VizColors.TEXT = Colors.FG_PRIMARY
        VizColors.TEXT_DIM = Colors.FG_SECONDARY


_init_viz_colors()


# =============================================================================
# Event Buffer Infrastructure
# =============================================================================

@dataclass
class EventRecord:
    """A single eye event record for visualization."""
    timestamp: float           # Unix timestamp (seconds)
    event_type: int            # 0-4 (saccade, fixation, saccade_onset, fixation_onset, blink)
    duration: float = 0.0      # Event duration in seconds
    amplitude_deg: float = 0.0 # Amplitude in degrees
    mean_velocity: float = 0.0 # Mean velocity (deg/s)
    start_x: float = 0.0       # Start gaze position X
    start_y: float = 0.0       # Start gaze position Y
    end_x: float = 0.0         # End gaze position X
    end_y: float = 0.0         # End gaze position Y


@dataclass
class EventBuffer:
    """Ring buffer storing recent events for visualization.

    Maintains a time-windowed collection of events and provides
    derived metrics for visualizations.
    """
    max_age_sec: float = 60.0
    _events: deque = field(default_factory=lambda: deque(maxlen=2000))
    _last_prune: float = field(default_factory=time.time)

    def add(self, event_data: Any) -> None:
        """Add an event from the Pupil Labs API to the buffer."""
        try:
            record = EventRecord(
                timestamp=getattr(event_data, "timestamp", time.time()),
                event_type=int(getattr(event_data, "event_type", -1)),
                duration=float(getattr(event_data, "duration", 0.0) or 0.0),
                amplitude_deg=float(getattr(event_data, "amplitude_angle_deg", 0.0) or 0.0),
                mean_velocity=float(getattr(event_data, "mean_velocity", 0.0) or 0.0),
                start_x=float(getattr(event_data, "start_gaze_x", 0.0) or 0.0),
                start_y=float(getattr(event_data, "start_gaze_y", 0.0) or 0.0),
                end_x=float(getattr(event_data, "end_gaze_x", 0.0) or 0.0),
                end_y=float(getattr(event_data, "end_gaze_y", 0.0) or 0.0),
            )
            self._events.append(record)

            # Prune old events periodically (every 5 seconds)
            now = time.time()
            if now - self._last_prune > 5.0:
                self._prune_old_events(now)
                self._last_prune = now
        except Exception:
            pass

    def _prune_old_events(self, now: float) -> None:
        """Remove events older than max_age_sec."""
        cutoff = now - self.max_age_sec
        while self._events and self._events[0].timestamp < cutoff:
            self._events.popleft()

    def get_recent(self, seconds: float) -> list[EventRecord]:
        """Get events from the last N seconds."""
        cutoff = time.time() - seconds
        return [e for e in self._events if e.timestamp >= cutoff]

    def get_events_by_type(self, event_type: int, seconds: float = 60.0) -> list[EventRecord]:
        """Get events of a specific type from the last N seconds."""
        cutoff = time.time() - seconds
        return [e for e in self._events if e.event_type == event_type and e.timestamp >= cutoff]

    def get_blinks_per_minute(self, window_sec: float = 60.0) -> float:
        """Calculate blinks per minute over the given window."""
        blinks = self.get_events_by_type(EVENT_TYPE_BLINK, window_sec)
        if not blinks:
            return 0.0
        # Scale to per-minute rate
        return len(blinks) * (60.0 / window_sec)

    def get_blink_rate_history(self, buckets: int = 60) -> list[int]:
        """Get blink counts per second for the last N seconds (for sparkline)."""
        now = time.time()
        counts = [0] * buckets
        for event in self._events:
            if event.event_type == EVENT_TYPE_BLINK:
                age = now - event.timestamp
                if 0 <= age < buckets:
                    idx = buckets - 1 - int(age)
                    if 0 <= idx < buckets:
                        counts[idx] += 1
        return counts

    def get_fixation_durations(self, seconds: float = 60.0) -> list[float]:
        """Get list of fixation durations from recent events."""
        fixations = self.get_events_by_type(EVENT_TYPE_FIXATION, seconds)
        return [f.duration for f in fixations if f.duration > 0]

    def get_saccade_velocities(self, seconds: float = 30.0) -> list[float]:
        """Get list of saccade mean velocities from recent events."""
        saccades = self.get_events_by_type(EVENT_TYPE_SACCADE, seconds)
        return [s.mean_velocity for s in saccades if s.mean_velocity > 0]

    def get_saccade_directions(self, seconds: float = 60.0) -> list[float]:
        """Get saccade direction angles in radians."""
        saccades = self.get_events_by_type(EVENT_TYPE_SACCADE, seconds)
        directions = []
        for s in saccades:
            dx = s.end_x - s.start_x
            dy = s.end_y - s.start_y
            if dx != 0 or dy != 0:
                directions.append(math.atan2(dy, dx))
        return directions

    def get_total_blink_duration(self, seconds: float = 60.0) -> float:
        """Get total blink duration in seconds."""
        blinks = self.get_events_by_type(EVENT_TYPE_BLINK, seconds)
        return sum(b.duration for b in blinks)

    def get_fixation_saccade_ratio(self, seconds: float = 60.0) -> tuple[float, float]:
        """Get fixation vs saccade time ratio as (fix_fraction, sacc_fraction)."""
        fixations = self.get_events_by_type(EVENT_TYPE_FIXATION, seconds)
        saccades = self.get_events_by_type(EVENT_TYPE_SACCADE, seconds)

        fix_time = sum(f.duration for f in fixations)
        sacc_time = sum(s.duration for s in saccades)
        total = fix_time + sacc_time

        if total <= 0:
            return 0.5, 0.5
        return fix_time / total, sacc_time / total


# =============================================================================
# Base Mini-Visualization
# =============================================================================

class MiniViz:
    """Base class for mini canvas visualizations."""

    def __init__(
        self,
        parent: "tk.Frame",
        width: int,
        height: int,
        title: str = "",
        label: str = "",
    ) -> None:
        self._parent = parent
        self._width = width
        self._height = height
        self._title = title  # Frame title (static)
        self._label = label  # Dynamic value label
        self._canvas: Optional["tk.Canvas"] = None
        self._frame: Optional["ttk.LabelFrame"] = None
        self._label_widget: Optional["ttk.Label"] = None

    def build(self) -> "ttk.LabelFrame":
        """Build the visualization widget. Returns the container LabelFrame."""
        if tk is None or ttk is None:
            raise RuntimeError("Tkinter not available")

        # Use LabelFrame for each chart
        self._frame = ttk.LabelFrame(self._parent, text=self._title, padding=(2, 1))

        # Canvas for visualization
        self._canvas = tk.Canvas(
            self._frame,
            width=self._width,
            height=self._height,
            bg=VizColors.BG,
            highlightthickness=1,
            highlightbackground=VizColors.BORDER,
        )
        self._canvas.pack(side=tk.TOP, fill=tk.X, expand=True)

        # Value label below canvas
        label_style = "Inframe.TLabel" if HAS_THEME else None
        self._label_widget = ttk.Label(
            self._frame,
            text=self._label,
            font=("Consolas", 9),
            anchor="center",
        )
        if label_style:
            self._label_widget.configure(style=label_style)
        self._label_widget.pack(side=tk.TOP, fill=tk.X)

        return self._frame

    def update(self, buffer: EventBuffer) -> None:
        """Update the visualization from buffer data. Override in subclass."""
        pass

    def reset(self) -> None:
        """Reset the visualization."""
        if self._canvas:
            self._canvas.delete("all")

    def set_label(self, text: str) -> None:
        """Update the label text."""
        if self._label_widget:
            self._label_widget.configure(text=text)


# =============================================================================
# Visualization Implementations
# =============================================================================

class BlinkRateSparkline(MiniViz):
    """Tiny sparkline showing blinks per minute over 60 seconds."""

    def __init__(self, parent: "tk.Frame") -> None:
        super().__init__(parent, width=100, height=30, title="Blink Rate", label="--/min")
        self._points: list[int] = []

    def update(self, buffer: EventBuffer) -> None:
        if not self._canvas:
            return

        # Get blink history (counts per second for last 60 seconds)
        history = buffer.get_blink_rate_history(60)
        bpm = buffer.get_blinks_per_minute(60.0)

        # Update label
        self.set_label(f"{bpm:.0f}/min")

        # Draw sparkline
        self._canvas.delete("all")

        w = self._width - 4
        h = self._height - 4

        # Calculate rolling bpm (5-second windows) for smoother line
        window = 5
        smoothed = []
        for i in range(len(history) - window + 1):
            chunk = history[i:i + window]
            smoothed.append(sum(chunk) * (60.0 / window))

        if not smoothed:
            return

        max_val = max(max(smoothed), 20)  # Minimum scale of 20 bpm

        # Build polyline points
        points = []
        for i, val in enumerate(smoothed):
            x = 2 + (i / max(1, len(smoothed) - 1)) * w
            y = 2 + h - (val / max_val) * h
            points.extend([x, y])

        if len(points) >= 4:
            # Color based on current bpm
            if bpm < 10:
                color = VizColors.CAUTION  # Low blink rate = high cognitive load
            elif bpm > 25:
                color = VizColors.WARNING  # High blink rate = fatigue
            else:
                color = VizColors.GOOD

            self._canvas.create_line(points, fill=color, width=1.5, smooth=True)


class EventTimeline(MiniViz):
    """Scrolling timeline showing recent events as colored ticks."""

    def __init__(self, parent: "tk.Frame") -> None:
        super().__init__(parent, width=120, height=30, title="Timeline", label="Last 30s")
        self._time_window = 30.0  # seconds

    def update(self, buffer: EventBuffer) -> None:
        if not self._canvas:
            return

        self._canvas.delete("all")

        w = self._width - 4
        h = self._height - 4
        now = time.time()

        events = buffer.get_recent(self._time_window)

        # Draw timeline background
        self._canvas.create_line(2, h // 2 + 2, w + 2, h // 2 + 2,
                                  fill=VizColors.TEXT_DIM, width=1)

        # Draw event ticks
        for event in events:
            age = now - event.timestamp
            if age < 0 or age > self._time_window:
                continue

            x = 2 + w - (age / self._time_window) * w

            # Color by event type
            if event.event_type == EVENT_TYPE_BLINK:
                color = VizColors.BLINK
                tick_h = h * 0.8
            elif event.event_type == EVENT_TYPE_FIXATION:
                color = VizColors.FIXATION
                tick_h = h * 0.6
            elif event.event_type == EVENT_TYPE_SACCADE:
                color = VizColors.SACCADE
                tick_h = h * 0.5
            else:
                color = VizColors.ONSET
                tick_h = h * 0.3

            y_center = h // 2 + 2
            self._canvas.create_line(
                x, y_center - tick_h // 2,
                x, y_center + tick_h // 2,
                fill=color, width=2
            )


class FixationDistBar(MiniViz):
    """3-segment bar showing short/medium/long fixation distribution."""

    def __init__(self, parent: "tk.Frame") -> None:
        super().__init__(parent, width=80, height=30, title="Fixation Dur", label="--")
        # Thresholds in seconds
        self._short_thresh = 0.2    # < 200ms
        self._long_thresh = 0.5     # > 500ms

    def update(self, buffer: EventBuffer) -> None:
        if not self._canvas:
            return

        durations = buffer.get_fixation_durations(60.0)

        if not durations:
            self._canvas.delete("all")
            self._draw_empty_bar()
            self.set_label("--")
            return

        # Categorize fixations
        short = sum(1 for d in durations if d < self._short_thresh)
        medium = sum(1 for d in durations if self._short_thresh <= d < self._long_thresh)
        long = sum(1 for d in durations if d >= self._long_thresh)
        total = len(durations)

        # Calculate proportions
        short_pct = short / total if total > 0 else 0.33
        medium_pct = medium / total if total > 0 else 0.34
        long_pct = long / total if total > 0 else 0.33

        # Draw bar
        self._canvas.delete("all")
        w = self._width - 4
        h = self._height - 8
        y = 4

        x = 2
        # Short (blue - visual search)
        short_w = short_pct * w
        if short_w > 0:
            self._canvas.create_rectangle(x, y, x + short_w, y + h,
                                          fill="#3498db", outline="")
            x += short_w

        # Medium (green - normal)
        medium_w = medium_pct * w
        if medium_w > 0:
            self._canvas.create_rectangle(x, y, x + medium_w, y + h,
                                          fill=VizColors.GOOD, outline="")
            x += medium_w

        # Long (orange - deep processing/fatigue)
        long_w = long_pct * w
        if long_w > 0:
            self._canvas.create_rectangle(x, y, x + long_w, y + h,
                                          fill=VizColors.CAUTION, outline="")

        # Update label with mean duration
        mean_dur = sum(durations) / len(durations) * 1000  # ms
        self.set_label(f"{mean_dur:.0f}ms avg")

    def _draw_empty_bar(self) -> None:
        w = self._width - 4
        h = self._height - 8
        self._canvas.create_rectangle(2, 4, w + 2, h + 4,
                                       fill=VizColors.GAUGE_BG, outline=VizColors.BORDER)


class AttentionHeatBar(MiniViz):
    """Gradient bar showing combined attention/cognitive state indicator."""

    def __init__(self, parent: "tk.Frame") -> None:
        super().__init__(parent, width=60, height=30, title="Cog Load", label="Normal")
        self._baseline_bpm = 15.0  # Typical blink rate

    def update(self, buffer: EventBuffer) -> None:
        if not self._canvas:
            return

        # Calculate attention score (0 = good, 1 = overload/fatigue)
        score = self._calculate_attention_score(buffer)

        self._canvas.delete("all")
        w = self._width - 4
        h = self._height - 8

        # Draw gradient background
        self._draw_gradient(2, 4, w, h)

        # Draw indicator marker
        marker_x = 2 + score * w
        self._canvas.create_polygon(
            marker_x - 4, 2,
            marker_x + 4, 2,
            marker_x, 8,
            fill=VizColors.TEXT, outline=""
        )
        self._canvas.create_line(marker_x, 8, marker_x, h + 4,
                                  fill=VizColors.TEXT, width=2)

        # Update label
        if score < 0.33:
            self.set_label("Normal")
        elif score < 0.66:
            self.set_label("Elevated")
        else:
            self.set_label("High")

    def _calculate_attention_score(self, buffer: EventBuffer) -> float:
        """Calculate combined attention/load score (0-1)."""
        scores = []

        # Blink rate deviation
        bpm = buffer.get_blinks_per_minute(60.0)
        if bpm > 0:
            deviation = abs(bpm - self._baseline_bpm) / self._baseline_bpm
            scores.append(min(1.0, deviation))

        # Fixation duration (longer = higher load or fatigue)
        durations = buffer.get_fixation_durations(30.0)
        if durations:
            mean_dur = sum(durations) / len(durations)
            # Score increases for very short (<150ms) or very long (>600ms)
            if mean_dur < 0.15:
                scores.append(0.6)  # Very short = visual search stress
            elif mean_dur > 0.6:
                scores.append(0.8)  # Very long = fatigue
            else:
                scores.append(0.2)  # Normal range

        # Saccade velocity (lower = fatigue)
        velocities = buffer.get_saccade_velocities(30.0)
        if velocities:
            mean_vel = sum(velocities) / len(velocities)
            if mean_vel < 200:
                scores.append(0.8)  # Slow saccades = fatigue
            elif mean_vel < 350:
                scores.append(0.4)
            else:
                scores.append(0.1)  # Normal/high velocity

        if not scores:
            return 0.5

        return min(1.0, sum(scores) / len(scores))

    def _draw_gradient(self, x: int, y: int, w: int, h: int) -> None:
        """Draw green-yellow-red gradient."""
        # Simple 3-zone gradient
        third = w // 3
        self._canvas.create_rectangle(x, y, x + third, y + h,
                                       fill=VizColors.GOOD, outline="")
        self._canvas.create_rectangle(x + third, y, x + 2 * third, y + h,
                                       fill=VizColors.CAUTION, outline="")
        self._canvas.create_rectangle(x + 2 * third, y, x + w, y + h,
                                       fill=VizColors.WARNING, outline="")


class SaccadeVelocityGauge(MiniViz):
    """Gauge showing mean saccade velocity vs normal range."""

    def __init__(self, parent: "tk.Frame") -> None:
        super().__init__(parent, width=80, height=30, title="Saccade Vel", label="--")
        # Normal saccade velocity range (deg/s)
        self._normal_min = 300.0
        self._normal_max = 500.0
        self._max_vel = 800.0

    def update(self, buffer: EventBuffer) -> None:
        if not self._canvas:
            return

        velocities = buffer.get_saccade_velocities(30.0)

        self._canvas.delete("all")
        w = self._width - 4
        h = self._height - 8

        # Draw background with normal zone
        self._canvas.create_rectangle(2, 4, w + 2, h + 4,
                                       fill=VizColors.GAUGE_BG, outline=VizColors.BORDER)

        # Draw normal zone
        zone_start = 2 + (self._normal_min / self._max_vel) * w
        zone_end = 2 + (self._normal_max / self._max_vel) * w
        self._canvas.create_rectangle(zone_start, 4, zone_end, h + 4,
                                       fill=VizColors.GAUGE_ZONE, outline="")

        if not velocities:
            self.set_label("--")
            return

        mean_vel = sum(velocities) / len(velocities)

        # Draw velocity indicator
        vel_x = 2 + min(1.0, mean_vel / self._max_vel) * w

        # Color based on velocity
        if mean_vel < self._normal_min:
            color = VizColors.WARNING  # Slow = fatigue
        elif mean_vel > self._normal_max:
            color = VizColors.CAUTION  # Fast = alertness/stress
        else:
            color = VizColors.GOOD

        self._canvas.create_rectangle(vel_x - 2, 4, vel_x + 2, h + 4,
                                       fill=color, outline="")

        self.set_label(f"{mean_vel:.0f}°/s")


class ScanPatternRose(MiniViz):
    """8-directional rose showing saccade direction distribution."""

    def __init__(self, parent: "tk.Frame") -> None:
        super().__init__(parent, width=40, height=40, title="Scan", label="--")
        self._num_sectors = 8

    def update(self, buffer: EventBuffer) -> None:
        if not self._canvas:
            return

        directions = buffer.get_saccade_directions(60.0)

        self._canvas.delete("all")

        cx = self._width // 2
        cy = self._height // 2
        max_r = min(cx, cy) - 4

        # Draw background circle
        self._canvas.create_oval(cx - max_r, cy - max_r, cx + max_r, cy + max_r,
                                  fill=VizColors.GAUGE_BG, outline=VizColors.BORDER)

        if not directions:
            self.set_label("--")
            return

        # Count directions in each sector
        sector_counts = [0] * self._num_sectors
        sector_angle = 2 * math.pi / self._num_sectors

        for angle in directions:
            # Normalize angle to [0, 2*pi)
            angle = angle % (2 * math.pi)
            sector = int(angle / sector_angle) % self._num_sectors
            sector_counts[sector] += 1

        max_count = max(sector_counts) if sector_counts else 1

        # Draw sectors
        for i, count in enumerate(sector_counts):
            if count == 0:
                continue

            angle_start = i * sector_angle - math.pi / 2  # Start from top
            r = (count / max_count) * max_r * 0.9

            # Draw pie slice
            x1 = cx + r * math.cos(angle_start)
            y1 = cy + r * math.sin(angle_start)
            x2 = cx + r * math.cos(angle_start + sector_angle)
            y2 = cy + r * math.sin(angle_start + sector_angle)

            intensity = int(100 + (count / max_count) * 155)
            color = f"#{intensity:02x}{intensity:02x}ff"  # Blue-ish

            self._canvas.create_polygon(
                cx, cy, x1, y1, x2, y2,
                fill=color, outline=""
            )

        # Draw center dot
        self._canvas.create_oval(cx - 2, cy - 2, cx + 2, cy + 2,
                                  fill=VizColors.TEXT, outline="")

        # Calculate entropy (distribution measure)
        total = sum(sector_counts)
        if total > 0:
            probs = [c / total for c in sector_counts if c > 0]
            entropy = -sum(p * math.log2(p) for p in probs) if probs else 0
            max_entropy = math.log2(self._num_sectors)
            uniformity = entropy / max_entropy if max_entropy > 0 else 0
            self.set_label(f"{uniformity:.0%} unif")
        else:
            self.set_label("--")


class FixSaccRatioBar(MiniViz):
    """Split bar showing fixation vs saccade time ratio."""

    def __init__(self, parent: "tk.Frame") -> None:
        super().__init__(parent, width=60, height=30, title="Fix/Sacc", label="--")

    def update(self, buffer: EventBuffer) -> None:
        if not self._canvas:
            return

        fix_ratio, sacc_ratio = buffer.get_fixation_saccade_ratio(60.0)

        self._canvas.delete("all")
        w = self._width - 4
        h = self._height - 8

        # Draw fixation portion (green)
        fix_w = fix_ratio * w
        if fix_w > 0:
            self._canvas.create_rectangle(2, 4, 2 + fix_w, h + 4,
                                          fill=VizColors.FIXATION, outline="")

        # Draw saccade portion (orange)
        if sacc_ratio > 0:
            self._canvas.create_rectangle(2 + fix_w, 4, w + 2, h + 4,
                                          fill=VizColors.SACCADE, outline="")

        # Update label
        self.set_label(f"{fix_ratio:.0%} fix")


class PerclosIndicator(MiniViz):
    """PERCLOS-style indicator showing percentage of eyes closed."""

    def __init__(self, parent: "tk.Frame") -> None:
        super().__init__(parent, width=50, height=30, title="PERCLOS", label="--")
        # PERCLOS thresholds
        self._normal_thresh = 0.08   # < 8% = alert
        self._caution_thresh = 0.15  # 8-15% = drowsy
        # > 15% = dangerous

    def update(self, buffer: EventBuffer) -> None:
        if not self._canvas:
            return

        # Calculate PERCLOS (blink duration / total time)
        window = 60.0
        blink_duration = buffer.get_total_blink_duration(window)
        perclos = blink_duration / window

        self._canvas.delete("all")
        w = self._width - 4
        h = self._height - 8

        # Determine color
        if perclos < self._normal_thresh:
            color = VizColors.GOOD
        elif perclos < self._caution_thresh:
            color = VizColors.CAUTION
        else:
            color = VizColors.WARNING

        # Draw background
        self._canvas.create_rectangle(2, 4, w + 2, h + 4,
                                       fill=VizColors.GAUGE_BG, outline=VizColors.BORDER)

        # Draw fill based on percentage (cap at 30% for display)
        fill_w = min(perclos / 0.30, 1.0) * w
        if fill_w > 0:
            self._canvas.create_rectangle(2, 4, 2 + fill_w, h + 4,
                                          fill=color, outline="")

        self.set_label(f"{perclos:.1%}")


# =============================================================================
# Main EventsViewer
# =============================================================================

class EventsViewer(BaseStreamViewer):
    """Eye events viewer with mini-visualizations and counter display.

    Shows real-time visualizations for human factors research:
    - Blink rate sparkline (fatigue/drowsiness)
    - Event timeline (temporal patterns)
    - Fixation duration distribution (processing depth)
    - Attention heat indicator (cognitive state)
    - Saccade velocity gauge (fatigue detection)
    - Scan pattern rose (attention distribution)
    - Fixation/saccade ratio (task type)
    - PERCLOS indicator (drowsiness)

    Plus compact counters showing running totals.
    """

    # Event type definitions matching Pupil Labs API (full labels for display)
    EVENT_TYPES = [
        ("Blinks", "blink"),
        ("Fixations", "fixation"),
        ("Fix Onsets", "fixation_onset"),
        ("Saccades", "saccade"),
        ("Sacc Onsets", "saccade_onset"),
    ]

    def __init__(
        self,
        parent: "tk.Frame",
        logger: logging.Logger,
        *,
        row: int = 0,
    ) -> None:
        """Initialize the events viewer.

        Args:
            parent: Parent tkinter frame
            logger: Logger instance
            row: Grid row position
        """
        super().__init__(parent, "events", logger, row=row)

        # Event buffer for visualizations
        self._buffer = EventBuffer(max_age_sec=60.0)

        # Counters for each event type
        self._counts: dict[str, int] = {et[1]: 0 for et in self.EVENT_TYPES}
        self._vars: dict[str, Optional["tk.StringVar"]] = {}

        # Mini-visualizations
        self._visualizations: list[MiniViz] = []

    def build_ui(self) -> "ttk.Frame":
        """Build the eye events display with visualizations and counters."""
        if ttk is None or tk is None:
            raise RuntimeError("Tkinter not available")

        self._frame = ttk.LabelFrame(self._parent, text="Eye Events", padding=(4, 2))
        self._frame.columnconfigure(0, weight=1)

        # Row 0: Visualizations in grid (evenly spaced)
        viz_frame = ttk.Frame(self._frame)
        viz_frame.grid(row=0, column=0, sticky="ew", pady=(0, 4))

        # Create all mini-visualizations
        self._visualizations = [
            BlinkRateSparkline(viz_frame),
            EventTimeline(viz_frame),
            FixationDistBar(viz_frame),
            AttentionHeatBar(viz_frame),
            SaccadeVelocityGauge(viz_frame),
            ScanPatternRose(viz_frame),
            FixSaccRatioBar(viz_frame),
            PerclosIndicator(viz_frame),
        ]

        # Configure columns for even spacing
        num_viz = len(self._visualizations)
        for col in range(num_viz):
            viz_frame.columnconfigure(col, weight=1, uniform="viz")

        # Build and grid visualizations evenly
        for col, viz in enumerate(self._visualizations):
            frame = viz.build()
            frame.grid(row=0, column=col, sticky="nsew", padx=2, pady=2)

        # Row 1: Original counter display (full labels with values)
        counter_frame = ttk.Frame(self._frame)
        counter_frame.grid(row=1, column=0, sticky="ew", pady=(4, 0))

        label_style = "Inframe.TLabel" if HAS_THEME else None
        value_font = ("Consolas", 10, "bold")

        # Create counters with full labels (matching original layout)
        self._vars: dict[str, Optional["tk.StringVar"]] = {}
        for col, (label_text, event_key) in enumerate(self.EVENT_TYPES):
            # Counter frame
            item_frame = ttk.Frame(counter_frame)
            is_last = col == len(self.EVENT_TYPES) - 1
            item_frame.grid(row=0, column=col, padx=(0, 12) if not is_last else 0)

            # Label
            label = ttk.Label(item_frame, text=label_text)
            if label_style:
                label.configure(style=label_style)
            label.grid(row=0, column=0)

            # Value
            var = tk.StringVar(value="0")
            self._vars[event_key] = var
            value_label = ttk.Label(
                item_frame,
                textvariable=var,
                font=value_font,
            )
            if label_style:
                value_label.configure(style=label_style)
            value_label.grid(row=1, column=0)

        return self._frame

    def update(self, event_data: Any) -> None:
        """Update the visualizations and counters with new event data.

        Args:
            event_data: Eye event from Pupil Labs API, or None if no event available
        """
        if not self._enabled:
            return

        # Always update visualizations (they use buffered data)
        for viz in self._visualizations:
            try:
                viz.update(self._buffer)
            except Exception as exc:
                self._logger.debug("Visualization update failed: %s", exc)

        if event_data is None:
            return

        try:
            # Add event to buffer
            self._buffer.add(event_data)

            # Determine event type and update counter
            event_key = self._get_event_type(event_data)

            if event_key in self._counts:
                self._counts[event_key] += 1
                var = self._vars.get(event_key)
                if var:
                    var.set(str(self._counts[event_key]))

        except Exception as exc:
            self._logger.debug("Event update failed: %s", exc)

    def _get_event_type(self, event_data: Any) -> str:
        """Determine the type of eye event.

        Pupil Labs event types are encoded as integers:
        - event_type=0: Saccade (completed)
        - event_type=1: Fixation (completed)
        - event_type=2: Saccade onset
        - event_type=3: Fixation onset
        - event_type=4: Blink

        Args:
            event_data: Eye event object

        Returns:
            Event type key: 'blink', 'fixation', 'fixation_onset',
                           'saccade', 'saccade_onset', or 'unknown'
        """
        # Check numeric event_type attribute (Pupil Labs API)
        event_type_val = getattr(event_data, "event_type", None)
        if event_type_val is not None:
            try:
                event_type_int = int(event_type_val)
                if event_type_int == EVENT_TYPE_SACCADE:
                    return "saccade"
                elif event_type_int == EVENT_TYPE_FIXATION:
                    return "fixation"
                elif event_type_int == EVENT_TYPE_SACCADE_ONSET:
                    return "saccade_onset"
                elif event_type_int == EVENT_TYPE_FIXATION_ONSET:
                    return "fixation_onset"
                elif event_type_int == EVENT_TYPE_BLINK:
                    return "blink"
            except (ValueError, TypeError):
                pass

        # Fallback: check class name
        class_name = type(event_data).__name__.lower()
        if "blink" in class_name:
            return "blink"
        if "fixationonset" in class_name:
            return "fixation_onset"
        if "fixation" in class_name:
            return "fixation"

        return "unknown"

    def reset(self) -> None:
        """Reset all counters and visualizations."""
        for event_key in self._counts:
            self._counts[event_key] = 0
            var = self._vars.get(event_key)
            if var:
                var.set("0")

        # Reset buffer
        self._buffer = EventBuffer(max_age_sec=60.0)

        # Reset visualizations
        for viz in self._visualizations:
            viz.reset()


__all__ = ["EventsViewer"]
