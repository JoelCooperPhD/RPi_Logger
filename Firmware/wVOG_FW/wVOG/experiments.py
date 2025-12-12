import uasyncio as asyncio
from pyb import Pin, USB_VCP
from wVOG import lenses, timers, xb, switch
from time import ticks_us, ticks_ms, ticks_diff, sleep


class BaseVOG:
    """
    The BaseVOG class provides base functionality for a variety of virtual occlusion glasses (VOGs).

    Args:
        config (dict): The configuration dictionary containing all required parameters for the experiment.
        broadcast (callable): A function or method that broadcasts a message.
        debug (bool, optional): A flag indicating whether debug mode is enabled. Defaults to False.
    """
    def __init__(self, config, broadcast, debug=False):
        self._debug = debug
        if self._debug: print(f'{ticks_us()} BaseVOG.__init__')
        
        self._cfg = config
        self._broadcast = broadcast

        # Lenses
        self._lens_is_clear = False
        self._time_since_last_change = 0
        self._lenses = lenses.Lenses(broadcast)

        # Switches
        self.switch = switch.DebouncedSwitch()
        self.switch.debounce_ms = int(self._cfg['dbc'])
        self.switch.set_open_closed_callback(self._handle_valid_response)
        asyncio.create_task(self.switch.update())

        # Toggle Timer
        self._ab_timer = timers.ABTimeAccumulator()

        # Experiment
        self.exp_running = False
        self._exp_task = None

        # Trial
        self._trial_n = 0
        self._trial_running = False
        self._request_peek = False
        
        self._first_peek = True

    # Public Methods
    def handle_exp_msg(self, action, value):
        if self._debug: print(f'{ticks_us} BaseVOG.handle_exp_msg {action} {value}')
        """
        Update the experiment state based on the given action and value.

        Args:
            action (str): The action to be performed, either "exp" for experiment or "trl" for trial.
            value (str): The value associated with the action, either "1" for start or "0" for stop.
        """
        if self._debug: print(f'{ticks_us()} BaseVOG.handle_exp_msg')
    
        if action == "exp":
            if value == "1":
                self.begin_experiment()
            elif value == "0":
                self.end_experiment()
        elif action == "trl":
            if value == "1":
                self.begin_trial()
            elif value == "0":
                self.end_trial()
    
    def begin_experiment(self):
        if self._debug: print(f'{ticks_us()} BaseVOG.begin_experiment')
        
        if not self.exp_running:
            self.exp_running = True
            
            self._broadcast('exp>1')
            self._trial_n = 0
            self._exp_task = asyncio.create_task(self._exp_loop())
        
    def end_experiment(self):
        if self._debug: print(f'{ticks_us()} BaseVOG.end_experiment')
        
        if self.exp_running:
            self.exp_running = False
            
            self._broadcast('exp>0')
            self._exp_task.cancel()
        
    def begin_trial(self):
        if self._debug: print(f'{ticks_us()} BaseVOG.begin_trial')
        
        
        if not self._trial_running:
            self._trial_running = True
            
            self._lens_is_clear = not int(self._cfg['srt'])
            self._broadcast('trl>1')
            self._trial_n += 1
            self._first_peek = True

    def end_trial(self):
        if self._debug: print(f'{ticks_us()} BaseVOG.end_trial')
        
        if self._trial_running:
            self._trial_running = False
            
            results = self._ab_timer.stop()
            self._broadcast('trl>0')
            self._lenses.update_lens('x', 0)
            print('end')
            self._lens_is_clear = False
            
            results_string = ','.join(map(str, results))
            self._broadcast(f'dta>{self._trial_n},{results_string}')

    def _handle_valid_response(self, now_state, triggered_ms, down_cnt, up_cnt):
        """
        This method should be overridden by each experiment type to handle a valid response.
        """
        pass
    
    # Main Experiment Loop
    async def _exp_loop(self):
        if self._debug: print(f'{ticks_us()} BaseVOG._exp_loop')

        open_ms = int(self._cfg['opn']) # Dictionary lookups are slow. These transfere the value to a variable
        close_ms = int(self._cfg['cls'])
        state_change_delta = 0 # The ms time stamp when the lenses last changed.
        last_change_time = 0 # The number of ms elapsed since the lenses toggled.
        toggle_flag = False # Changed to true when one of the conditions for changing the lenses is met
        
        while True:
            # This loop starts when trial_running is set to true
            if self._trial_running:
                time_now = ticks_ms()
                state_change_delta =  ticks_diff(time_now, last_change_time)

                # Run this code if first pass through it cause the lenses to start out either clear or opaque
                if not self._ab_timer.running:
                    toggle_flag = True
                    times = self._ab_timer.start(time_now, start_open = not int(self._cfg['srt']))
                
                # Check if lenses should toggle
                if not toggle_flag:
                    if self._lens_is_clear:
                        toggle_flag = self._should_lens_turn_opaque(state_change_delta, open_ms)
                    else:
                        toggle_flag = self._should_lens_turn_clear(state_change_delta, close_ms)
                
                if toggle_flag:
                    toggle_flag = False
                    self._toggle_lenses(time_now)
                    last_change_time = time_now
                    
            await asyncio.sleep(0)
            if self._debug: await asyncio.sleep(1)
    
    def _should_lens_turn_opaque(self, delta, open_ms):
        if self._debug: print(f'{ticks_us()} BaseVOG._should_lens_turn_opaque {delta} {open_ms}')
        
        return True if delta >= open_ms else False
    
    def _should_lens_turn_clear(self, delta, close_ms):
        if self._debug: print(f'{ticks_us()} BaseVOG._should_lens_turn_clear {delta} {open_ms}')
        
        return True if delta >= close_ms else False
    
    def _toggle_lenses(self, now_ms, results=None):
        if self._debug: print(f'{ticks_us()} BaseVOG._toggle_lenses')
        self._lens_is_clear = not self._lens_is_clear
        self._lenses.update_lens('x', self._lens_is_clear)
        if not results:
            results = self._ab_timer.toggle(now_ms)
        
        # If dta is set to 1 then send data at each lens toggle
        if int(self._cfg['dta']):
            results_string = ','.join(map(str, results))
            self._broadcast(f'dta>{self._trial_n},{results_string}')


