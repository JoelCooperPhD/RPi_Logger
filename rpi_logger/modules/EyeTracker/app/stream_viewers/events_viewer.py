"""Eye events stream viewer with mini-visualizations and counter display.

Real-time visualization: timeline, gauges (blink/saccade rate & duration), PERCLOS P80.
"""

from __future__ import annotations

import logging
import math
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Optional

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

# =============================================================================
# Constants
# =============================================================================

# Event type mappings (Pupil Labs API)
EVENT_TYPE_SACCADE = 0
EVENT_TYPE_FIXATION = 1
EVENT_TYPE_SACCADE_ONSET = 2
EVENT_TYPE_FIXATION_ONSET = 3
EVENT_TYPE_BLINK = 4

# Visualization colors (instrument-grade, muted professional palette)
class VizColors:
    """Colors for mini-visualizations."""
    # Canvas backgrounds
    BG = "#1a1a1a"
    BG_DARK = "#141414"
    BORDER = "#333333"

    # Event colors (muted, professional)
    BLINK = "#5a7a8a"      # Muted steel blue
    FIXATION = "#5a7a5a"   # Muted sage green
    SACCADE = "#7a6a5a"    # Muted tan/brown
    ONSET = "#6a5a7a"      # Muted purple

    # State colors (subdued)
    GOOD = "#4a6a4a"       # Dark muted green
    CAUTION = "#6a5a3a"    # Dark muted amber
    WARNING = "#6a4a4a"    # Dark muted red

    # Text
    TEXT = "#a0a0a0"
    TEXT_DIM = "#505050"

    # Gauge
    GAUGE_BG = "#252525"
    GAUGE_ZONE = "#2a3a2a"
    GAUGE_RANGE = "#3a4a5a"    # Muted blue-gray for min/max spread
    GAUGE_INDICATOR = "#8a9aaa"  # Neutral light blue-gray for current value


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
# PERCLOS Buffer Infrastructure
# =============================================================================

@dataclass
class ApertureRecord:
    """A single eyelid aperture sample for PERCLOS calculation."""
    timestamp: float           # Unix timestamp (seconds)
    aperture_left: float       # Left eyelid aperture (0-1, 1=fully open)
    aperture_right: float      # Right eyelid aperture (0-1, 1=fully open)


