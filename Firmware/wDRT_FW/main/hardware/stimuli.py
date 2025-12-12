from pyb import Timer, Pin, LED
from time import sleep, ticks_us
from uasyncio import sleep_ms, run

class Stimulus:
    """
    A class used to control the PWM (Pulse Width Modulation) output of a pin.
    """
    def __init__(self, pin='Y4', intensity=100, debug=False):
        """
        Initialize the Stimulus class.

        Args:
            pin (str): The pin to control. Default is 'Y4'.
            intensity (int): The initial PWM intensity. Default is 100.
            debug (bool): Enable or disable debug output. Default is False.
        """
        self._debug = debug
        self._intensity = intensity
        self._stm = Timer(3, freq=1000).channel(2, Timer.PWM, pin=Pin(pin))
        self._stm.pulse_width_percent(0)
        if self._debug: print(f'Stimulus.__init__ pin:{pin} intensity:{intensity}')

    @property
    def intensity(self):
        """
        Gets the current intensity.
        """
        return self._intensity

    @intensity.setter
    def intensity(self, val):
        """
        Sets the PWM intensity within the range 0-100.

        Args:
            val (int): The new intensity.
        """
        if val > 100:
            val = 100
        elif val < 0:
            val = 0
        self._intensity = val
        if self._debug: print(f'Stimulus.intensity:{val}')

    def on(self):
        """
        Turns on the PWM with the current intensity.
        """
        self._stm.pulse_width_percent(self._intensity)
        if self._debug: print(f'Stimulus.on intensity:{self._intensity}')
        return ticks_us()

    def off(self):
        """
        Turns off the PWM.
        """
        self._stm.pulse_width_percent(0)
        if self._debug: print('Stimulus.off')
        return ticks_us()
    
    def fade(self):
        """
        Gradually decrease the intensity of the PWM from 100 to 0.
        """
        for i in range(100, -1, -1):
            self._stm.pulse_width_percent(i)
            if self._debug: print(f'Stimulus.fade intensity:{i}')
            sleep(.015)
    
    def pulse(self, times: int=6):
        """
        Pulse the PWM a specific number of times.

        Args:
            times (int): The number of pulses. Default is 6.
        """
        for i in range(times):
            self._stm.pulse_width_percent(self._intensity)
            sleep(.125)
            self._stm.pulse_width_percent(0)
            sleep(.05)
            if self._debug: print(f'Stimulus.pulse count:{i+1}')
            
if __name__ == '__main__':
    debug = True
    s = Stimulus(debug=debug)
    if debug:
        s.on()
        sleep(1)
        s.off()
        sleep(1)
        s.pulse()
        sleep(1)
        s.fade()
