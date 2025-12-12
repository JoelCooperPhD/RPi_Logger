import pyb
import uasyncio as asyncio
from uasyncio.event import Event
from uasyncio.lock import Lock
from time import ticks_us

class XB:
    """
    A class to manage an XBee (XB) module using AT commands.
    Handles sending and receiving messages, and retrieving the name of the XBee module.
    """
    def __init__(self, debug=False):
        self._debug = debug
        if self._debug: print(f'{ticks_us()} XB.__init__')

        self.name_NI = None

        self.ACK = False

        # Commands
        self._cmd = None
        self._message_callback = None

        # UART
        self._uart = pyb.UART(1, 921600)
        self._uart_lock = Lock()
        self._reader = asyncio.StreamReader(self._uart, {})
        self._writer = asyncio.StreamWriter(self._uart, {})

        # AT Commands
        self._AT = None
        self._AT_event = Event()
        self._AT_lock = Lock()
        self._dest_addr = None

        asyncio.create_task(self._initialize())

    ##################
    # UART
    async def _initialize(self):
        """
        Asynchronously initializes the module by creating tasks for listening for new messages,
        syncing the destination address, and getting the XBee name.
        """
        if self._debug: print(f'{ticks_us()} XB._initialize')
        
        await asyncio.sleep(1)
        asyncio.create_task(self._listen_for_new_messages())
        asyncio.create_task(self._sync_dest_addr())
        asyncio.create_task(self._get_xb_name())

    async def _listen_for_new_messages(self):
        """
        Asynchronously listens for new messages and handles them based on their API identifier.
        """
        if self._debug: print(f'{ticks_us()} XB._listen_for_new_messages')
        
        while True:
            msg = await self._reader.read(-1)
            if msg[3:4] == b'\x90':
                self._API_0x90(msg)  # Receive Packet
            elif msg[3:4] == b'\x88':
                self._API_0x88(msg)  # AT Command Response
            elif msg[3:4] == b'\x8b':
                self._API_0x8B(msg)  # Transmit Status
            else:
                print("Message not handled: {}".format(msg[3:4]))

    async def _send_AT_frame(self, cmd):
        async with self._uart_lock:
            # 7E 00 04 08 01 41 49 6C
            self._writer.write(cmd)
            await self._writer.drain()

    ##################
    # AT Commands
    async def get_AT(self, cmd):
        '''
        EA: ACK Failures
        EC: Clear Channel Faulures
        AI: Association Indication
        DH: Destitination High Address
        DL: Destination Low Address
        '''
        if self._debug: print(f'{ticks_us()} XB.get_AT')
        
        async with self._AT_lock:
            packet = self._AT_packetize(cmd)
            asyncio.create_task(self._send_AT_frame(packet))

            await self._AT_event.wait()

            self._AT_event.clear()
        return self._AT

    # ---- AT Command Response Callback
    def _API_0x88(self, arg):
        if self._debug: print(f'{ticks_us()} XB._API_0x88 {arg}')
        
        self._AT = arg[8:-1]
        self._AT_event.set()

    # ---- AT helper
    def _AT_packetize(self, cmd):
        if self._debug: print(f'{ticks_us()} XB._AT_packetize {cmd}')
        
        start = b'\x7E'  # Start byte
        typ = b'\x08'  # Frame type
        fid = b'\x01'  # Frame ID
        packet = typ + fid + cmd  # Completed packet
        csum = bytes([255 - (sum(packet) & 0xFF)])  # Checksum
        mlen = bytes([0x00, len(packet)])  # Packet Length
        return start + mlen + packet + csum

    async def _sync_dest_addr(self):
        if self._debug: print(f'{ticks_us()} XB._sync_dest_addr')
        
        while True:  # Wait until the radio has found a controller
            if b'\x00' == await asyncio.create_task(self.get_AT(b'AI')):
                DH = await asyncio.create_task(self.get_AT(b'DH'))
                DL = await asyncio.create_task(self.get_AT(b'DL'))
                self._dest_addr = DH + DL
                break
            await asyncio.sleep_ms(500)
            

    async def _get_xb_name(self):
        if self._debug: print(f'{ticks_us()} XB._get_xb_name')
        
        n = await asyncio.create_task(self.get_AT(b'NI'))
        self.name_NI = n.decode('utf-8').strip()

    ##################
    # Transmit Status
    def _API_0x8B(self, msg):
        if self._debug: print(f'{ticks_us()} XB._API_0x8B {msg}')
        
        if self._debug:
            self.ACK = False if msg[8:9] != b'\x00' else True

    ##################
    # Transmit Request
    # ----send: 0x10
    async def transmit(self, msg):
        if self._debug: print(f'{ticks_us()} XB.transmit {msg}')
        
        if self._dest_addr:
            packet = self._xmit_packetize(msg)
            asyncio.create_task(self._send_AT_frame(packet))
            await asyncio.sleep(0)

    def _xmit_packetize(self, cmd):
        if self._debug: print(f'{ticks_us()} XB._xmit_packetize {cmd}')
        
        start = b'\x7E'  # Start byte
        typ = b'\x10'  # Frame type
        fid = b'\x01'  # Frame ID
        dest_64 = self._dest_addr
        dest_16 = b'\xFF\xFE'
        br = b'\x00'
        opt = b'\x00'
        packet = typ + fid + dest_64 + dest_16 + br + opt + cmd  # Completed packet
        csum = bytes([255 - (sum(packet) & 0xFF)])  # Checksum
        mlen = bytes([0x00, len(packet)])  # Packet Length
        to_send = start + mlen + packet + csum
        return to_send

    # ---- Receive Packet Callback :0x90
    def _API_0x90(self, msg):
        if self._debug: print(f'{ticks_us()} XB._API_0x90 {msg}')
        
        try:
            self._cmd = msg[15:-1].decode('utf-8')
            self._handle_incoming_message(self._cmd)
        except UnicodeError:
            if self._debug:
                print("Xbee: Unicode Error")

    def register_incoming_message_cb(self, callback):
        if self._debug: print(f'{ticks_us()} XB.register_incoming_message_cb')
        self._message_callback = callback

    def _handle_incoming_message(self, cmd):
        if self._debug: print(f'{ticks_us()} XB._handle_incoming_message {cmd}')
        
        if self._message_callback:
            self._message_callback(cmd)