class PerclosBuffer:
    """Ring buffer for eyelid aperture samples to compute true PERCLOS.

    PERCLOS (Percentage of Eye Closure) is defined as the percentage of time
    that the eyes are more than 80% closed over a measurement period.

    Reference: NHTSA-approved thresholds:
    - < 7.5% = Alert
    - 7.5-15% = Questionable/Drowsy
    - > 15% = Dangerous

    Uses P80 definition: eye is "closed" when eyelid aperture < 20% (80%+ closed).
    """

    # Eye is considered "closed" when aperture is below this threshold
    # P80 definition: <20% open means >80% closed
    CLOSURE_THRESHOLD = 0.20

    def __init__(self, window_sec: float = 30.0, max_samples: int = 3000):
        """Initialize PERCLOS buffer.

        Args:
            window_sec: Time window for PERCLOS calculation (default 30s)
            max_samples: Maximum samples to retain (default 3000 = 100Hz * 30s)
        """
        self._window_sec = window_sec
        self._samples: deque[ApertureRecord] = deque(maxlen=max_samples)
        self._last_prune = time.time()

    def add_gaze_sample(self, gaze_data: Any) -> None:
        """Add a gaze sample containing eyelid aperture data.

        Args:
            gaze_data: Gaze sample from Pupil Labs API with eyelid_aperture_left/right
        """
        try:
            aperture_left = getattr(gaze_data, "eyelid_aperture_left", None)
            aperture_right = getattr(gaze_data, "eyelid_aperture_right", None)

            # Skip if no aperture data available
            if aperture_left is None and aperture_right is None:
                return

            # Use available aperture (prefer average of both eyes)
            left = float(aperture_left) if aperture_left is not None else None
            right = float(aperture_right) if aperture_right is not None else None

            record = ApertureRecord(
                timestamp=getattr(gaze_data, "timestamp_unix_seconds", time.time()),
                aperture_left=left if left is not None else (right or 1.0),
                aperture_right=right if right is not None else (left or 1.0),
            )
            self._samples.append(record)

            # Periodic pruning
            now = time.time()
            if now - self._last_prune > 5.0:
                self._prune_old_samples(now)
                self._last_prune = now
        except Exception:
            pass

    def _prune_old_samples(self, now: float) -> None:
        """Remove samples older than window_sec."""
        cutoff = now - self._window_sec
        while self._samples and self._samples[0].timestamp < cutoff:
            self._samples.popleft()

    def get_perclos(self) -> float:
        """Calculate PERCLOS (percentage of time eyes >80% closed).

        Returns:
            PERCLOS value between 0.0 and 1.0, or -1.0 if insufficient data
        """
        if len(self._samples) < 10:  # Need minimum samples
            return -1.0

        now = time.time()
        cutoff = now - self._window_sec
        recent = [s for s in self._samples if s.timestamp >= cutoff]

        if len(recent) < 10:
            return -1.0

        # Count samples where eye is >80% closed (aperture < 20%)
        # Use binocular average - if either eye is closed, consider closed
        closed_count = 0
        for sample in recent:
            avg_aperture = (sample.aperture_left + sample.aperture_right) / 2.0
            if avg_aperture < self.CLOSURE_THRESHOLD:
                closed_count += 1

        return closed_count / len(recent)

    def has_data(self) -> bool:
        """Check if buffer has sufficient data for PERCLOS calculation."""
        return len(self._samples) >= 10


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
        """Add an event from the Pupil Labs API to the buffer.

        Note: We use time.time() at receipt rather than the event's timestamp
        to ensure time windowing works correctly (same pattern as IMU viewer).

        Pupil Labs FixationEventData has start_time_ns and end_time_ns but no
        duration attribute - we must calculate it ourselves.
        """
        try:
            now = time.time()
            event_type = int(getattr(event_data, "event_type", -1))

            # Calculate duration from start_time_ns and end_time_ns (Pupil Labs API)
            # The API does NOT provide a 'duration' attribute directly
            start_ns = getattr(event_data, "start_time_ns", None)
            end_ns = getattr(event_data, "end_time_ns", None)
            if start_ns is not None and end_ns is not None:
                duration_sec = (end_ns - start_ns) / 1e9
            else:
                duration_sec = 0.0

            record = EventRecord(
                timestamp=now,
                event_type=event_type,
                duration=duration_sec,
                amplitude_deg=float(getattr(event_data, "amplitude_angle_deg", 0.0) or 0.0),
                mean_velocity=float(getattr(event_data, "mean_velocity", 0.0) or 0.0),
                start_x=float(getattr(event_data, "start_gaze_x", 0.0) or 0.0),
                start_y=float(getattr(event_data, "start_gaze_y", 0.0) or 0.0),
                end_x=float(getattr(event_data, "end_gaze_x", 0.0) or 0.0),
                end_y=float(getattr(event_data, "end_gaze_y", 0.0) or 0.0),
            )
            self._events.append(record)

            # Prune old events periodically (every 5 seconds)
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
        """Get fixation vs saccade time ratio as (fix_fraction, sacc_fraction).

        Uses completed fixation/saccade events if available (they have duration).
        Falls back to onset event counts if no completed events are available.
        """
        # Try completed events first (they have duration data)
        fixations = self.get_events_by_type(EVENT_TYPE_FIXATION, seconds)
        saccades = self.get_events_by_type(EVENT_TYPE_SACCADE, seconds)

        fix_time = sum(f.duration for f in fixations)
        sacc_time = sum(s.duration for s in saccades)
        total = fix_time + sacc_time

        if total > 0:
            return fix_time / total, sacc_time / total

        # Fallback: use onset event counts as a proxy
        # This gives a rough ratio even without completed events
        fix_onsets = self.get_events_by_type(EVENT_TYPE_FIXATION_ONSET, seconds)
        sacc_onsets = self.get_events_by_type(EVENT_TYPE_SACCADE_ONSET, seconds)
        onset_total = len(fix_onsets) + len(sacc_onsets)

        if onset_total > 0:
            return len(fix_onsets) / onset_total, len(sacc_onsets) / onset_total

        return 0.5, 0.5


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
            font=("Consolas", 8),
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