class PeekVOG(BaseVOG):
    """
    The PeekVOG class represents a type of VOG experiment. This experiment provides a peek with lockout. If open
    and closed times are set to 1500 and peeks are repeatedly requested then they will perform similar to the
    NHTSA Visual Manual Distraction Guidelines testing or ISO 16673. However, participants chose when to get a peek
    and thus this testing method can be used to evaluate displays where the primary interaction modality may be
    auditory vocal with occasional peeks requested to confirm the system performance. Cred Greg Fitch with the idea.

    Args:
        config (dict): The configuration dictionary containing all required parameters for the experiment.
        broadcast (callable): A function or method that broadcasts a message.
    """
    def __init__(self, config, broadcast, debug=False):
        self._debug = debug
        if self._debug: print(f'{ticks_us()} PeekVOG.__init__')
        
        super().__init__(config, broadcast, debug=debug)
        self._request_peek = False

    def _handle_valid_response(self, now_state, triggered_ms, down_cnt, up_cnt):
        if self._debug: print(f'{ticks_us()} PeekVOG._handle_valid_response')
        
        if now_state == 0: # If the switch is down
            if self.exp_running & self._trial_running:
                self._request_peek = True
    
    def _should_lens_turn_clear(self, state_change_delta, close_ms):
        if self._debug: print(f'{ticks_us()} PeekVOG._should_lens_turn_clear')

        if state_change_delta >= close_ms or self._first_peek:            
            if self._request_peek:
                self._request_peek = False
                self._first_peek = False
                return True
        return False


class EBlindfoldVOG(BaseVOG):
    """
    The EBlindfold class represents a type of VOG experiment. This experiment begins with the glasses clear.
    Participants are instructed to identify a target in the visual field as quickly as possible. When they do,
    they press the response button and the glasses immediately go opaque and the total shutter open time is recorded
    to a file and saved for analysis.

    Args:
        config (dict): The configuration dictionary containing all required parameters for the experiment.
        broadcast (callable): A function or method that broadcasts a message.
    """
    def __init__(self, config, broadcast, debug=False):
        super().__init__(config, broadcast)
    
    def _handle_valid_response(self, now_state, triggered_ms, down_cnt, up_cnt):
        """
        Overrides the method from BaseVOG to handle a valid response in the context of the EBlindfold experiment.
        """
        if self._debug: print(f'{ticks_us()} EBlindfold._handle_valid_response')
        if self.exp_running & self._trial_running:
            self.end_trial()


class CycleVOG(BaseVOG):
    """
    The CycleVOG class represents a type of VOG experiment. This experiment cycles the glasses from clear to opaque at
    prespecified intervals. Examples include NHTSA Visual Manual Distraction Guidelines testing and ISO 16673

    Args:
        config (dict): The configuration dictionary containing all required parameters for the experiment.
        broadcast (callable): A function or method that broadcasts a message.
    """
    def __init__(self, config, broadcast, debug=False):
        super().__init__(config, broadcast)

    def _handle_valid_response(self, now_state, triggered_ms, down_cnt, up_cnt):
        if self._debug: print(f'{ticks_us()} CycleVOG._handle_valid_response')
        if now == 1:
            if self.exp_running:
                if self._trial_running:
                    self.end_trial()
                else:
                    self.begin_trial()


class DirectVOG():
    """
    The DirectVOG class makes it possible to directly control the state of the glasses over the button port. This
    can be useful if control is desired from a third party piece of hardware.

    Args:
        config (dict): The configuration dictionary containing all required parameters for the experiment.
        broadcast (callable): A function or method that broadcasts a message.
    """
    def __init__(self, config, broadcast, debug=False):
        self._lenses = lenses.Lenses()
        self._switch = switch.DebouncedSwitch()
        self._switch.set_open_closed_callback(self._handle_valid_response)
        
    def run(self):
        await asyncio.create_task(self._switch.update())   

    def _handle_valid_response(self, now_state, triggered_ms, down_cnt, up_cnt):
        if self._debug: print(f'{ticks_us()} DirectVOG._handle_valid_response')
        if state == 1:
            self._lenses.update_lens('x', 1)
        elif state == 0:
            self._lenses.update_lens('x', 0)


def create_vog(config: dict, broadcast, debug=False):
    """
    Factory function to create a specific VOG experiment type based on the given configuration.

    Args:
        config (dict): The configuration dictionary containing all required parameters for the experiment.
        broadcast (callable): A function or method that broadcasts a message.
        debug (bool, optional): A flag indicating whether debug mode is enabled. Defaults to False.

    Returns:
        BaseVOG: A VOG experiment object of the type specified in the configuration.

    Raises:
        ValueError: If the "typ" value in the configuration is not a recognized VOG type.
    """
    if debug: print(f'{ticks_us()} experiments.create_vog')
    
    vog_type = config["typ"]
    if vog_type == "direct":
        return DirectVOG(config, broadcast)
    elif vog_type == "cycle":
        return CycleVOG(config, broadcast)
    elif vog_type == "peek":
        return PeekVOG(config, broadcast)
    elif vog_type == "eBlindfold":
        return EBlindfoldVOG(config, broadcast)
    else:
        raise ValueError(f"Unknown VOG type: {vog_type}")