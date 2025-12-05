"""
Battery Widget

A visual battery indicator widget for wDRT devices.
Displays battery percentage as a segmented bar with color coding.
"""

import tkinter as tk
from tkinter import ttk
from typing import Optional
import logging

from rpi_logger.core.ui.theme.colors import Colors

logger = logging.getLogger(__name__)


class BatteryWidget(ttk.Frame):
    """
    A battery indicator widget showing charge level as segments.

    Features:
    - 10-segment bar display
    - Color coding: green (>30%), yellow (20-30%), red (<20%)
    - Percentage label
    - Optional voltage display
    """

    # Color thresholds
    HIGH_THRESHOLD = 30  # Above this: green
    LOW_THRESHOLD = 20   # Below this: red (between: yellow)

    # Colors - using theme colors for dark mode compatibility
    COLOR_HIGH = Colors.SUCCESS         # Green
    COLOR_MEDIUM = Colors.WARNING       # Yellow/Amber
    COLOR_LOW = Colors.ERROR            # Red
    COLOR_EMPTY = Colors.BG_FRAME       # Dark gray (empty segment)
    COLOR_BORDER = Colors.BORDER        # Border color

    def __init__(
        self,
        parent: tk.Widget,
        width: int = 120,
        height: int = 24,
        segments: int = 10,
        show_label: bool = True,
        **kwargs
    ):
        """
        Initialize the battery widget.

        Args:
            parent: Parent widget
            width: Widget width in pixels
            height: Widget height in pixels
            segments: Number of segments (default 10)
            show_label: Whether to show percentage label
            **kwargs: Additional frame options
        """
        super().__init__(parent, **kwargs)

        self.width = width
        self.height = height
        self.segments = segments
        self.show_label = show_label

        self._percent: Optional[int] = None
        self._segment_frames: list = []

        self._create_widgets()

    def _create_widgets(self) -> None:
        """Create the widget components."""
        # Main container
        container = ttk.Frame(self)
        container.pack(fill=tk.X, expand=True)

        # Battery icon frame (with border to look like battery)
        battery_frame = tk.Frame(
            container,
            bg=self.COLOR_BORDER,
            padx=1,
            pady=1
        )
        battery_frame.pack(side=tk.LEFT, padx=(0, 2))

        # Inner frame for segments
        segments_frame = tk.Frame(battery_frame, bg=self.COLOR_EMPTY)
        segments_frame.pack(side=tk.LEFT)

        # Create segments
        segment_width = (self.width - 20) // self.segments
        segment_height = self.height - 4

        for i in range(self.segments):
            segment = tk.Frame(
                segments_frame,
                width=segment_width,
                height=segment_height,
                bg=self.COLOR_EMPTY,
                highlightthickness=0
            )
            segment.pack(side=tk.LEFT, padx=1, pady=1)
            segment.pack_propagate(False)
            self._segment_frames.append(segment)

        # Battery tip (positive terminal)
        tip = tk.Frame(
            battery_frame,
            width=4,
            height=self.height // 2,
            bg=self.COLOR_BORDER
        )
        tip.pack(side=tk.LEFT, pady=(self.height // 4 - 2))
        tip.pack_propagate(False)

        # Percentage label
        if self.show_label:
            self._label_var = tk.StringVar(value="---%")
            self._label = ttk.Label(
                container,
                textvariable=self._label_var,
                width=5,
                anchor=tk.E
            )
            self._label.pack(side=tk.LEFT, padx=(4, 0))

    def set_percent(self, percent: Optional[int]) -> None:
        """
        Set the battery percentage and update display.

        Args:
            percent: Battery percentage (0-100), or None for unknown
        """
        self._percent = percent

        if percent is None:
            # Unknown state
            for segment in self._segment_frames:
                segment.configure(bg=self.COLOR_EMPTY)
            if self.show_label:
                self._label_var.set("---%")
            return

        # Clamp to valid range
        percent = max(0, min(100, percent))

        # Determine color based on level
        if percent > self.HIGH_THRESHOLD:
            color = self.COLOR_HIGH
        elif percent > self.LOW_THRESHOLD:
            color = self.COLOR_MEDIUM
        else:
            color = self.COLOR_LOW

        # Calculate number of filled segments
        filled = int((percent / 100) * self.segments)
        if percent > 0 and filled == 0:
            filled = 1  # Always show at least one segment if not empty

        # Update segments
        for i, segment in enumerate(self._segment_frames):
            if i < filled:
                segment.configure(bg=color)
            else:
                segment.configure(bg=self.COLOR_EMPTY)

        # Update label
        if self.show_label:
            self._label_var.set(f"{percent}%")

    def get_percent(self) -> Optional[int]:
        """Return the current battery percentage."""
        return self._percent

    def flash_low_battery(self) -> None:
        """Flash the widget to indicate low battery warning."""
        if self._percent is not None and self._percent <= self.LOW_THRESHOLD:
            # Flash by toggling visibility
            current_color = self._segment_frames[0].cget('bg')
            flash_color = self.COLOR_EMPTY if current_color == self.COLOR_LOW else self.COLOR_LOW

            for segment in self._segment_frames[:max(1, int(self._percent / 10))]:
                segment.configure(bg=flash_color)

            # Schedule restore
            self.after(500, lambda: self.set_percent(self._percent))


class CompactBatteryWidget(ttk.Frame):
    """
    A more compact battery indicator using just colored boxes.

    Similar to the RS_Logger implementation with 10 small segments.
    """

    def __init__(
        self,
        parent: tk.Widget,
        segment_size: int = 8,
        **kwargs
    ):
        """
        Initialize the compact battery widget.

        Args:
            parent: Parent widget
            segment_size: Size of each segment in pixels
            **kwargs: Additional frame options
        """
        super().__init__(parent, **kwargs)

        self.segment_size = segment_size
        self._segments: list = []
        self._percent: Optional[int] = None

        self._create_widgets()

    def _create_widgets(self) -> None:
        """Create the segment widgets."""
        for i in range(10):
            segment = tk.Frame(
                self,
                width=self.segment_size,
                height=self.segment_size,
                bg=Colors.BG_FRAME,
                highlightbackground=Colors.BORDER,
                highlightthickness=1
            )
            segment.pack(side=tk.LEFT, padx=1)
            segment.pack_propagate(False)
            self._segments.append(segment)

    def set_percent(self, percent: Optional[int]) -> None:
        """
        Set the battery percentage.

        Args:
            percent: Battery percentage (0-100)
        """
        self._percent = percent

        if percent is None:
            for segment in self._segments:
                segment.configure(bg=Colors.BG_FRAME)
            return

        # Number of filled segments (0-10)
        filled = percent // 10

        for i, segment in enumerate(self._segments):
            if i < filled:
                # Color based on level
                if filled <= 2:
                    color = Colors.ERROR
                elif filled <= 4:
                    color = Colors.WARNING
                else:
                    color = Colors.SUCCESS
                segment.configure(bg=color)
            else:
                segment.configure(bg=Colors.BG_FRAME)

    def get_percent(self) -> Optional[int]:
        """Return the current battery percentage."""
        return self._percent
