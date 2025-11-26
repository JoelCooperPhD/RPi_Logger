import numpy as np
import matplotlib
matplotlib.use('TkAgg')
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.animation import FuncAnimation
from rpi_logger.core.logging_utils import get_module_logger


class DRTPlotter:
    BUFFER_SIZE = 600

    def __init__(self, parent_frame):
        self._parent = parent_frame
        self.logger = get_module_logger("DRTPlotter")
        self._time_array = np.arange(-60, 0, 0.1)

        self._fig = Figure(figsize=(4, 2), dpi=100)
        self._fig.suptitle("DRT - Detection Response Task")

        self._ax_state = self._fig.add_subplot(211)
        self._ax_rt = self._fig.add_subplot(212)

        self._setup_plots()

        self._canvas = FigureCanvasTkAgg(self._fig, master=parent_frame)
        self._canvas.draw()
        self._canvas.get_tk_widget().grid(row=0, column=0, rowspan=20, sticky='nsew', padx=2, pady=2)

        self._rt_now = {}
        self._rt_array = {}
        self._rt_xy = {}
        self._rt_index = {}

        self._state_now = {}
        self._state_array = {}
        self._state_xy = {}
        self._state_index = {}

        self._unit_ids = set()
        self._plot_lines = []

        self._rt_y_min = 0
        self._rt_y_max = 1

        self._ani = None
        self.run = False
        self._session_active = False
        self._recording = False

    def _setup_plots(self):
        self._ax_state.xaxis.set_tick_params(labelbottom=False)
        self._ax_state.set_ylabel("Stimulus")
        self._ax_state.yaxis.set_label_position('right')
        self._ax_state.set_ylim(-0.2, 1.2)
        self._ax_state.set_yticks([0, 1])
        self._ax_state.set_yticklabels(["Off", "On"])
        self._ax_state.set_xticks([-60, -50, -40, -30, -20, -10, 0])
        self._ax_state.set_xlim(-62, 2)

        self._ax_rt.set_ylabel("RT-Seconds")
        self._ax_rt.yaxis.set_label_position('right')
        self._ax_rt.set_xticks([-60, -50, -40, -30, -20, -10, 0])
        self._ax_rt.set_xlim(-62, 2)
        self._ax_rt.set_yticks(np.arange(0, 2, 1))
        self._ax_rt.set_ylim(-0.2, 1.2)

        self._fig.tight_layout()

    def add_device(self, port: str):
        if port in self._unit_ids:
            return

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

        self._state_now[port] = 0
        self._state_index[port] = 0
        self._state_array[port] = np.full(self.BUFFER_SIZE, np.nan)
        self._state_xy[port] = self._ax_state.plot(
            self._time_array, self._state_array[port],
            linewidth=1.5
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
        self._plot_lines = []
        for port in self._unit_ids:
            if port in self._state_xy:
                self._plot_lines.extend(self._state_xy[port])
            if port in self._rt_xy:
                self._plot_lines.extend(self._rt_xy[port]['hit'])
                self._plot_lines.extend(self._rt_xy[port]['miss'])

    def _init_animation(self, port):
        if port in self._state_xy:
            self._state_xy[port][0].set_data(self._time_array, self._state_array[port])

        if port in self._rt_xy:
            self._rt_xy[port]['hit'][0].set_data(self._time_array, self._rt_array[port]['hit'])
            self._rt_xy[port]['miss'][0].set_data(self._time_array, self._rt_array[port]['miss'])

        return self._plot_lines

    def _animate(self, i):
        if not self.run:
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
        return np.concatenate((arr[head_idx:], arr[:head_idx]))


    def _rescale_rt_y(self, val=None):
        if val is not None:
            abs_val = abs(val)
            if abs_val >= self._rt_y_max:
                self._ax_rt.set_yticks(np.arange(0, abs_val, 1))
                self._ax_rt.set_ylim(self._rt_y_min - 0.3, abs_val * 1.2)
                self._rt_y_max = abs_val
                self._ax_rt.figure.canvas.draw_idle()

    def update_trial(self, port: str, reaction_time: float, is_hit: bool = True):
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
        if not self._recording:
            return

        if port not in self._state_now:
            self.add_device(port)

        self._state_now[port] = int(state)

    def pause(self):
        self.logger.info("PAUSE: Creating gap in stimulus line, animation keeps running")
        for port in list(self._state_now.keys()):
            self._state_now[port] = np.nan
        self._recording = False

    def stop(self):
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

    def start_session(self):
        self.logger.info("START SESSION: Clearing plot and starting animation (blank)")
        self.clear_all()
        self.run = True
        self._session_active = True
        self._recording = False

    def start_recording(self):
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
        self.logger.info("STOP RECORDING: Creating gap, animation keeps marching")
        for port in list(self._state_now.keys()):
            self._state_now[port] = np.nan
        self._recording = False

    def remove_device(self, port: str):
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

        self._ax_rt.figure.canvas.draw_idle()
