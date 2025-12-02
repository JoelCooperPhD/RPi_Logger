"""VOG real-time plotter using matplotlib FuncAnimation.

Based on RS_Logger's sVOG_UIPlotter.py pattern - uses device-keyed dictionaries
(maps) to support multiple simultaneous devices.
"""

from __future__ import annotations

import time
from typing import Dict, Optional, Set, TYPE_CHECKING

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

if TYPE_CHECKING:
    from tkinter import Widget


class VOGPlotter:
    """Real-time plotter for VOG stimulus state and shutter timing data.

    Supports multiple devices via device-keyed dictionaries. Each device gets
    its own set of plot lines and data arrays.

    Layout:
        - Top subplot (211): Stimulus state (Clear/Opaque) over time
        - Bottom subplot (212): TSOT (Total Shutter Open Time) and TSCT over time
    """

    def __init__(self, frame: "Widget", title: str = "VOG - Visual Occlusion Glasses"):
        if not HAS_MATPLOTLIB:
            raise ImportError("matplotlib is required for VOGPlotter")

        # Chart setup
        self._fig = Figure(figsize=(4, 2), dpi=100)
        self._fig.suptitle(title, fontsize=9)
        self._canvas = FigureCanvasTkAgg(self._fig, master=frame)
        self._canvas.get_tk_widget().grid(row=0, column=0, padx=2, pady=2, sticky='NEWS', rowspan=20)

        self._plt: list = []

        # Track registered device IDs
        self._unit_ids: Set[str] = set()

        # Time axis: 60 seconds of history at 100ms resolution
        self._time_array = np.arange(-60, 0, 0.1)

        # Update throttling
        self._next_update = time.time()
        self._interval = 0.1  # 100ms between plot updates

        # Total Shutter Times - device-keyed maps
        self._tsot_now: Dict[str, Optional[float]] = {}
        self._tsct_now: Dict[str, Optional[float]] = {}
        self._tst_array: Dict[str, Dict[str, np.ndarray]] = {}
        self._tst_xy: Dict[str, Dict[str, list]] = {}

        self._tst_y_min = 0
        self._tst_y_max = 3000

        # All plot line objects for animation blitting
        self._plot_lines: Set = set()

        # Stimulus State - device-keyed maps
        self._state_now: Dict[str, float] = {}
        self._state_array: Dict[str, np.ndarray] = {}
        self._state_xy: Dict[str, list] = {}

        # Animation control
        self._ani: Optional[animation.FuncAnimation] = None

        # Build subplots
        self._add_tsot_plot()
        self._add_state_plot()

        # Control flags
        self.run = False
        self.recording = False

    def _add_tsot_plot(self):
        """Add bottom subplot for TSOT/TSCT timing data."""
        self._plt.append(self._fig.add_subplot(212))
        self._plt[0].set_ylabel("TSOT-TSCT", fontsize=8)
        self._plt[0].yaxis.set_label_position('right')
        self._plt[0].tick_params(axis='both', labelsize=7)

    def _add_state_plot(self):
        """Add top subplot for stimulus state (Clear/Opaque)."""
        self._plt.append(self._fig.add_subplot(211))
        self._plt[1].xaxis.set_tick_params(labelbottom=False)
        self._plt[1].set_ylabel("State", fontsize=8)
        self._plt[1].yaxis.set_label_position('right')
        self._plt[1].set_ylim([-0.2, 1.2])
        self._plt[1].set_yticks([0, 1])
        self._plt[1].set_yticklabels(["Opaque", "Clear"], fontsize=7)
        self._plt[1].tick_params(axis='x', labelsize=7)

    def add_device(self, unit_id: str):
        """Add a new device to the plotter.

        Creates data arrays and plot lines for the device.
        """
        if unit_id in self._unit_ids:
            return

        # Initialize TSOT/TSCT data
        self._tsot_now[unit_id] = None
        self._tsct_now[unit_id] = None

        self._tst_array[unit_id] = {}
        self._tst_xy[unit_id] = {}

        # TSOT array and line
        self._tst_array[unit_id]['tsot'] = np.empty([600])
        self._tst_array[unit_id]['tsot'][:] = np.nan
        self._tst_xy[unit_id]['tsot'] = self._plt[0].plot(
            self._time_array, self._tst_array[unit_id]['tsot'], marker="o", markersize=3
        )

        # Get color from TSOT line to match TSCT
        c = self._tst_xy[unit_id]['tsot'][0].get_color()

        # TSCT array and line (same color, different marker)
        self._tst_array[unit_id]['tsct'] = np.empty([600])
        self._tst_array[unit_id]['tsct'][:] = np.nan
        self._tst_xy[unit_id]['tsct'] = self._plt[0].plot(
            self._time_array, self._tst_array[unit_id]['tsct'], marker="_", color=c, markersize=3
        )

        # Configure TST axes
        self._plt[0].set_xticks([-60, -50, -40, -30, -20, -10, 0])
        self._plt[0].set_xlim([-62, 2])
        self._plt[0].set_yticks(np.arange(0, 3000, 1000))
        self._plt[0].set_ylim([0, 3000])

        # Initialize state data
        self._state_now[unit_id] = np.nan
        self._state_array[unit_id] = np.empty([600])
        self._state_array[unit_id][:] = np.nan
        self._state_xy[unit_id] = self._plt[1].plot(
            self._time_array, self._state_array[unit_id], marker=""
        )

        # Configure state axes
        self._plt[1].set_xticks([-60, -50, -40, -30, -20, -10, 0])
        self._plt[1].set_xlim([-62, 2])

        # Start animation if not already running
        if self._ani is None:
            self._ani = animation.FuncAnimation(
                self._fig,
                self._animate,
                init_func=lambda prt=unit_id: self._init_animation(prt),
                interval=10,
                blit=True,
                cache_frame_data=False
            )

        self._unit_ids.add(unit_id)

    def remove_device(self, unit_id: str):
        """Remove a device from the plotter."""
        if unit_id not in self._unit_ids:
            return

        self._state_array.pop(unit_id, None)
        self._state_xy.pop(unit_id, None)
        self._state_now.pop(unit_id, None)
        self._tst_array.pop(unit_id, None)
        self._tst_xy.pop(unit_id, None)
        self._tsot_now.pop(unit_id, None)
        self._tsct_now.pop(unit_id, None)
        self._unit_ids.discard(unit_id)

    def _init_animation(self, p: str):
        """Initialize animation with current data."""
        if p not in self._state_xy:
            return self._plot_lines

        self._state_xy[p][0].set_data(self._time_array, self._state_array[p])
        self._tst_xy[p]['tsot'][0].set_data(self._time_array, self._tst_array[p]['tsot'])
        self._tst_xy[p]['tsct'][0].set_data(self._time_array, self._tst_array[p]['tsct'])

        self._plot_lines.update(self._state_xy[p])
        self._plot_lines.update(self._tst_xy[p]['tsot'])
        self._plot_lines.update(self._tst_xy[p]['tsct'])

        return self._plot_lines

    def _animate(self, i):
        """Animation frame callback."""
        if self.run and self._ready_to_update():
            for unit_id in self._unit_ids:
                if unit_id not in self._tst_array:
                    continue

                # Rescale Y axis if needed
                self._rescale_y(self._tsot_now.get(unit_id), self._tsct_now.get(unit_id))

                # Roll and update TST arrays
                self._tst_array[unit_id]['tsot'] = np.roll(self._tst_array[unit_id]['tsot'], -1)
                self._tst_array[unit_id]['tsct'] = np.roll(self._tst_array[unit_id]['tsct'], -1)

                if self._tsot_now.get(unit_id) is not None:
                    self._tst_array[unit_id]['tsot'][-1] = self._tsot_now[unit_id]
                else:
                    self._tst_array[unit_id]['tsot'][-1] = np.nan

                if self._tsct_now.get(unit_id) is not None:
                    self._tst_array[unit_id]['tsct'][-1] = self._tsct_now[unit_id]
                else:
                    self._tst_array[unit_id]['tsct'][-1] = np.nan

                self._tst_xy[unit_id]['tsot'][0].set_data(self._time_array, self._tst_array[unit_id]['tsot'])
                self._tst_xy[unit_id]['tsct'][0].set_data(self._time_array, self._tst_array[unit_id]['tsct'])

                self._tsot_now[unit_id] = None
                self._tsct_now[unit_id] = None

                self._plot_lines.update(self._tst_xy[unit_id]['tsot'])
                self._plot_lines.update(self._tst_xy[unit_id]['tsct'])

                # Roll and update state array
                self._state_array[unit_id] = np.roll(self._state_array[unit_id], -1)
                self._state_array[unit_id][-1] = self._state_now.get(unit_id, np.nan)
                self._state_xy[unit_id][0].set_data(self._time_array, self._state_array[unit_id])

                self._plot_lines.update(self._state_xy[unit_id])

        return self._plot_lines

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
            self._plt[0].set_ylim(self._tst_y_min - 0.3, val * 1.2)
            self._tst_y_max = val
            self._plt[0].figure.canvas.draw_idle()

    # ------------------------------------------------------------------
    # Public update methods

    def tsot_update(self, unit_id: str, val: float):
        """Update TSOT value for a device."""
        self._tsot_now[unit_id] = val

    def tsct_update(self, unit_id: str, val: float):
        """Update TSCT value for a device."""
        self._tsct_now[unit_id] = val

    def state_update(self, unit_id: str, val: float):
        """Update stimulus state for a device (only if recording)."""
        if self.recording:
            self._state_now[unit_id] = val

    def clear_all(self):
        """Clear all data from all devices."""
        for unit_id in list(self._state_array.keys()):
            self._state_now[unit_id] = np.nan
            self._state_array[unit_id][:] = np.nan
            if unit_id in self._state_xy:
                self._state_xy[unit_id][0].set_data(self._time_array, self._state_array[unit_id])

        for unit_id in list(self._tst_array.keys()):
            self._tst_array[unit_id]['tsot'][:] = np.nan
            self._tst_array[unit_id]['tsct'][:] = np.nan
            if unit_id in self._tst_xy:
                self._tst_xy[unit_id]['tsot'][0].set_data(self._time_array, self._tst_array[unit_id]['tsot'])
                self._tst_xy[unit_id]['tsct'][0].set_data(self._time_array, self._tst_array[unit_id]['tsct'])

        # Reset Y scale
        self._tst_y_max = 3000
        self._plt[0].set_yticks(np.arange(0, 3000, 1000))
        self._plt[0].set_ylim([0, 3000])
        self._plt[0].figure.canvas.draw_idle()
