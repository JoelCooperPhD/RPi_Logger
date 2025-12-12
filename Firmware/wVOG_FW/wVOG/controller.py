import uasyncio as asyncio
from wVOG import xb, config, lenses, battery, mmc, experiments, timers
from pyb import RTC, USB_VCP, Pin, LED
from time import time, sleep, ticks_us

cfg_template = {"clr": "100", "cls": "1500", "dbc": "20", "srt": "1", "opn": "1500", "dta": "0", "drk": "0", "typ": "cycle"}

class WirelessVOG:
    """
    Class to manage and coordinate the various components of the Wireless Visual Occlusion Glasses (VOG) system.

    Attributes:
        lenses: Instance of the Lenses class for controlling the lens states.
        battery: Instance of the LipoReader class for reading battery data.
        xb: Instance of the XB class for wireless communication.
        headers: String that defines the headers for data saved to the MMC.
        mmc: Instance of the MMC class for managing data storage.
        rtc: Instance of the RTC class for real-time clock functionalities.
        utc: The current time in UTC. 
        cfg: Instance of the Configurator class for managing the device configuration.
        exp: Instance for managing the currently running experiments.
        exp_running: Boolean flag to indicate if an experiment is currently running.
        trial_running: Boolean flag to indicate if a trial is currently running.

    The class also initializes tasks for handling incoming serial messages.
    """
    def __init__(self, debug=False):
        self._debug = debug
        if self._debug: print(f'{ticks_us()} WirelessVOG.__init__')

        # Lenses
        self.lenses = lenses.Lenses(self.broadcast)

        # Battery
        self.battery = battery.LipoReader()
        
        # XB
        self.xb = xb.XB()
        self.xb.register_incoming_message_cb(self.parse_cmd)

        # MMC Save - The flash module stuck to the bottom of the unit
        self.headers = 'Device ID,Label,Unix time in UTC,Trial Number,Shutter Open,Shutter Closed,Shutter Total,' \
                         'Transition 0 1 or X,Battery SOC,Device Unix time in UTC\n'
        self.mmc = mmc.MMC()

        # Realtime Clock
        self.rtc = RTC()
        self.utc = None

        # Config
        self.cfg = config.Configurator('wVOG/config.jsn')
        self.verify_cfg()

        # Experiments
        self.exp_running = False
        self.exp = None

        # Trial
        self.trial_running = False
        
        asyncio.create_task(self.handle_serial_msg())
        
    async def handle_serial_msg(self):
        """
        Asynchronous method that continually checks for incoming messages 
        over the USB serial connection and passes them to the command parser.
        """
        if self._debug: print(f'{ticks_us()} WirlessVOG.handle_serial_msg')
        
        while True:
            if USB_VCP().any():
                msg = USB_VCP().read()
                msg = msg.strip().decode('utf-8')
                
                self.parse_cmd(msg)
            await asyncio.sleep(.01)

    def parse_cmd(self, msg):
        """
        Method to parse incoming messages and route them to the appropriate handler.
        Messages are expected in the format '<command><value>' and are split on the '>'.
        """
        if self._debug: print(f'{ticks_us()} WirlessVOG.parse_cmd got:{msg}')
        
        if ">" in msg:
            cmd, val = msg.split(">")
        else:
            cmd, val = msg, ''

        # Lenses: a, b, or x = both
        if cmd in ['a', 'b', 'x']:
            self.lenses.update_lens(cmd, int(val))

        # Experiment / Trial
        elif cmd in ['exp', 'trl']:
            if cmd == 'exp' and val == '1':
                self.exp = None # Clear any prior experiments
                if self.mmc.mmc_present:
                    self.mmc.init(self.headers)
                self.exp = experiments.create_vog(self.cfg.config, self.broadcast)
                 
            if self.exp:
                self.exp.handle_exp_msg(cmd, val)

        # Configuration
        elif cmd == 'cfg':
            self.get_full_configuration()
        elif cmd == 'set':
            self.update_config(val)

        elif cmd == 'rtc':
            self.update_rtc(val)
        elif cmd == 'bat':
            self.get_battery()

        else:
            self.broadcast("Unknown command")
            
    def get_full_configuration(self):
        """
        Method to send the full configuration settings to the recipient. 
        """
        if self._debug: print(f'{ticks_us()} WirlessVOG.get_full_configuration')
        
        cfg_str = self.cfg.get_config_str()
        
        self.broadcast(f'cfg>{cfg_str}')

    def update_config(self, val):
        """
        Method to update the configuration settings. Receives a string of key-value pairs separated by ','.
        
        The configuration options are as follows:
            opn: The time (in ms) that the lenses remain in the open or clear state.
            cls: The time (in ms) that the lenses remain in the closed or opaque state.
            dbc: The time (in ms) to debounce the switch.
            typ: The type of experiment. Options are 'cycle', 'peek', 'eblind', 'direct'.
            dta: Whether data are sent at each lens cycle or at the end of a trial.
            srt: The lens state for the first cycling, either clear or opaque.
            drk: The opacity value (between 0-100) of the lenses when in the opaque state.
            clr: The opacity value (between 0-100) of the lenses when in the clear state.

        Each configuration option is sent as a string in the form of 'key,value' where the key is 
        the configuration option and the value is the new setting for that option. Multiple configuration 
        updates can be sent at once by separating each 'key,value' pair with a comma.
        """
        
        if self._debug: print(f'{ticks_us()} WirlessVOG.update_config got:{val}')

        if val != '':
            kvs = val.split(',')
            for kv in kvs:
                self.cfg.update(kv)
            cfg_str = self.cfg.get_config_str()
            
            self.broadcast(f'cfg>{cfg_str}')
            
    def update_rtc(self, dt):
        """
        Method to update the real-time clock (RTC) with a given datetime.
        """
        if self._debug: print(f'{ticks_us()} WirlessVOG.update_rtc got:{dt}')
        
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

    def verify_cfg(self):
        """
        Method to check if the configuration matches the template. 
        If not, it updates the configuration to match the template.
        """
        if self._debug: print(f'{ticks_us()} WirlessVOG.verify_cfg')
        
        if len(cfg_template) != len(self.cfg.config):
            self.cfg.update(cfg_template)
        for key in self.cfg.config:
            if self.cfg.config[key] == "":
                self.cfg.update(cfg_template)
                break
            
    def broadcast(self, msg):
        """
        Method to broadcast a message to all recipients.
        """
        if self._debug: print(f'{ticks_us()} WirlessVOG.broadcast got:{msg}')
        
        if msg.startswith('dta>'):
            msg = f'{msg},{self.battery.percent()},{time() + 946684800}\n'
            m = f"{self.xb.name_NI},,,{msg.strip('dta>')}"
            self.mmc.write(m)
        else:
            msg = f"{msg}\n"
        asyncio.create_task(self.xb.transmit(msg))
        USB_VCP().write(msg)