class EventTimeline(MiniViz):
    """Scrolling timeline showing recent events as colored ticks."""

    def __init__(self, parent: "tk.Frame") -> None:
        super().__init__(parent, width=120, height=30, title="Timeline", label="Last 30s")
        self._time_window = 30.0  # 30 second rolling window

    def update(self, buffer: EventBuffer) -> None:
        if not self._canvas:
            return

        self._canvas.delete("all")

        # Get actual canvas dimensions
        canvas_w = self._canvas.winfo_width()
        canvas_h = self._canvas.winfo_height()
        if canvas_w <= 1:
            canvas_w = self._width
        if canvas_h <= 1:
            canvas_h = self._height

        w = canvas_w - 4
        h = canvas_h - 4
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
                fill=color, width=1
            )


class RateGauge(MiniViz):
    """Unified gauge for rates/durations with min/max spread visualization."""

    def __init__(self, parent: "tk.Frame", title: str, max_value: float,
                 value_func, format_func, *, track_spread: bool = True) -> None:
        super().__init__(parent, width=80, height=30, title=title, label="--")
        self._max_value = max_value
        self._value_func = value_func  # Function to get value from buffer
        self._format_func = format_func  # Function to format label
        self._track_spread = track_spread
        self._recent_values: deque[float] = deque(maxlen=6) if track_spread else None
        self._last_sample_time = 0.0

    def _get_canvas_dims(self) -> tuple[int, int]:
        """Get canvas dimensions, falling back to defaults if not yet rendered."""
        w = self._canvas.winfo_width() if self._canvas.winfo_width() > 1 else self._width
        h = self._canvas.winfo_height() if self._canvas.winfo_height() > 1 else self._height
        return w - 4, h - 8

    def update(self, buffer: EventBuffer) -> None:
        if not self._canvas:
            return
        self._canvas.delete("all")
        w, h = self._get_canvas_dims()

        # Background
        self._canvas.create_rectangle(2, 4, w + 2, h + 4,
                                       fill=VizColors.GAUGE_BG, outline=VizColors.BORDER)

        value = self._value_func(buffer)
        if value == 0 or (isinstance(value, list) and not value):
            self.set_label("--")
            return

        # Handle both single values and lists (for min/max/mean)
        if isinstance(value, list):
            mean_val = sum(value) / len(value)
            min_val, max_val = min(value), max(value)
        else:
            mean_val = value
            min_val = max_val = None

        # Sample for spread if enabled
        if self._track_spread and self._recent_values is not None:
            now = time.time()
            if now - self._last_sample_time >= 10.0:
                self._recent_values.append(mean_val)
                self._last_sample_time = now
            if len(self._recent_values) >= 2:
                min_val = min(self._recent_values)
                max_val = max(self._recent_values)

        # Draw spread bar
        if min_val is not None and max_val is not None and max_val > min_val:
            min_x = 2 + min(1.0, min_val / self._max_value) * w
            max_x = 2 + min(1.0, max_val / self._max_value) * w
            self._canvas.create_rectangle(min_x, 6, max_x, h + 2,
                                           fill=VizColors.GAUGE_RANGE, outline="")

        # Draw current indicator
        val_x = 2 + min(1.0, mean_val / self._max_value) * w
        self._canvas.create_rectangle(val_x - 2, 4, val_x + 2, h + 4,
                                       fill=VizColors.GAUGE_INDICATOR, outline="")

        self.set_label(self._format_func(mean_val))


