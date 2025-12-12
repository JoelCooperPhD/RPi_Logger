from pyb import ADC, Pin
from micropython import const
from array import array
import uasyncio as asyncio
from time import ticks_ms, ticks_diff, ticks_us


class LipoReader:
    """
    Class to handle the reading of the voltage and percentage of a Lipo battery. 
    It uses an ADC (Analog-to-Digital Converter) pin to read the battery level.
    """
    def __init__(self, pin='X8', debug=False):
        """
        Initializes the LipoReader with the specified ADC pin and debug mode.
        
        Args:
            pin (str): The ADC pin to be used for reading the battery level. Defaults to 'X8'.
            debug (bool): If True, debug information is printed. Defaults to False.
        """
        self._debug = debug
        if self._debug: print(f'{ticks_us()} LipoReader.__init__')
        
        self._bat_pin = ADC(Pin(pin))

        self._vref = 3.3
        self._vcut = 3.3
        self._vmax = 4.00
        self._max_adc = 4000

    # vref: Voltage reference for adjustments to the voltage reading as the battery is drained
    @property
    def vref(self):
        """
        The voltage reference for adjustments to the voltage reading as the battery is drained.

        Gets or sets the voltage reference.
        """
        return self._vref

    @vref.setter
    def vref(self, val):
        self._vref = val

    # vcut: Voltage cutoff when the battery is completely drained
    @property
    def vcut(self):
        """
        The voltage cutoff when the battery is completely drained.

        Gets or sets the voltage cutoff.
        """
        return self._vcut

    @vcut.setter
    def vcut(self, val):
        self._vcut = val

    # max: Maximum ADC Reading when the battery is fully charged
    @property
    def max_adc(self):
        """
        The maximum ADC Reading when the battery is fully charged.

        Gets or sets the maximum ADC reading.
        """
        return self._max_adc

    @max_adc.setter
    def max_adc(self, val):
        self._max_adc = val

    ######################
    # Main Methods

    def percent(self):
        """
        Calculates the current battery level as a percentage.

        Returns:
            int: The battery level as a percentage. 
        """
        if self._debug: print(f'{ticks_us()} LipoReader.percent')
        
        prct = round(((self.voltage() - self._vcut) / (self._vmax - self._vcut)) * 100)
        if prct > 100:
            prct = 100
        elif prct < 0:
            prct = 0
        return prct

    def voltage(self):
        """
        Calculates the current battery voltage. 

        Returns:
            float: The current battery voltage.
        """
        if self._debug: print(f'{ticks_us()} LipoReader.voltage')
        
        pin_val = sum([self._bat_pin.read() for i in range(50)]) / 50
        return ((pin_val / self._max_adc) * self._vref) * 1.24
