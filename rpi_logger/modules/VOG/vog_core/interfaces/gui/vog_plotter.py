"""VOG real-time plotter for shutter state visualization."""

import numpy as np
import matplotlib
matplotlib.use('TkAgg')
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.animation import FuncAnimation
from rpi_logger.core.logging_utils import get_module_logger


class VOGPlotter:
    """Real-time plotter showing shutter open/closed state."""

    BUFFER_SIZE = 600  # 60 seconds at 10Hz update

    def __init__(self, parent_frame):
        self._parent = parent_frame
        self.logger = get_module_logger("VOGPlotter")
        self._time_array = np.arange(-60, 0, 0.1)

        self._fig = Figure(figsize=(4, 2), dpi=100)
        self._fig.suptitle("VOG - Shutter State")

        self._ax_shutter = self._fig.add_subplot(111)
        self._setup_plot()

        self._canvas = FigureCanvasTkAgg(self._fig, master=parent_frame)
        self._canvas.draw()
        self._canvas.get_tk_widget().grid(row=0, column=0, rowspan=20, sticky='nsew', padx=2, pady=2)

        # State tracking per device
        self._shutter_now = {}  # Current shutter state (0=closed, 1=open)
        self._shutter_array = {}  # History buffer
        self._shutter_xy = {}  # Plot lines
        self._shutter_index = {}  # Current index in circular buffer

        self._unit_ids = set()
        self._plot_lines = []

        self._ani = None
        self.run = False
        self._session_active = False
        self._recording = False

    def _setup_plot(self):
        """Configure the shutter state plot."""
        self._ax_shutter.set_ylabel("Shutter")
        self._ax_shutter.yaxis.set_label_position('right')
        self._ax_shutter.set_ylim(-0.2, 1.2)
        self._ax_shutter.set_yticks([0, 1])
        self._ax_shutter.set_yticklabels(["Closed", "Open"])
        self._ax_shutter.set_xticks([-60, -50, -40, -30, -20, -10, 0])
        self._ax_shutter.set_xlim(-62, 2)
        self._ax_shutter.set_xlabel("Time (seconds)")

        self._fig.tight_layout()

    def add_device(self, port: str):
        """Add a device to the plotter."""
        if port in self._unit_ids:
            return

        self._shutter_now[port] = 0
        self._shutter_index[port] = 0
        self._shutter_array[port] = np.full(self.BUFFER_SIZE, np.nan)
        self._shutter_xy[port] = self._ax_shutter.plot(
            self._time_array, self._shutter_array[port],
            linewidth=2.0
        )

        self._unit_ids.add(port)
        self._rebuild_plot_lines()

        if self._ani is None:
            self._ani = FuncAnimation(
                self._fig,
                self._animate,
                init_func=lambda: self._init_animation(port),
                interval=100,
                blit=True,
                cache_frame_data=False
            )

    def _rebuild_plot_lines(self):
        """Rebuild list of plot lines for animation."""
        self._plot_lines = []
        for port in self._unit_ids:
            if port in self._shutter_xy:
                self._plot_lines.extend(self._shutter_xy[port])

    def _init_animation(self, port):
        """Initialize animation for a device."""
        if port in self._shutter_xy:
            self._shutter_xy[port][0].set_data(self._time_array, self._shutter_array[port])
        return self._plot_lines

    def _animate(self, i):
        """Animation update function."""
        if not self.run:
            return self._plot_lines

        for unit_id in list(self._unit_ids):
            try:
                idx = self._shutter_index[unit_id]
                self._shutter_array[unit_id][idx] = self._shutter_now.get(unit_id, np.nan)
                self._shutter_index[unit_id] = (idx + 1) % self.BUFFER_SIZE

                view = self._get_circular_view(self._shutter_array[unit_id], self._shutter_index[unit_id])
                self._shutter_xy[unit_id][0].set_ydata(view)

            except (KeyError, IndexError) as e:
                self.logger.debug("Animation error for %s: %s", unit_id, e)

        return self._plot_lines

    def _get_circular_view(self, arr, head_idx):
        """Get linear view of circular buffer."""
        return np.concatenate((arr[head_idx:], arr[:head_idx]))

    def update_shutter_state(self, port: str, is_open: bool):
        """Update shutter state for a device.

        Args:
            port: Device port identifier
            is_open: True if shutter is open, False if closed
        """
        if not self._recording:
            return

        if port not in self._shutter_now:
            self.add_device(port)

        self._shutter_now[port] = 1 if is_open else 0

    def update_trial_data(self, port: str, shutter_open: int, shutter_closed: int):
        """Update from trial data received from device.

        Args:
            port: Device port identifier
            shutter_open: Duration shutter was open (ms)
            shutter_closed: Duration shutter was closed (ms)
        """
        if not self._recording:
            return

        if port not in self._shutter_now:
            self.add_device(port)

        # Determine current state based on most recent timing
        # If shutter_open > 0, it was open; otherwise closed
        is_open = shutter_open > 0
        self._shutter_now[port] = 1 if is_open else 0

    def pause(self):
        """Pause recording - creates gap in plot."""
        self.logger.info("PAUSE: Creating gap in shutter line")
        for port in list(self._shutter_now.keys()):
            self._shutter_now[port] = np.nan
        self._recording = False

    def stop(self):
        """Stop animation completely."""
        self.logger.info("STOP: Freezing animation")
        for port in list(self._shutter_now.keys()):
            idx = self._shutter_index.get(port, 0)
            self._shutter_array[port][idx] = np.nan
            self._shutter_index[port] = (idx + 1) % self.BUFFER_SIZE
            view = self._get_circular_view(self._shutter_array[port], self._shutter_index[port])
            self._shutter_xy[port][0].set_ydata(view)
        self.run = False
        self._session_active = False
        self._recording = False

    def start_session(self):
        """Start a new session - clears plot and starts animation."""
        self.logger.info("START SESSION: Clearing plot and starting animation")
        self.clear_all()
        self.run = True
        self._session_active = True
        self._recording = False

    def start_recording(self):
        """Start recording - data will appear on plot."""
        self.logger.info("START RECORDING: Data will start appearing")
        if not self._session_active:
            self.start_session()
        else:
            self.run = True

        for port in list(self._shutter_now.keys()):
            self._shutter_now[port] = 0  # Start with closed state

        self._recording = True

    def stop_recording(self):
        """Stop recording - creates gap in plot."""
        self.logger.info("STOP RECORDING: Creating gap")
        for port in list(self._shutter_now.keys()):
            self._shutter_now[port] = np.nan
        self._recording = False

    def remove_device(self, port: str):
        """Remove a device from the plotter."""
        if port not in self._unit_ids:
            return

        if port in self._shutter_xy:
            self._shutter_xy[port][0].remove()
            del self._shutter_xy[port]

        if port in self._shutter_array:
            del self._shutter_array[port]
            del self._shutter_now[port]
            del self._shutter_index[port]

        self._unit_ids.discard(port)
        self._rebuild_plot_lines()

        self.logger.info("Removed device %s from plotter", port)

    def clear_all(self):
        """Clear all plot data."""
        for unit_id in self._shutter_array.keys():
            self._shutter_now[unit_id] = np.nan
            self._shutter_array[unit_id][:] = np.nan
            self._shutter_index[unit_id] = 0
            self._shutter_xy[unit_id][0].set_ydata(self._shutter_array[unit_id])

        self._ax_shutter.figure.canvas.draw_idle()