class PerclosIndicator(MiniViz):
    """True PERCLOS indicator using continuous eyelid aperture data.

    PERCLOS (Percentage of Eye Closure) is defined as the percentage of time
    that the eyes are more than 80% closed (P80 definition).

    NHTSA-approved thresholds:
    - < 7.5% = Alert
    - 7.5-15% = Questionable/Drowsy
    - > 15% = Dangerous
    """

    def __init__(self, parent: "tk.Frame") -> None:
        super().__init__(parent, width=50, height=30, title="PERCLOS", label="--")
        # NHTSA-approved PERCLOS thresholds
        self._alert_thresh = 0.075   # < 7.5% = alert
        self._drowsy_thresh = 0.15   # 7.5-15% = drowsy, > 15% = dangerous

    def update_perclos(self, perclos_buffer: PerclosBuffer) -> None:
        """Update PERCLOS display using eyelid aperture data.

        Args:
            perclos_buffer: Buffer containing eyelid aperture samples
        """
        if not self._canvas:
            return

        self._canvas.delete("all")

        # Get actual canvas dimensions
        canvas_w = self._canvas.winfo_width()
        canvas_h = self._canvas.winfo_height()
        if canvas_w <= 1:
            canvas_w = self._width
        if canvas_h <= 1:
            canvas_h = self._height

        w = canvas_w - 4
        h = canvas_h - 8

        # Get true PERCLOS from aperture data
        perclos = perclos_buffer.get_perclos()

        # Draw background
        self._canvas.create_rectangle(2, 4, w + 2, h + 4,
                                       fill=VizColors.GAUGE_BG, outline=VizColors.BORDER)

        if perclos < 0:
            # Insufficient data
            self.set_label("--")
            return

        # Determine color based on NHTSA thresholds
        if perclos < self._alert_thresh:
            color = VizColors.GOOD       # Alert
        elif perclos < self._drowsy_thresh:
            color = VizColors.CAUTION    # Drowsy
        else:
            color = VizColors.WARNING    # Dangerous

        # Draw fill based on percentage (cap at 30% for display scaling)
        fill_w = min(perclos / 0.30, 1.0) * w
        if fill_w > 0:
            self._canvas.create_rectangle(2, 4, 2 + fill_w, h + 4,
                                          fill=color, outline="")

        self.set_label(f"{perclos:.1%}")

    def update(self, buffer: EventBuffer) -> None:
        """Legacy update method - does nothing, use update_perclos instead."""
        pass


# =============================================================================
# Main EventsViewer
# =============================================================================

