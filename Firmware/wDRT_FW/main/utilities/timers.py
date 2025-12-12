from utime import ticks_ms, ticks_us, ticks_diff
import uasyncio as asyncio


class Stopwatch:
    """
    A simple stopwatch class for measuring elapsed time.
    """

    def __init__(self, precision='ms', debug=False):
        """
        Constructor for the Stopwatch class.

        Args:
            precision (str): The precision of the stopwatch. Can be 'ms' or 'us'.
        """
        self._debug = debug
        if self._debug: print(f'{ticks_us()} Stopwatch.__init__')
        
        self._precision = precision
        self._tic = None
        self._running = False

    def start(self):
        """
        Start the stopwatch.
        """
        if self._debug: print(f'{ticks_us()} Stopwatch.start')
        
        self._running = True
        if self._precision == 'ms':
            self._tic = ticks_ms()
        elif self._precision == 'us':
            self._tic = ticks_us()

    def read(self):
        """
        Get the elapsed time since the stopwatch was started.

        Returns:
            int: The elapsed time in milliseconds or microseconds, depending on the precision of the stopwatch.
        """
        if self._debug: print(f'{ticks_us()} Stopwatch.read')
        
        if self._running:
            if self._precision == 'ms':
                return ticks_diff(ticks_ms(), self._tic)
            elif self._precision == 'us':
                return ticks_diff(ticks_us(), self._tic)
        else:
            return 0

    def stop(self, in_t=None):
        """
        Stop the stopwatch and get the elapsed time.

        Args:
            in_t (int): An optional timestamp to use as the end time.

        Returns:
            int: The elapsed time in milliseconds or microseconds, depending on the precision of the stopwatch.
        """
        if self._debug: print(f'{ticks_us()} Stopwatch.stop')
        
        if self._running:
            self._running = False

            if in_t:
                toc = in_t
            else:
                if self._precision == 'ms':
                    toc = ticks_ms()
                elif self._precision == 'us':
                    toc = ticks_us()

            return ticks_diff(toc, self._tic)
        else:
            return 0


class Countdown:
    """
    A class for managing a countdown timer with a specified duration and callback function.
    """

    def __init__(self, callback, duration=None, debug=False):
        """
        Constructor for the Countdown class.

        Args:
            callback (function): The callback function to call when the countdown is complete.
            duration (int): The duration of the countdown in milliseconds.
        """
        self._debug = debug
        if self._debug: print(f'{ticks_us()} Countdown.__init__')
        
        self._duration = duration
        self._callback = callback
        self._stop = False

    @property
    def duration(self):
        """
        Get the duration of the countdown.

        Returns:
            int: The duration of the countdown in milliseconds.
        """
        return self._duration

    @duration.setter
    def duration(self, val):
        """
        Set the duration of the countdown.

        Args:
            val (int): The duration of the countdown in milliseconds.
        """
        if isinstance(val, int) and val >= 0:
            self._duration = val

    async def start(self, start_t=None, duration=None):
        """
        Start the countdown.

        Args:
            start_t (int): The start time of the countdown. If None, the current time will be used.
            duration (int): The duration of the countdown in milliseconds. If None, the duration set in the constructor will be used.

        """
        if self._debug: print(f'{ticks_us()} Countdown.start')
        
        if duration:
            self._duration = duration
        if not start_t:
            start_t = ticks_ms()

        while True:
            elapsed = ticks_diff(ticks_ms(), start_t)
            if elapsed >= self._duration:
                self._callback(elapsed)
                break
            await asyncio.sleep(0)
            



class ABTimeAccumulator:
    """
    A class for measuring the elapsed time between two events that toggle a boolean state (e.g., measuring the amount of time
    a switch is open or closed).
    """

    def __init__(self, debug=False):
        """
        Constructor for the ABTimeAccumulator class.
        """
        self._debug= debug
        if self._debug: print(f'{ticks_us()} ABTimeAccumulator.__init__')
        
        # point time variables
        self._start_ms = 0
        self._stop_ms = 0
        self._toggle_ms = 0

        # time accumulators
        self._accumulator = [int(), int()]
        self._data = [str(), int(), int(), int()]

        # state tracker
        self._i = False
        self.running = False

    def start(self, now=None, start_open=True):
        """
        Start the time accumulator.

        Args:
            now (int): The current time. If None, the current time will be used.
            start_open (bool): Whether the starting state is "open" or "closed". If True, the starting state is "open".

        Returns:
            list: A list containing the current state of the accumulator.
        """
        if self._debug: print(f'{ticks_us()} ABTimeAccumulator.start')
        
        if not now:
            now = ticks_ms()
        self._start_ms, self._toggle_ms = now, now
        self._accumulator = [0, 0]
        self.running = True
        self._i = not start_open
        return self._state(now)

    def stop(self):
        """
        Stop the time accumulator.

        Returns:
            list: A list containing the final state of the accumulator.
        """
        if self._debug: print(f'{ticks_us()} ABTimeAccumulator.stop')
        
        now = ticks_ms()
        self._update_accumulator(now)
        self.running = False
        return self._state(now, tag='X')

    def toggle(self, now=None):
        """
        Toggle the state of the accumulator.

        Args:
            now (int): The current time. If None, the current time will be used.

        Returns:
            list: A list containing the current state of the accumulator.
        """
        if self._debug: print(f'{ticks_us()} ABTimeAccumulator.toggle')
        
        if not now:
            now = ticks_ms()

        self._update_accumulator(now)

        self._toggle_ms = now
        self._i = not self._i

        return self._state(now)

    def _update_accumulator(self, now):
        """
        Update the time accumulator with the elapsed time since the last toggle.

        Args:
            now (int): The current time.
        """
        if self._debug: print(f'{ticks_us()} ABTimeAccumulator._update_accumulator')
        
        elapsed = ticks_diff(now, self._toggle_ms)
        self._accumulator[self._i] += elapsed

    def _state(self, now, tag=None):
        """
        Get the current state of the time accumulator.

        Args:
            now (int): The current time.
            tag (str): A tag to add to the data list.

        Returns:
            list: A list containing the current state of the accumulator.
        """
        if self._debug: print(f'{ticks_us()} ABTimeAccumulator._state')
        
        if tag:
            self._data[3] = tag
        else:
            self._data[3] = '1' if self._i else '0'

        self._data[0:2] = self._accumulator
        self._data[2] = ticks_diff(now, self._start_ms)

        return self._data
