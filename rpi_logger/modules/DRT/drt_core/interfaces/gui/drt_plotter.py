"""DRT real-time plotter using matplotlib FuncAnimation.

Real-time plotting of stimulus state and reaction time data for single-device display.
Uses dark theme colors for consistent styling with the modern UI.
"""

from __future__ import annotations

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

from rpi_logger.core.logging_utils import get_module_logger

if TYPE_CHECKING:
    from tkinter import Widget


class DRTPlotter:
    """Real-time plotter for DRT stimulus state and reaction time data.

    Layout:
        - Top subplot (211): Stimulus state (On/Off) over time
        - Bottom subplot (212): Reaction times (hits/misses) over time
    """

    BUFFER_SIZE = 600

    def __init__(self, parent_frame: "Widget", title: str = "DRT - Detection Response Task"):
        if not HAS_MATPLOTLIB:
            raise ImportError("matplotlib is required for DRTPlotter")

        self._parent = parent_frame
        self.logger = get_module_logger("DRTPlotter")
        self._time_array = np.arange(-60, 0, 0.1)

        # Chart setup with dark theme colors
        self._fig = Figure(figsize=(4, 2), dpi=100, facecolor=Colors.BG_DARK, edgecolor=Colors.BORDER)
        self._fig.suptitle(title, fontsize=9, color=Colors.FG_PRIMARY)

        self._ax_state = self._fig.add_subplot(211)
        self._ax_rt = self._fig.add_subplot(212)

        self._setup_plots()

        self._canvas = FigureCanvasTkAgg(self._fig, master=parent_frame)
        self._canvas.draw()
        # Set canvas widget background to match theme
        canvas_widget = self._canvas.get_tk_widget()
        canvas_widget.configure(bg=Colors.BG_DARK, highlightbackground=Colors.BORDER, highlightcolor=Colors.BORDER)
        canvas_widget.grid(row=0, column=0, rowspan=20, sticky='nsew', padx=2, pady=2)

        # Single device tracking (multi-instance pattern - one device per plotter)
        self._device_id: Optional[str] = None
        self._device_added: bool = False

        # Reaction time data (single device)
        self._rt_now: Optional[float] = None
        self._rt_array: dict = {'hit': None, 'miss': None}
        self._rt_xy: dict = {'hit': None, 'miss': None}
        self._rt_index: int = 0

        # Stimulus state data (single device)
        self._state_now: float = 0
        self._state_array: Optional[np.ndarray] = None
        self._state_xy = None
        self._state_index: int = 0

        self._plot_lines = []

        self._rt_y_min = 0
        self._rt_y_max = 1

        # Animation state

        self._ani = None
        self.run = False
        self._session_active = False
        self._recording = False

        # Initialize default plot lines for display before any device connects
        self._init_default_lines()

        # Start animation immediately so chart is visible
        self._start_animation()

    def _init_default_lines(self):
        """Initialize default plot lines for display before any device connects."""
        # Create empty stimulus state line
        self._default_state_line, = self._ax_state.plot(
            self._time_array, np.full(len(self._time_array), np.nan),
            linewidth=1.5
        )

        # Create empty RT lines (hit and miss markers)
        self._default_rt_hit, = self._ax_rt.plot(
            self._time_array, np.full(len(self._time_array), np.nan),
            marker='o', linestyle='', markersize=3
        )
        c = self._default_rt_hit.get_color()
        self._default_rt_miss, = self._ax_rt.plot(
            self._time_array, np.full(len(self._time_array), np.nan),
            marker='x', linestyle='', markersize=3, color=c
        )

        # Add to plot lines for animation
        self._plot_lines = [self._default_state_line, self._default_rt_hit, self._default_rt_miss]

    def _setup_plots(self):
        """Configure plot axes with dark theme styling."""
        # Top plot: Stimulus state
        self._ax_state.set_facecolor(Colors.BG_DARKER)
        self._ax_state.xaxis.set_tick_params(labelbottom=False)
        self._ax_state.set_ylabel("Stimulus", fontsize=8, color=Colors.FG_PRIMARY)
        self._ax_state.yaxis.set_label_position('right')
        self._ax_state.set_ylim(-0.2, 1.2)
        self._ax_state.set_yticks([0, 1])
        self._ax_state.set_yticklabels(["Off", "On"], fontsize=7)
        self._ax_state.tick_params(axis='both', labelsize=7, colors=Colors.FG_SECONDARY)
        self._ax_state.set_xticks([-60, -50, -40, -30, -20, -10, 0])
        self._ax_state.set_xlim(-62, 2)
        # Style spines
        for spine in self._ax_state.spines.values():
            spine.set_color(Colors.BORDER)

        # Bottom plot: Reaction time
        self._ax_rt.set_facecolor(Colors.BG_DARKER)
        self._ax_rt.set_ylabel("RT (s)", fontsize=8, color=Colors.FG_PRIMARY)
        self._ax_rt.yaxis.set_label_position('right')
        self._ax_rt.tick_params(axis='both', labelsize=7, colors=Colors.FG_SECONDARY)
        self._ax_rt.set_xticks([-60, -50, -40, -30, -20, -10, 0])
        self._ax_rt.set_xlim(-62, 2)
        self._ax_rt.set_yticks(np.arange(0, 2, 1))
        self._ax_rt.set_ylim(-0.2, 1.2)
        # Style spines
        for spine in self._ax_rt.spines.values():
            spine.set_color(Colors.BORDER)

    def _start_animation(self):
        """Start the animation loop for the chart."""
        if self._ani is not None:
            return  # Already started
        self._ani = animation.FuncAnimation(
            self._fig,
            self._animate,
            init_func=self._init_animation,
            interval=100,  # Match the internal throttle rate (self._interval)
            blit=True,  # Re-enabled for performance - clear_all() calls draw() explicitly
            cache_frame_data=False
        )

    def stop_animation(self):
        """Stop the animation loop to free resources."""
        if self._ani is not None:
            self._ani.event_source.stop()
            self._ani = None

    def _init_animation(self):
        """Initialize animation - return empty list if no devices yet."""
        return self._plot_lines

    def add_device(self, port: str):
        """Add a device to track in the plotter (single device only)."""
        if self._device_added:
            return

        self._device_id = port
        self._device_added = True

        # Initialize reaction time tracking
        self._rt_now = None
        self._rt_index = 0

        self._rt_array = {
            'hit': np.full(self.BUFFER_SIZE, np.nan),
            'miss': np.full(self.BUFFER_SIZE, np.nan)
        }

        self._rt_xy['hit'] = self._ax_rt.plot(
            self._time_array, self._rt_array['hit'],
            marker='o', linestyle='', markersize=3
        )

        c = self._rt_xy['hit'][0].get_color()
        self._rt_xy['miss'] = self._ax_rt.plot(
            self._time_array, self._rt_array['miss'],
            marker='x', linestyle='', markersize=3, color=c
        )

        # Initialize stimulus state tracking
        self._state_now = 0
        self._state_index = 0
        self._state_array = np.full(self.BUFFER_SIZE, np.nan)
        self._state_xy = self._ax_state.plot(
            self._time_array, self._state_array,
            linewidth=1.5
        )

        self._rebuild_plot_lines()

        # Restart animation if it was stopped (e.g., after previous device removal)
        self._start_animation()

    def _rebuild_plot_lines(self):
        """Rebuild the list of plot lines for animation."""
        # Always include default lines
        self._plot_lines = [self._default_state_line, self._default_rt_hit, self._default_rt_miss]
        # Add device-specific lines if device is added
        if self._device_added:
            if self._state_xy is not None:
                self._plot_lines.extend(self._state_xy)
            if self._rt_xy['hit'] is not None:
                self._plot_lines.extend(self._rt_xy['hit'])
            if self._rt_xy['miss'] is not None:
                self._plot_lines.extend(self._rt_xy['miss'])

    def _should_update(self) -> bool:
        """Check if animation should process this frame.

        Since FuncAnimation now runs at the correct interval (100ms),
        we just check if the plotter is running.
        """
        return self.run

    def _animate(self, i):
        """Animation frame callback."""
        if not self._should_update():
            return self._plot_lines

        if not self._device_added:
            return self._plot_lines

        try:
            self._rescale_rt_y(self._rt_now)

            idx = self._rt_index
            rt_val = self._rt_now
            if rt_val is not None:
                if rt_val > 0:
                    self._rt_array['hit'][idx] = rt_val
                    self._rt_array['miss'][idx] = np.nan
                else:
                    self._rt_array['hit'][idx] = np.nan
                    self._rt_array['miss'][idx] = abs(rt_val)
            else:
                self._rt_array['hit'][idx] = np.nan
                self._rt_array['miss'][idx] = np.nan

            self._rt_index = (idx + 1) % self.BUFFER_SIZE
            self._rt_now = None

            rt_view_hit = self._get_circular_view(self._rt_array['hit'], self._rt_index)
            rt_view_miss = self._get_circular_view(self._rt_array['miss'], self._rt_index)
            self._rt_xy['hit'][0].set_ydata(rt_view_hit)
            self._rt_xy['miss'][0].set_ydata(rt_view_miss)

            state_idx = self._state_index
            self._state_array[state_idx] = self._state_now
            self._state_index = (state_idx + 1) % self.BUFFER_SIZE

            state_view = self._get_circular_view(self._state_array, self._state_index)
            self._state_xy[0].set_ydata(state_view)

        except (KeyError, IndexError) as e:
            self.logger.debug("Animation error: %s", e)

        return self._plot_lines

    def _get_circular_view(self, arr, head_idx):
        """Get circular buffer view starting from head index."""
        return np.concatenate((arr[head_idx:], arr[:head_idx]))

    def _rescale_rt_y(self, val=None):
        """Auto-scale Y axis if values exceed current range."""
        if val is not None:
            abs_val = abs(val)
            if abs_val >= self._rt_y_max:
                # Choose sensible tick interval based on value range
                new_max = abs_val * 1.2
                if new_max <= 1.0:
                    tick_interval = 0.25
                elif new_max <= 2.0:
                    tick_interval = 0.5
                else:
                    tick_interval = 1.0
                self._ax_rt.set_yticks(np.arange(0, new_max + tick_interval, tick_interval))
                self._ax_rt.set_ylim(self._rt_y_min - 0.1, new_max)
                self._rt_y_max = abs_val
                self._ax_rt.figure.canvas.draw_idle()

    # ------------------------------------------------------------------
    # Public update methods

    def update_trial(self, port: str, reaction_time: float, is_hit: bool = True):
        """Update trial data with reaction time.

        Args:
            port: Device port/ID
            reaction_time: Reaction time in milliseconds
            is_hit: True for hit, False for miss
        """
        if not self._recording:
            return

        if not self._device_added:
            self.add_device(port)

        rt_seconds = reaction_time / 1000.0

        if is_hit:
            self._rt_now = rt_seconds
        else:
            self._rt_now = -rt_seconds

    def update_stimulus_state(self, port: str, state: int):
        """Update stimulus state for a device.

        Args:
            port: Device port/ID
            state: Stimulus state (0=off, 1=on)
        """
        if not self._recording:
            return

        if not self._device_added:
            self.add_device(port)

        self._state_now = int(state)

    # ------------------------------------------------------------------
    # Session and recording control

    def start_session(self):
        """Start a new session - clear plot and start animation (blank)."""
        self.logger.debug("Starting session: clearing plot and starting animation")
        self.clear_all()
        self.run = True
        self._session_active = True
        self._recording = False

    def start_recording(self):
        """Start recording - data will start appearing on plot."""
        self.logger.debug("Starting recording")
        if not self._session_active:
            self.logger.debug("First recording - clearing plot")
            self.start_session()
        else:
            self.logger.debug("Resuming animation from frozen state")
            self.run = True

        if self._device_added:
            self._state_now = 0

        self._recording = True

    def stop_recording(self):
        """Pause recording - creates gap in data, animation keeps marching."""
        self.logger.debug("Stop recording: creating gap, animation continues")
        if self._device_added:
            self._state_now = np.nan
        self._recording = False

    def stop(self):
        """Stop session completely - freeze animation."""
        self.logger.debug("Stopping session: freezing animation")
        if self._device_added and self._state_array is not None:
            idx = self._state_index
            self._state_array[idx] = np.nan
            self._state_index = (idx + 1) % self.BUFFER_SIZE
            state_view = self._get_circular_view(self._state_array, self._state_index)
            self._state_xy[0].set_ydata(state_view)
        self.run = False
        self._session_active = False
        self._recording = False

    def remove_device(self, port: str = None):
        """Remove the device from the plotter."""
        if not self._device_added:
            return

        if self._rt_xy['hit'] is not None:
            self._rt_xy['hit'][0].remove()
            self._rt_xy['hit'] = None
        if self._rt_xy['miss'] is not None:
            self._rt_xy['miss'][0].remove()
            self._rt_xy['miss'] = None

        if self._state_xy is not None:
            self._state_xy[0].remove()
            self._state_xy = None

        self._rt_array = {'hit': None, 'miss': None}
        self._rt_now = None
        self._rt_index = 0

        self._state_array = None
        self._state_now = 0
        self._state_index = 0

        device_id = self._device_id
        self._device_id = None
        self._device_added = False
        self._rebuild_plot_lines()

        # Stop animation to free CPU resources when no device is connected
        self.stop_animation()

        self.logger.info("Removed device %s from plotter", device_id)

    def clear_all(self):
        """Clear all data from the plot."""
        if self._device_added and self._state_array is not None:
            self._state_now = np.nan
            self._state_array[:] = np.nan
            self._state_index = 0
            self._state_xy[0].set_ydata(self._state_array)

        if self._device_added and self._rt_array['hit'] is not None:
            self._rt_now = None  # Clear pending RT values
            self._rt_array['hit'][:] = np.nan
            self._rt_array['miss'][:] = np.nan
            self._rt_index = 0
            self._rt_xy['hit'][0].set_ydata(self._rt_array['hit'])
            self._rt_xy['miss'][0].set_ydata(self._rt_array['miss'])

        # Reset Y scale
        self._rt_y_max = 1
        self._ax_rt.set_yticks(np.arange(0, 2, 1))
        self._ax_rt.set_ylim(-0.2, 1.2)
        self._fig.canvas.draw_idle()

    @property
    def recording(self) -> bool:
        """Whether recording is active."""
        return self._recording