class EventsViewer(BaseStreamViewer):
    """Eye events viewer with mini-visualizations and counter display.

    Shows real-time visualizations for human factors research:
    - Event timeline (temporal patterns)
    - Saccade velocity gauge (fatigue detection)
    - Scan pattern rose (attention distribution)
    - Fixation/saccade ratio (task type)
    - PERCLOS indicator (true P80 drowsiness metric from eyelid aperture)

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

        # PERCLOS buffer for true P80 calculation from eyelid aperture
        self._perclos_buffer = PerclosBuffer(window_sec=30.0)

        # Counters for each event type
        self._counts: dict[str, int] = {et[1]: 0 for et in self.EVENT_TYPES}

        # StringVar for text display (IMU style)
        self._info_var: Optional["tk.StringVar"] = None

        # Mini-visualizations
        self._visualizations: list[MiniViz] = []

        # Reference to PERCLOS indicator for special update handling
        self._perclos_indicator: Optional[PerclosIndicator] = None

        # Track last processed event to avoid duplicate additions
        self._last_event_id: Optional[int] = None

    def build_ui(self) -> "ttk.Frame":
        """Build the eye events display with visualizations and counters."""
        if ttk is None or tk is None:
            raise RuntimeError("Tkinter not available")

        self._frame = ttk.LabelFrame(self._parent, text="Eye Events", padding=(4, 2))
        self._frame.columnconfigure(0, weight=1)

        # Row 0: Visualizations in grid (evenly spaced)
        viz_frame = ttk.Frame(self._frame)
        viz_frame.grid(row=0, column=0, sticky="ew", pady=(0, 4))

        # Create mini-visualizations using unified RateGauge
        self._perclos_indicator = PerclosIndicator(viz_frame)
        self._visualizations = [
            EventTimeline(viz_frame),
            RateGauge(viz_frame, "Blink Rate", 40.0,
                     lambda b: b.get_blinks_per_minute(60.0),
                     lambda v: f"{v:.0f}/min"),
            RateGauge(viz_frame, "Blink Dur", 600.0,
                     lambda b: [e.duration * 1000 for e in b.get_events_by_type(EVENT_TYPE_BLINK, 60.0) if e.duration > 0],
                     lambda v: f"{v:.0f}ms", track_spread=False),
            RateGauge(viz_frame, "Saccades", 300.0,
                     lambda b: len(b.get_events_by_type(EVENT_TYPE_SACCADE_ONSET, 30.0)) * 2.0,
                     lambda v: f"{v:.0f}/min"),
            self._perclos_indicator,
        ]

        # Configure columns for even spacing
        num_viz = len(self._visualizations)
        for col in range(num_viz):
            viz_frame.columnconfigure(col, weight=1, uniform="viz")

        # Build and grid visualizations evenly
        for col, viz in enumerate(self._visualizations):
            frame = viz.build()
            frame.grid(row=0, column=col, sticky="nsew", padx=2, pady=2)

        # Row 1: Single line of text data (IMU style)
        label_style = "Inframe.TLabel" if HAS_THEME else None
        small_font = ("Consolas", 8)

        self._info_var = tk.StringVar(value="Blink:-- │ Fix:-- │ FixOn:-- │ Sacc:-- │ SaccOn:--")
        info_label = ttk.Label(self._frame, textvariable=self._info_var, font=small_font)
        if label_style:
            info_label.configure(style=label_style)
        info_label.grid(row=1, column=0, sticky="w", pady=(4, 0))

        return self._frame

    def update(self, event_data: Any, gaze_data: Any = None) -> None:
        """Update the visualizations and counters with new event and gaze data.

        Args:
            event_data: Eye event from Pupil Labs API, or None if no event available
            gaze_data: Gaze sample with eyelid aperture for PERCLOS, or None
        """
        if not self._enabled:
            return

        # Add gaze data to PERCLOS buffer if available
        if gaze_data is not None:
            try:
                self._perclos_buffer.add_gaze_sample(gaze_data)
            except Exception as exc:
                self._logger.debug("PERCLOS gaze update failed: %s", exc)

        # Add event to buffer FIRST (before updating visualizations)
        # Only add if it's a NEW event (not the same one we already processed)
        if event_data is not None:
            event_id = id(event_data)
            if event_id != self._last_event_id:
                self._last_event_id = event_id
                try:
                    self._buffer.add(event_data)

                    # Determine event type and update counter
                    event_key = self._get_event_type(event_data)

                    if event_key in self._counts:
                        self._counts[event_key] += 1

                    # Update info line (IMU style)
                    self._update_info_line()

                except Exception as exc:
                    self._logger.debug("Event update failed: %s", exc)

        # Update visualizations (they use buffered data)
        for viz in self._visualizations:
            try:
                # PERCLOS indicator uses its own buffer
                if viz is self._perclos_indicator:
                    self._perclos_indicator.update_perclos(self._perclos_buffer)
                else:
                    viz.update(self._buffer)
            except Exception as exc:
                self._logger.debug("Visualization update failed: %s", exc)

    def _update_info_line(self) -> None:
        """Update the single-line info display."""
        if self._info_var:
            self._info_var.set(
                f"Blink:{self._counts.get('blink', 0)} │ "
                f"Fix:{self._counts.get('fixation', 0)} │ "
                f"FixOn:{self._counts.get('fixation_onset', 0)} │ "
                f"Sacc:{self._counts.get('saccade', 0)} │ "
                f"SaccOn:{self._counts.get('saccade_onset', 0)}"
            )

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

        # Reset info line
        if self._info_var:
            self._info_var.set("Blink:-- │ Fix:-- │ FixOn:-- │ Sacc:-- │ SaccOn:--")

        # Reset buffers and tracking
        self._buffer = EventBuffer(max_age_sec=60.0)
        self._perclos_buffer = PerclosBuffer(window_sec=30.0)
        self._last_event_id = None

        # Reset visualizations
        for viz in self._visualizations:
            viz.reset()


__all__ = ["EventsViewer"]
