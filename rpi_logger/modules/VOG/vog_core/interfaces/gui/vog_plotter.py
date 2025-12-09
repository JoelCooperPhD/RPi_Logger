"""VOG real-time plotter using matplotlib FuncAnimation.

Real-time plotting of stimulus state and shutter timing data for single-device display.
"""

from __future__ import annotations

import time
from typing import Optional, TYPE_CHECKING

import numpy as np

try:
    import matplotlib
    matplotlib.use('TkAgg')
    import matplotlib.animation as animation
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False
    Figure = None
    FigureCanvasTkAgg = None
    animation = None

# Import theme colors for consistent styling
try:
    from rpi_logger.core.ui.theme.colors import Colors
    HAS_THEME = True
except ImportError:
    HAS_THEME = False
    # Fallback colors if theme not available
    class Colors:
        BG_DARK = "#2b2b2b"
        BG_DARKER = "#242424"
        FG_PRIMARY = "#ecf0f1"
        FG_SECONDARY = "#95a5a6"
        BORDER = "#404055"

if TYPE_CHECKING:
    from tkinter import Widget


class VOGPlotter:
    """Real-time plotter for VOG stimulus state and shutter timing data.

    Layout:
        - Top subplot (211): Stimulus state (Clear/Opaque) over time
        - Bottom subplot (212): TSOT (Total Shutter Open Time) and TSCT over time
    """

    def __init__(self, frame: "Widget", title: str = "VOG - Visual Occlusion Glasses"):
        if not HAS_MATPLOTLIB:
            raise ImportError("matplotlib is required for VOGPlotter")

        # Chart setup with dark theme colors
        self._fig = Figure(figsize=(4, 2), dpi=100, facecolor=Colors.BG_DARK, edgecolor=Colors.BORDER)
        self._fig.suptitle(title, fontsize=9, color=Colors.FG_PRIMARY)
        self._canvas = FigureCanvasTkAgg(self._fig, master=frame)
        # Set canvas widget background to match theme
        canvas_widget = self._canvas.get_tk_widget()
        canvas_widget.configure(bg=Colors.BG_DARK, highlightbackground=Colors.BORDER, highlightcolor=Colors.BORDER)
        canvas_widget.grid(row=0, column=0, padx=2, pady=2, sticky='NEWS', rowspan=20)

        self._plt: list = []

        # Time axis: 60 seconds of history at 100ms resolution
        self._time_array = np.arange(-60, 0, 0.1)

        # Update throttling
        self._next_update = time.time()
        self._interval = 0.1  # 100ms between plot updates

        # Total Shutter Times
        self._tsot_now: Optional[float] = None
        self._tsct_now: Optional[float] = None
        self._tsot_array = np.empty([600])
        self._tsot_array[:] = np.nan
        self._tsct_array = np.empty([600])
        self._tsct_array[:] = np.nan
        self._tsot_line = None
        self._tsct_line = None

        self._tst_y_max = 3000

        # Stimulus State
        self._state_now: float = np.nan
        self._state_array = np.empty([600])
        self._state_array[:] = np.nan
        self._state_line = None

        # Animation control
        self._ani: Optional[animation.FuncAnimation] = None

        # Build subplots
        self._add_tsot_plot()
        self._add_state_plot()

        # Initialize plot lines
        self._init_plot_lines()

        # Control flags
        self.run = False
        self.recording = False
        self._session_active = False

    def _add_tsot_plot(self):
        """Add bottom subplot for TSOT/TSCT timing data."""
        self._plt.append(self._fig.add_subplot(212))
        ax = self._plt[0]
        ax.set_facecolor(Colors.BG_DARKER)
        ax.set_ylabel("TSOT-TSCT", fontsize=8, color=Colors.FG_PRIMARY)
        ax.yaxis.set_label_position('right')
        ax.tick_params(axis='both', labelsize=7, colors=Colors.FG_SECONDARY)
        # Style spines
        for spine in ax.spines.values():
            spine.set_color(Colors.BORDER)

    def _add_state_plot(self):
        """Add top subplot for stimulus state (Clear/Opaque)."""
        self._plt.append(self._fig.add_subplot(211))
        ax = self._plt[1]
        ax.set_facecolor(Colors.BG_DARKER)
        ax.xaxis.set_tick_params(labelbottom=False)
        ax.set_ylabel("State", fontsize=8, color=Colors.FG_PRIMARY)
        ax.yaxis.set_label_position('right')
        ax.set_ylim([-0.2, 1.2])
        ax.set_yticks([0, 1])
        ax.set_yticklabels(["Opaque", "Clear"], fontsize=7)
        ax.tick_params(axis='both', labelsize=7, colors=Colors.FG_SECONDARY)
        # Style spines
        for spine in ax.spines.values():
            spine.set_color(Colors.BORDER)

    def _init_plot_lines(self):
        """Initialize plot lines for data display."""
        # TSOT line
        self._tsot_line, = self._plt[0].plot(
            self._time_array, self._tsot_array, marker="o", markersize=3
        )

        # Get color from TSOT line to match TSCT
        c = self._tsot_line.get_color()

        # TSCT line (same color, different marker)
        self._tsct_line, = self._plt[0].plot(
            self._time_array, self._tsct_array, marker="_", color=c, markersize=3
        )

        # Configure TST axes
        self._plt[0].set_xticks([-60, -50, -40, -30, -20, -10, 0])
        self._plt[0].set_xlim([-62, 2])
        self._plt[0].set_yticks(np.arange(0, 3000, 1000))
        self._plt[0].set_ylim([0, 3000])

        # State line
        self._state_line, = self._plt[1].plot(
            self._time_array, self._state_array, marker=""
        )

        # Configure state axes
        self._plt[1].set_xticks([-60, -50, -40, -30, -20, -10, 0])
        self._plt[1].set_xlim([-62, 2])

        # Start animation (interval matches throttle rate for efficiency)
        self._ani = animation.FuncAnimation(
            self._fig,
            self._animate,
            init_func=self._init_animation,
            interval=100,  # Match 100ms throttle rate to reduce CPU wake-ups
            blit=True,
            cache_frame_data=False
        )

    def _init_animation(self):
        """Initialize animation with current data."""
        self._state_line.set_data(self._time_array, self._state_array)
        self._tsot_line.set_data(self._time_array, self._tsot_array)
        self._tsct_line.set_data(self._time_array, self._tsct_array)
        return [self._state_line, self._tsot_line, self._tsct_line]

    def _animate(self, i):
        """Animation frame callback."""
        if self.run and self._ready_to_update():
            # Rescale Y axis if needed
            self._rescale_y(self._tsot_now, self._tsct_now)

            # Shift arrays in-place (no allocation, unlike np.roll)
            self._tsot_array[:-1] = self._tsot_array[1:]
            self._tsct_array[:-1] = self._tsct_array[1:]

            if self._tsot_now is not None:
                self._tsot_array[-1] = self._tsot_now
            else:
                self._tsot_array[-1] = np.nan

            if self._tsct_now is not None:
                self._tsct_array[-1] = self._tsct_now
            else:
                self._tsct_array[-1] = np.nan

            self._tsot_line.set_data(self._time_array, self._tsot_array)
            self._tsct_line.set_data(self._time_array, self._tsct_array)

            self._tsot_now = None
            self._tsct_now = None

            # Shift state array in-place
            self._state_array[:-1] = self._state_array[1:]
            self._state_array[-1] = self._state_now
            self._state_line.set_data(self._time_array, self._state_array)

        return [self._state_line, self._tsot_line, self._tsct_line]

    def _ready_to_update(self) -> bool:
        """Check if enough time has passed for next update."""
        t = time.time()
        if t >= self._next_update:
            if (t - self._next_update) > 0.25:
                self._next_update = t
            else:
                self._next_update += self._interval
            return True
        return False

    def _rescale_y(self, tsot: Optional[float], tsct: Optional[float]):
        """Auto-scale Y axis if values exceed current range."""
        if tsot is None and tsct is None:
            return

        val = max(v for v in [tsot, tsct] if v is not None)
        if val >= self._tst_y_max:
            val = round(val / 1000) * 1000
            tic_width = max(1000, round(val / 3 / 1000) * 1000)
            self._plt[0].set_yticks(np.arange(0, val * 1.2, tic_width))
            self._plt[0].set_ylim(-0.3, val * 1.2)
            self._tst_y_max = val
            self._plt[0].figure.canvas.draw_idle()

    # ------------------------------------------------------------------
    # Public update methods

    def tsot_update(self, val: float):
        """Update TSOT value."""
        self._tsot_now = val

    def tsct_update(self, val: float):
        """Update TSCT value."""
        self._tsct_now = val

    def state_update(self, val: float):
        """Update stimulus state.

        Always accepts updates. The animation function checks self.run before
        displaying data, so updates received before the plotter is fully started
        will be stored and shown once animation begins.
        """
        self._state_now = val

    # ------------------------------------------------------------------
    # Session and recording control

    def start_session(self):
        """Start a new session - clear plot and start animation (blank)."""
        self.clear_all()
        self.run = True
        self._session_active = True
        self.recording = False

    def start_recording(self):
        """Start recording - data will start appearing on plot."""
        if not self._session_active:
            # First recording - start session first
            self.start_session()
        else:
            # Resuming from pause - ensure animation running
            self.run = True

        # Only initialize state to 0 if it's NaN (no data received yet).
        # Don't overwrite if a state update already arrived before this
        # method was called (due to async timing with Tk event loop).
        if np.isnan(self._state_now):
            self._state_now = 0

        self.recording = True

    def stop_recording(self):
        """Pause recording - creates gap in data, animation keeps marching."""
        # Set state to NaN to create visible gap in line
        self._state_now = np.nan
        self.recording = False
        # Note: self.run stays True so animation keeps advancing time

    def stop(self):
        """Stop session completely - freeze animation."""
        self._state_now = np.nan
        self.run = False
        self._session_active = False
        self.recording = False

    def clear_all(self):
        """Clear all data."""
        self._state_now = np.nan
        self._state_array[:] = np.nan
        self._state_line.set_data(self._time_array, self._state_array)

        self._tsot_array[:] = np.nan
        self._tsct_array[:] = np.nan
        self._tsot_line.set_data(self._time_array, self._tsot_array)
        self._tsct_line.set_data(self._time_array, self._tsct_array)

        # Reset Y scale
        self._tst_y_max = 3000
        self._plt[0].set_yticks(np.arange(0, 3000, 1000))
        self._plt[0].set_ylim([0, 3000])
        self._plt[0].figure.canvas.draw_idle()
