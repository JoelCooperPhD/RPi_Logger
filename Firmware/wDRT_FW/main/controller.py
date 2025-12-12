from uasyncio import gather, sleep, create_task
from pyb import RTC, USB_VCP, Pin, LED
from time import time, ticks_us

from main.hardware import  battery, mmc, xb
from main.utilities import config, timers


class RSDeviceController:
    """
    Class to manage and coordinate a non specific RS Device.

    The class also initializes tasks for handling incoming serial messages.
    """
    def __init__(self, device, debug=False):
        self._debug = debug
        if self._debug: print(f'{ticks_us()} RSDeviceController.__init__')

        # This is the specific instance of the RS device
        self.device = device(self.broadcast)

        # Battery
        self.battery = battery.LipoReader()
        
        # XB
        self.xb = xb.XB()
        self.xb.register_incoming_message_cb(self.parse_cmd)

        # MMC Save - The flash module stuck to the bottom of the unit
        self.headers = device.HEADERS
        
        self.mmc = mmc.MMC()

        # Realtime Clock
        self.rtc = RTC()
        self.utc = None

        # Trial
        self.trial_running = False
        
    async def run_controller(self):
        await gather(self._handle_serial_com())
        
    async def _handle_serial_com(self):
        """
        Asynchronous method that continually checks for incoming messages 
        over the USB serial connection and passes them to the command parser.
        """
        if self._debug: print(f'{ticks_us()} RSDeviceController._handle_serial_com')
        
        while True:
            if USB_VCP().any():
                msg = USB_VCP().read()
                msg = msg.strip().decode('utf-8')
                
                self.parse_cmd(msg)
            await sleep(.01)

    def parse_cmd(self, msg):
        """
        Method to parse incoming messages and route them to the appropriate handler.
        Messages are expected in the format '<command><value>' and are split on the '>'.
        """
        if self._debug: print(f'{ticks_us()} RSDeviceController.parse_cmd got:{msg}')
        try:
            if ">" in msg:
                cmd, val = msg.split(">")
            else:
                cmd, val = msg, ''

            # Experiment / Trial
            if cmd in ['dev', 'exp', 'trl']:
                if cmd == 'trl' and val == '1':
                    if self.mmc.mmc_present:
                        self.mmc.init(self.headers)
                self.device.handle_msg(cmd, val)

            # Configuration
            elif cmd == 'get_cfg':
                self.get_full_configuration()
            elif cmd == 'set':
                self.update_config(val)

            elif cmd == 'set_rtc':
                self.update_rtc(val)
            elif cmd == 'get_bat':
                self.get_battery()

        except ValueError as e:
            if self._debug: print(f'{ticks_us()} RSDeviceController.parse_cmd (e)')
            
    def get_full_configuration(self):
        """
        Method to send the full configuration settings to the recipient. 
        """
        if self._debug: print(f'{ticks_us()} RSDeviceController.get_full_configuration')
        
        cfg_str = self.device.configurator.get_config_str()
        self.broadcast(f'cfg>{cfg_str}')

    def update_config(self, val):
        """
        Method to update the configuration settings. Receives a string of key-value pairs separated by ','.  
        """
        
        if self._debug: print(f'{ticks_us()} RSDeviceController.update_config got:{val}')

        if val != '':
            kvs = val.split(',')
            for kv in kvs:
                self.device.configurator.update(kv)
                if 'SPCT' in kv:
                    self.device._stimulus.intensity = int(kv.split(':')[1])
            cfg_str = self.device.configurator.get_config_str()
            
            self.broadcast(f'cfg>{cfg_str}')
            
    def update_rtc(self, dt):
        """
        Method to update the real-time clock (RTC) with a given datetime.
        """
        if self._debug: print(f'{ticks_us()} RSDeviceController.update_rtc got:{dt}')
        
        if dt != '':
            rtc_tuple = tuple([int(i) for i in dt.split(',')])
            self.rtc.datetime(rtc_tuple)

        r = self.rtc.datetime()
        self.broadcast(f"rtc>{(',').join([str(v) for v in r])}")

    def get_battery(self):
        """
        Method to broadcast the current battery state of charge.
        """
        self.broadcast(f'bty>{self.battery.percent()}')
            
    def broadcast(self, msg):
        """
        Method to broadcast a message to all recipients.
        """
        if self._debug: print(f'{ticks_us()} RSDeviceController.broadcast got:{msg}')
        
        if msg.startswith('dta>'):
            msg = f'{msg},{self.battery.percent()},{time() + 946684800}\n'
            m = f"{self.xb.name_NI},,,{msg.strip('dta>')}"
            if self.mmc.mmc_present:
                self.mmc.write(m)
        else:
            msg = f"{msg}\n"
        create_task(self.xb.transmit(msg))
        USB_VCP().write(msg)
