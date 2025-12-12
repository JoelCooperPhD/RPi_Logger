from pyb import RTC, MMCard
import os
import micropython
from uasyncio import create_task, sleep
from pyb import usb_mode
from time import ticks_us

micropython.alloc_emergency_exception_buf(100)


class MMC:
    """
    A class that interfaces with the solid state memory attached to the botton of the pyboard using an MMCard object.

    Attributes:
        mmc (MMCard): An instance of the MMCard class used to interface with the memory card.
        mmc_present (bool): A flag indicating whether the memory card is present.
        filename (str): The name of the file to write data to.
        rtc (RTC): An instance of the RTC class used to get the current date and time.
    """

    def __init__(self, debug=False):
        """
        Initializes the MMC class and checks if the memory card is present.
        """
        self._debug = debug
        if self._debug: print(f'{ticks_us()} MMC.__init__')

        self.mmc = MMCard()
        self.mmc_present = False

        self.filename = None

        # Check if the USB device is in mass storage device mode and power on the memory card if available
        if 'MSC' in usb_mode():
            self.mmc.power(1)

            # Check if the memory card is present
            if self.mmc.info():
                self.rtc = RTC()
                # Start a coroutine to mount the memory card
                create_task(self.mount_mmc())
                self.mmc_present = True

    async def mount_mmc(self):
        """
        Coroutine that mounts the memory card.
        """
        if self._debug: print(f'{ticks_us()} MMC.mount_mmc')

        while True:
            if self.mmc.info():
                break
            await sleep(1)
        try:
            os.mount(self.mmc, '/mmc')
            self.mmc_present = True

        except Exception as e:
            print(f'MMC Error: {e}')
            # from utilities import mmc_format
            # mmc_format.mmc_format()

    def init(self, header):
        """
        Initializes a new file to write data to.

        Args:
            header (str): The header text to write to the file.
        """
        if self._debug: print(f'{ticks_us()} MMC.init')

        if self.mmc_present:
            max_version = "0"
            rtc = self.rtc.datetime()
            date_str = "{}-{}-{}".format(rtc[0], rtc[1], rtc[2])

            # Check for existing files and get the highest version number
            for file in os.listdir('/mmc'):
                key_value = file.split("_")
                if key_value[0].isdigit() and int(key_value[0]) >= int(max_version):
                    max_version = str(int(key_value[0]) + 1)

            # Create a filename with the highest version number and current date
            self.filename = "/mmc/{}_{}.txt".format(max_version, date_str)

            # Write the header to the file
            with open(self.filename, 'w') as outfile:
                outfile.write(header)

    def write(self, data):
        """
        Writes data to the file specified by the filename attribute.

        Args:
            data (str): The data to write to the file.
        """
        if self._debug: print(f'{ticks_us()} MMC.write:{data}')

        if self.mmc_present:
            if self.filename:
                with open(self.filename, 'a') as outfile:
                    outfile.write(data)
            else:
                print(f'filename is None')

