"""DRT real-time plotter using matplotlib FuncAnimation.

Real-time plotting of stimulus state and reaction time data for single-device display.
Uses dark theme colors for consistent styling with the modern UI.
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

        # Per-device reaction time data
        self._rt_now = {}
        self._rt_array = {}
        self._rt_xy = {}
        self._rt_index = {}

        # Per-device stimulus state data
        self._state_now = {}
        self._state_array = {}
        self._state_xy = {}
        self._state_index = {}

        self._unit_ids = set()
        self._plot_lines = []

        self._rt_y_min = 0
        self._rt_y_max = 1

        # Update throttling
        self._next_update = time.time()
        self._interval = 0.1  # 100ms between plot updates

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
            interval=10,
            blit=True,
            cache_frame_data=False
        )

    def _init_animation(self):
        """Initialize animation - return empty list if no devices yet."""
        return self._plot_lines

    def add_device(self, port: str):
        """Add a device to track in the plotter."""
        if port in self._unit_ids:
            return

        # Initialize reaction time tracking for device
        self._rt_now[port] = None
        self._rt_index[port] = 0

        self._rt_array[port] = {
            'hit': np.full(self.BUFFER_SIZE, np.nan),
            'miss': np.full(self.BUFFER_SIZE, np.nan)
        }

        self._rt_xy[port] = {}
        self._rt_xy[port]['hit'] = self._ax_rt.plot(
            self._time_array, self._rt_array[port]['hit'],
            marker='o', linestyle='', markersize=3
        )

        c = self._rt_xy[port]['hit'][0].get_color()
        self._rt_xy[port]['miss'] = self._ax_rt.plot(
            self._time_array, self._rt_array[port]['miss'],
            marker='x', linestyle='', markersize=3, color=c
        )

        # Initialize stimulus state tracking for device
        self._state_now[port] = 0
        self._state_index[port] = 0
        self._state_array[port] = np.full(self.BUFFER_SIZE, np.nan)
        self._state_xy[port] = self._ax_state.plot(
            self._time_array, self._state_array[port],
            linewidth=1.5
        )

        self._unit_ids.add(port)
        self._rebuild_plot_lines()

    def _rebuild_plot_lines(self):
        """Rebuild the list of plot lines for animation."""
        # Always include default lines
        self._plot_lines = [self._default_state_line, self._default_rt_hit, self._default_rt_miss]
        # Add device-specific lines
        for port in self._unit_ids:
            if port in self._state_xy:
                self._plot_lines.extend(self._state_xy[port])
            if port in self._rt_xy:
                self._plot_lines.extend(self._rt_xy[port]['hit'])
                self._plot_lines.extend(self._rt_xy[port]['miss'])

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

    def _animate(self, i):
        """Animation frame callback."""
        if not self.run or not self._ready_to_update():
            return self._plot_lines

        for unit_id in list(self._unit_ids):
            try:
                self._rescale_rt_y(self._rt_now.get(unit_id))

                idx = self._rt_index[unit_id]
                rt_val = self._rt_now.get(unit_id)
                if rt_val is not None:
                    if rt_val > 0:
                        self._rt_array[unit_id]['hit'][idx] = rt_val
                        self._rt_array[unit_id]['miss'][idx] = np.nan
                    else:
                        self._rt_array[unit_id]['hit'][idx] = np.nan
                        self._rt_array[unit_id]['miss'][idx] = abs(rt_val)
                else:
                    self._rt_array[unit_id]['hit'][idx] = np.nan
                    self._rt_array[unit_id]['miss'][idx] = np.nan

                self._rt_index[unit_id] = (idx + 1) % self.BUFFER_SIZE
                self._rt_now[unit_id] = None

                rt_view_hit = self._get_circular_view(self._rt_array[unit_id]['hit'], self._rt_index[unit_id])
                rt_view_miss = self._get_circular_view(self._rt_array[unit_id]['miss'], self._rt_index[unit_id])
                self._rt_xy[unit_id]['hit'][0].set_ydata(rt_view_hit)
                self._rt_xy[unit_id]['miss'][0].set_ydata(rt_view_miss)

                state_idx = self._state_index[unit_id]
                self._state_array[unit_id][state_idx] = self._state_now.get(unit_id, 0)
                self._state_index[unit_id] = (state_idx + 1) % self.BUFFER_SIZE

                state_view = self._get_circular_view(self._state_array[unit_id], self._state_index[unit_id])
                self._state_xy[unit_id][0].set_ydata(state_view)

            except (KeyError, IndexError) as e:
                self.logger.debug("Animation error for %s: %s", unit_id, e)

        return self._plot_lines

    def _get_circular_view(self, arr, head_idx):
        """Get circular buffer view starting from head index."""
        return np.concatenate((arr[head_idx:], arr[:head_idx]))

    def _rescale_rt_y(self, val=None):
        """Auto-scale Y axis if values exceed current range."""
        if val is not None:
            abs_val = abs(val)
            if abs_val >= self._rt_y_max:
                self._ax_rt.set_yticks(np.arange(0, abs_val, 1))
                self._ax_rt.set_ylim(self._rt_y_min - 0.3, abs_val * 1.2)
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

        if port not in self._rt_now:
            self.add_device(port)

        rt_seconds = reaction_time / 1000.0

        if is_hit:
            self._rt_now[port] = rt_seconds
        else:
            self._rt_now[port] = -rt_seconds

    def update_stimulus_state(self, port: str, state: int):
        """Update stimulus state for a device.

        Args:
            port: Device port/ID
            state: Stimulus state (0=off, 1=on)
        """
        if not self._recording:
            return

        if port not in self._state_now:
            self.add_device(port)

        self._state_now[port] = int(state)

    # ------------------------------------------------------------------
    # Session and recording control

    def start_session(self):
        """Start a new session - clear plot and start animation (blank)."""
        self.logger.info("START SESSION: Clearing plot and starting animation (blank)")
        self.clear_all()
        self.run = True
        self._session_active = True
        self._recording = False

    def start_recording(self):
        """Start recording - data will start appearing on plot."""
        self.logger.info("START RECORDING: Data will start appearing")
        if not self._session_active:
            self.logger.info("  First recording - clearing plot")
            self.start_session()
        else:
            self.logger.info("  Resuming animation from frozen state")
            self.run = True

        for port in list(self._state_now.keys()):
            self._state_now[port] = 0

        self._recording = True

    def stop_recording(self):
        """Pause recording - creates gap in data, animation keeps marching."""
        self.logger.info("STOP RECORDING: Creating gap, animation keeps marching")
        for port in list(self._state_now.keys()):
            self._state_now[port] = np.nan
        self._recording = False

    def pause(self):
        """Pause recording - creates gap in data, animation keeps marching."""
        self.logger.info("PAUSE: Creating gap in stimulus line, animation keeps running")
        for port in list(self._state_now.keys()):
            self._state_now[port] = np.nan
        self._recording = False

    def stop(self):
        """Stop session completely - freeze animation."""
        self.logger.info("STOP: Freezing animation completely")
        for port in list(self._state_now.keys()):
            idx = self._state_index.get(port, 0)
            self._state_array[port][idx] = np.nan
            self._state_index[port] = (idx + 1) % self.BUFFER_SIZE
            state_view = self._get_circular_view(self._state_array[port], self._state_index[port])
            self._state_xy[port][0].set_ydata(state_view)
        self.run = False
        self._session_active = False
        self._recording = False

    def remove_device(self, port: str):
        """Remove a device from the plotter."""
        if port not in self._unit_ids:
            return

        if port in self._rt_xy:
            self._rt_xy[port]['hit'][0].remove()
            self._rt_xy[port]['miss'][0].remove()
            del self._rt_xy[port]

        if port in self._state_xy:
            self._state_xy[port][0].remove()
            del self._state_xy[port]

        if port in self._rt_array:
            del self._rt_array[port]
            del self._rt_now[port]
            del self._rt_index[port]

        if port in self._state_array:
            del self._state_array[port]
            del self._state_now[port]
            del self._state_index[port]

        self._unit_ids.discard(port)
        self._rebuild_plot_lines()

        self.logger.info("Removed device %s from plotter", port)

    def clear_all(self):
        """Clear all data from the plot."""
        for unit_id in self._state_array.keys():
            self._state_now[unit_id] = np.nan
            self._state_array[unit_id][:] = np.nan
            self._state_index[unit_id] = 0
            self._state_xy[unit_id][0].set_ydata(self._state_array[unit_id])

        for unit_id in self._rt_array.keys():
            self._rt_array[unit_id]['hit'][:] = np.nan
            self._rt_array[unit_id]['miss'][:] = np.nan
            self._rt_index[unit_id] = 0
            self._rt_xy[unit_id]['hit'][0].set_ydata(self._rt_array[unit_id]['hit'])
            self._rt_xy[unit_id]['miss'][0].set_ydata(self._rt_array[unit_id]['miss'])

        # Reset Y scale
        self._rt_y_max = 1
        self._ax_rt.set_yticks(np.arange(0, 2, 1))
        self._ax_rt.set_ylim(-0.2, 1.2)
        self._ax_rt.figure.canvas.draw_idle()

    @property
    def recording(self) -> bool:
        """Whether recording is active."""
        return self._recording
