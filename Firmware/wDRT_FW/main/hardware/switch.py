from utime import ticks_us, ticks_ms, ticks_diff
from micropython import schedule
from pyb import Pin


class DebouncedSwitchIRQ:
    """
    A class that provides debouncing for a switch's interrupt requests (IRQs).
    """
    def __init__(self, pin="X11", debug=False):
        """
        Args:
            pin (str): Pin identifier.
            debug (bool): Debug mode flag.
        """
        self._debug = debug
        if self._debug: print(f'{ticks_us()} DebouncedSwitchIRQ.__init__ pin:{pin}')

        self._prior_closure_us = ticks_us()  # The last closure - used for debouncing

        # Pin Config
        self._pin = Pin(pin, mode=Pin.IN, pull=Pin.PULL_UP)
        self._pin.irq(trigger=Pin.IRQ_FALLING, handler=self._resp_down_irq)

        # Properties
        self._debounce_ms = 100
        
        self._debounced = True

        # Callbacks
        self._click_cb = None

    def set_closure_callback(self, callback):
        """
        Assigns a function to be called upon a closure event. This function should take 1 argument which is closure microseconds

        Args:
            callback (function): Function to be called upon closure event.
        """
        if self._debug: print(f'{ticks_us()} DebouncedSwitchIRQ.set_closure_callback')
        self._click_cb = callback

    # Debounced Milliseconds - switch close lockout period
    @property
    def debounce_ms(self):
        return self._debounce_ms

    @debounce_ms.setter
    def debounce_ms(self, val):
        if val < 0:
            val = 0
        self._debounce_ms = val

    ##################
    # Private Methods
    def _resp_down_irq(self, e):
        """
        Handles falling edge interrupts. i.e., when the switch is pressed.
        """
        now = ticks_us()
        if self._debug: self._print_message_to_screen(f'{ticks_us()} DebouncedSwitchIRQ._resp_down_irq now:{now}')
        
        diff = ticks_diff(now, self._prior_closure_us) // 1000
        if diff > self.debounce_ms:
            if self._debug: self._print_message_to_screen(f'{ticks_us()} DebouncedSwitchIRQ._resp_down_irq Debounced {diff}')
            if self._click_cb:
                schedule(self._click_cb, now)
        else:
            if self._debug: self._print_message_to_screen(f'{ticks_us()} DebouncedSwitchIRQ._resp_down_irq NOT Debounced {diff}')
            
        self._prior_closure_us = now
                 
    def _print_message_to_screen(self, msg: str):
        """
        Prints a message to the console. Required for printing from an IRQ
        """
        print(msg)
        
if __name__ == '__main__':
    DebouncedSwitchIRQ(debug=True)
    