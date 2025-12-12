import pyb
from time import ticks_us


class Lenses:
    def __init__(self, broadcast=None, debug=False):
        self._debug = debug
        if self._debug: print(f'{ticks_us()} Lenses.__init__')
        
        self._broadcast_cb = broadcast
        
        # Lens controls
        self._lens_a = pyb.Pin(pyb.Pin.board.X9, pyb.Pin.OUT, value=0)
        self._lens_b = pyb.Pin(pyb.Pin.board.X10, pyb.Pin.OUT, value=0)

        # Transformer controls for legs 1 and 2
        self._flip_flop = True
        self._pwm_vals = [0.0, 100.0]
        self._pwm_vals[self._flip_flop]

        tim = pyb.Timer(3, freq=1000)
        self._toggle_1 = tim.channel(1, pyb.Timer.PWM, pin=pyb.Pin('Y3'))
        self._toggle_1.pulse_width_percent(self._pwm_vals[0])

        tim = pyb.Timer(3, freq=1000)
        self._toggle_2 = tim.channel(2, pyb.Timer.PWM, pin=pyb.Pin('Y4'))
        self._toggle_2.pulse_width_percent(self._pwm_vals[1])

        # Transformer toggle timer - toggles each leg at a set interval
        self._toggle_timer = pyb.Timer(4, freq=120)
        self._toggle_timer.callback(self._toggle_xformer)

    def _toggle_xformer(self, tmr):
        # if self._debug: print(f'{ticks_us()} Lenses._toggle_xformer')
        # This is a timer based callback from timer 4
        self._toggle_1.pulse_width_percent(self._pwm_vals[self._flip_flop])
        self._toggle_2.pulse_width_percent(self._pwm_vals[not self._flip_flop])
        self._flip_flop = not self._flip_flop

    # Lens opacity when switch on via "clear" method
    @property
    def on_opacity(self):
        if self._debug: print(f'{ticks_us()} Lenses.on_opacity getter')
        
        return self._pwm_vals[1]

    @on_opacity.setter
    def on_opacity(self, val):
        if self._debug: print(f'{ticks_us()} Lenses.on_opacity setter {val}')
        
        if val > 100:
            val = 100
        self._pwm_vals[1] = val

    # Lens opacity when switch off via "opaque" method
    @property
    def off_opacity(self):
        if self._debug: print(f'{ticks_us()} Lenses.off_opacity getter')
        
        return self._pwm_vals[0]

    @off_opacity.setter
    def off_opacity(self, val):
        if self._debug: print(f'{ticks_us()} Lenses.on_opacity setter {val}')
        
        if val < 0:
            val = 0
        self._pwm_vals[0] = val

    ###################################################
    # Lens control
    def _clear(self, lenses=['a', 'b']):
        if self._debug: print(f'{ticks_us()} Lenses._clear {lenses}')
        
        if 'x' in lenses:
            lenses = ['a', 'b']
        if 'a' in lenses:
            self._lens_a.value(1)
        if 'b' in lenses:
            self._lens_b.value(1)
        return True

    def _opaque(self, lenses=['a', 'b']):
        if self._debug: print(f'{ticks_us()} Lenses._opaque {lenses}')
        
        self._toggle_timer.callback(None)
        if 'x' in lenses:
            lenses = ['a', 'b']
        if 'a' in lenses:
            self._lens_a.value(0)
        if 'b' in lenses:
            self._lens_b.value(0)

        self._toggle_timer.callback(self._toggle_xformer)
        return False
        
    def update_lens(self, lens, state):
        if self._debug: print(f'{ticks_us()} Lenses.update_lens {lens} {state}')

        if state:
            self._clear(lens)
            if self._broadcast_cb: self._broadcast_cb('stm>1')
        else:
            self._opaque(lens)
            if self._broadcast_cb: self._broadcast_cb('stm>0')