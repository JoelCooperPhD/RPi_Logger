import numpy as np
import matplotlib
matplotlib.use('TkAgg')
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.animation import FuncAnimation
import logging
import time

logger = logging.getLogger(__name__)


class DRTPlotter:
    def __init__(self, parent_frame):
        self._parent = parent_frame
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

        self._state_now = {}
        self._state_array = {}
        self._state_xy = {}

        self._unit_ids = set()
        self._plot_lines = set()

        self._rt_y_min = 0
        self._rt_y_max = 1

        self._next_update = time.time()
        self._interval = 0.1

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

        self._rt_array[port] = {
            'hit': np.full(600, np.nan),
            'miss': np.full(600, np.nan)
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
        self._state_array[port] = np.full(600, np.nan)
        self._state_xy[port] = self._ax_state.plot(
            self._time_array, self._state_array[port],
            linewidth=1.5
        )

        self._unit_ids.add(port)

        if self._ani is None:
            self._ani = FuncAnimation(
                self._fig,
                self._animate,
                init_func=lambda: self._init_animation(port),
                interval=10,
                blit=True,
                cache_frame_data=False
            )

    def _init_animation(self, port):
        if port in self._state_xy:
            self._state_xy[port][0].set_data(self._time_array, self._state_array[port])
            self._plot_lines.update(self._state_xy[port])

        if port in self._rt_xy:
            self._rt_xy[port]['hit'][0].set_data(self._time_array, self._rt_array[port]['hit'])
            self._rt_xy[port]['miss'][0].set_data(self._time_array, self._rt_array[port]['miss'])
            self._plot_lines.update(self._rt_xy[port]['hit'])
            self._plot_lines.update(self._rt_xy[port]['miss'])

        return self._plot_lines

    def _animate(self, i):
        if not self.run:
            return self._plot_lines

        if not self._ready_to_update():
            return self._plot_lines

        for unit_id in list(self._unit_ids):
            try:
                self._rescale_rt_y(self._rt_now.get(unit_id))

                self._rt_array[unit_id]['hit'] = np.roll(self._rt_array[unit_id]['hit'], -1)
                self._rt_array[unit_id]['miss'] = np.roll(self._rt_array[unit_id]['miss'], -1)

                rt_val = self._rt_now.get(unit_id)
                if rt_val is not None:
                    if rt_val > 0:
                        self._rt_array[unit_id]['hit'][-1] = rt_val
                        self._rt_array[unit_id]['miss'][-1] = np.nan
                    else:
                        self._rt_array[unit_id]['hit'][-1] = np.nan
                        self._rt_array[unit_id]['miss'][-1] = abs(rt_val)
                else:
                    self._rt_array[unit_id]['hit'][-1] = np.nan
                    self._rt_array[unit_id]['miss'][-1] = np.nan

                self._rt_xy[unit_id]['hit'][0].set_data(self._time_array, self._rt_array[unit_id]['hit'])
                self._rt_xy[unit_id]['miss'][0].set_data(self._time_array, self._rt_array[unit_id]['miss'])

                self._rt_now[unit_id] = None

                self._plot_lines.update(self._rt_xy[unit_id]['hit'])
                self._plot_lines.update(self._rt_xy[unit_id]['miss'])

                self._state_array[unit_id] = np.roll(self._state_array[unit_id], -1)
                self._state_array[unit_id][-1] = self._state_now.get(unit_id, 0)
                self._state_xy[unit_id][0].set_data(self._time_array, self._state_array[unit_id])

                self._plot_lines.update(self._state_xy[unit_id])

            except (KeyError, IndexError) as e:
                logger.debug(f"Animation error for {unit_id}: {e}")

        return self._plot_lines

    def _ready_to_update(self):
        t = time.time()
        if t >= self._next_update:
            if (t - self._next_update) > 0.25:
                self._next_update = t
            else:
                self._next_update += self._interval
            return True
        return False

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
        logger.info("PAUSE: Creating gap in stimulus line, animation keeps running")
        for port in list(self._state_now.keys()):
            self._state_now[port] = np.nan
        self._recording = False

    def stop(self):
        logger.info("STOP: Freezing animation completely")
        for port in list(self._state_now.keys()):
            self._state_array[port] = np.roll(self._state_array[port], -1)
            self._state_array[port][-1] = np.nan
            self._state_xy[port][0].set_data(self._time_array, self._state_array[port])
        self.run = False
        self._session_active = False
        self._recording = False

    def start_session(self):
        logger.info("START SESSION: Clearing plot and starting animation (blank)")
        self.clear_all()
        self.run = True
        self._session_active = True
        self._recording = False

    def start_recording(self):
        logger.info("START RECORDING: Data will start appearing")
        if not self._session_active:
            logger.info("  First recording - clearing plot")
            self.start_session()
        else:
            logger.info("  Resuming animation from frozen state")
            self.run = True

        for port in list(self._state_now.keys()):
            self._state_now[port] = 0

        self._recording = True

    def stop_recording(self):
        logger.info("STOP RECORDING: Creating gap, animation keeps marching")
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

        if port in self._state_array:
            del self._state_array[port]
            del self._state_now[port]

        self._unit_ids.discard(port)

        logger.info(f"Removed device {port} from plotter")

    def clear_all(self):
        for unit_id in self._state_array.keys():
            self._state_now[unit_id] = np.nan
            self._state_array[unit_id][:] = np.nan
            self._state_xy[unit_id][0].set_data(self._time_array, self._state_array[unit_id])

        for unit_id in self._rt_array.keys():
            self._rt_array[unit_id]['hit'][:] = np.nan
            self._rt_array[unit_id]['miss'][:] = np.nan
            self._rt_xy[unit_id]['hit'][0].set_data(self._time_array, self._rt_array[unit_id]['hit'])
            self._rt_xy[unit_id]['miss'][0].set_data(self._time_array, self._rt_array[unit_id]['miss'])

        self._ax_rt.figure.canvas.draw_idle()
