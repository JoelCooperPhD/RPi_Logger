from pyb import Pin
import uasyncio as asyncio
from utime import ticks_ms, ticks_diff, ticks_us

class DebouncedSwitch:
    """
    Class for a debounced switch. 
    This class manages a switch input with software debouncing and callback functions.
    """
    def __init__(self, pin="Y9", debounce_ms=20, debug=False):
        """
        Initializes the DebouncedSwitch with a specified pin and debounce time.

        Args:
            pin (str): The pin the switch is connected to. Defaults to "Y9".
            debounce_ms (int): The debounce time in milliseconds. Defaults to 20.
            debug (bool): If True, debug information is printed. Defaults to False.
        """
        self._debug = debug
        if self._debug: print(f'{ticks_us()} DebouncedSwitch.__init__')
        
        self._switch = Pin(pin, mode=Pin.IN, pull=Pin.PULL_UP)
        self._debounce_ms = debounce_ms
        self._down_cnt = 0
        self._up_cnt = 0
        self._open_close_cb = None

    async def update(self):
        """
        Updates the switch state and counters, and calls the callback function when a change is detected.
        """
        if self._debug: print(f'{ticks_us()} DebouncedSwitch.update')
        
        now_state = 1
        then_state = 1
        debounced = True
        triggered_ms = 0

        while True:
            now_state = self._switch.value()
            if now_state != then_state:
                if debounced:
                    triggered_ms = ticks_ms()
                    if now_state == 1:
                        self._up_cnt += 1
                    else:
                        self._down_cnt += 1
                    if self._open_close_cb:
                        self._open_close_cb(now_state, triggered_ms, self._down_cnt, self._up_cnt)
                    debounced = False
                    then_state = now_state
            if not debounced and ticks_diff(ticks_ms(), triggered_ms) > self._debounce_ms:
                debounced = True
            await asyncio.sleep(0)
            
    def set_open_closed_callback(self, cb):
        """
        Sets the callback function that is called when a switch state change is detected.

        Args:
            cb (function): The callback function. It should accept four parameters: the switch state, 
            the time of the state change, the down counter, and the up counter.
        """
        if self._debug: print(f'{ticks_us()} DebouncedSwitch.set_open_closed_callback')
        
        self._open_close_cb = cb

    def reset_counters(self):
        """
        Resets the down and up counters to zero.
        """
        if self._debug: print(f'{ticks_us()} DebouncedSwitch.reset_counters')
        
        self._down_cnt = 0
        self._up_cnt = 0

if __name__ == "__main__":
    switch = DebouncedSwitch(debounce_ms=20, debug=True)
    switch._open_close_cb = lambda a, b, c, d: print(f"Switch state: {a}, Time: {b}, Down: {c}, Up: {d}")
    asyncio.run(switch.update())
