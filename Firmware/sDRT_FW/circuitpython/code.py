import time
import board
import digitalio
import pwmio
import supervisor
import random
import gc
gc.collect()

###################################################################
###################################################################
# Constants
DEBOUNCE_MILLIS = 50
PORT_ON_TIME = 0.0005

# STRING DICTIONARY
lowerISI  ='lowerISI'
upperISI  ='upperISI'
stimDur   ='stimDur'
intensity ='intensity'
name      ='name'
buildDate ='buildDate'
version   ='version'
config    ='config'
exception ='exception'
newline = '\n'

cfg_       ='cfg>'
trl_       ='trl>'
clk_       ='clk>'
end_       ='end>'
stm_1      ='stm>1'
stm_0      ='stm>0'

get_      ='get_'
set_      ='set_'
exp_      ='exp_'
stm_      ='stim_'


start     ='start'
stop      ='stop'
on        ='on'
off       ='off'

space     =' '
period    ='.'
comma     =','
colon     =':'
unknown   ='unknown'

txt       ='txt'
###################################################################
###################################################################

import adafruit_dotstar

# DOTSTAR
dotstar = adafruit_dotstar.DotStar(board.APA102_SCK, board.APA102_MOSI, 1)
dotstar.brightness=0.3
dotstar[0] = (0, 0, 255)

# dotstar[0] = (255, 0, 0) # red
# dotstar[0] = (0, 255, 0) # green
# dotstar[0] = (0, 0, 255) # blue
# dotstar[0] = (0, 0, 0) # off

# RESPONSE
last_response = float()
response = digitalio.DigitalInOut(board.D0)
response.pull = digitalio.Pull.UP

response_port = digitalio.DigitalInOut(board.D1)
response_port.direction = digitalio.Direction.OUTPUT
response_port.value = True

resp_now = int(time.monotonic() * 1000)
resp_then = resp_now

# STIMULUS
stimulus = pwmio.PWMOut(board.D3, frequency=500, duty_cycle=0)

stimulus_port = digitalio.DigitalInOut(board.D2)
stimulus_port.direction = digitalio.Direction.OUTPUT
stimulus_port.value = True

###################################################################
###################################################################
# CONFIG
cfg = {lowerISI : 3000, upperISI : 5000, stimDur: 1000, intensity: 255, name: 'sDRT', buildDate: '2/23/2022', version: '1.2'}

def read_cfg():
    with open(config+period+txt, 'r') as infile:
        for line in infile:
            kv = line.split(colon)
            if len(kv) == 2:
                cfg[kv[0]]  = int(kv[1])

def update_cfg(kv):
    if len(kv) == 2:
        key, val = kv[0][4:], kv[1]
        cfg[key] = int(val)

        to_write = (lowerISI + colon + str(cfg[lowerISI]) + newline
                    + upperISI + colon + str(cfg[upperISI]) + newline
                    + stimDur  + colon + str(cfg[stimDur])  + newline
                    + intensity+ colon + str(cfg[intensity]))

        with open(config+period+txt, 'w') as file:
            file.write(to_write)

        print(cfg_ + key + colon + str(cfg[key]))
    else:
        print(unknown + colon + kv)


###################################################################
###################################################################
# MESSAGE HANDLING
def parse_msg(msg):
    try:
        kv = msg.split(' ')

        if config  in msg: get_config()
        elif get_  in msg: print(cfg_ + kv[0] + colon + str(cfg[msg[4:]]))
        elif set_  in msg: update_cfg(kv)
        elif start in msg: begin()
        elif stop  in msg: end()
        elif on    in msg:
            stimulus.duty_cycle = int((cfg[intensity] *  65535) / 255)
            print(stm_1)
        elif off   in msg:
            stimulus.duty_cycle = 0
            print(stm_0)
        else:
            print(unknown)
    except Exception as e:
        print(e)
    gc.collect()

def get_config():
    print(cfg_
          + name      + colon + cfg[name]           + comma
          + buildDate + colon + cfg[buildDate]      + comma
          + version   + colon + cfg[version]        + comma
          + lowerISI  + colon + str(cfg[lowerISI])  + comma
          + upperISI  + colon + str(cfg[upperISI])  + comma
          + stimDur   + colon + str(cfg[stimDur])   + comma
          + intensity + colon + str(cfg[intensity])
    )


###################################################################
###################################################################
# EXPERIMENT
responded = False
exp_running = False

trial_counter = 0
reaction_time = 0
click_count = 0

time_now = float()
exp_start_time = float()
trial_start_time = float()

stim_cutoff_time = float()
trial_cutoff_time = float()

def begin():
    global exp_start_time, trial_counter, exp_running
    exp_running = True
    trial_counter = 0
    dotstar[0] = (0, 0, 0)
    exp_start_time = int(time.monotonic() * 1000)
    time.sleep(4)
    next_trial()

def next_trial():
    global trial_counter, trial_start_time, trial_counter, reaction_time, click_count, responded, stim_cutoff_time, trial_cutoff_time
    time_now = int(time.monotonic() * 1000)
    stimulus.duty_cycle = int((cfg[intensity] *  65535) / 255)
    dotstar[0] = (255,0,0)
    print(end_)
    print(stm_1)
    trial_start_time = time_now

    stimulus_port.value = 0
    time.sleep(PORT_ON_TIME)
    stimulus_port.value = 1

    trial_counter += 1
    reaction_time = -1
    click_count = 0
    responded = False

    stim_cutoff_time = time_now + cfg[stimDur]
    trial_cutoff_time = time_now + random.randrange(cfg[lowerISI], cfg[upperISI])

def send_results():
    start_millis = trial_start_time - exp_start_time
    print(trl_ + str(start_millis) + comma + str(trial_counter) + comma + str(reaction_time))

def end():
    global exp_running
    exp_running = False
    dotstar[0] = (0,0,255)
    stimulus.duty_cycle = 0
    print(stm_0)
    print(end_)

###################################################################
###################################################################
# MAIN LOOP
read_cfg()
gc.collect()
next_print = time.monotonic() + 1
loops = 0

while True:
    time_now = int(time.monotonic() * 1000)

    if exp_running:

        resp_now = response.value

        if resp_now - resp_then == -1:
            if not responded:
                reaction_time = time_now - trial_start_time

                response_port.value=0
                time.sleep(PORT_ON_TIME)
                response_port.value=1

                stimulus.duty_cycle = 0
                dotstar[0] = (0,0,0)
                print(stm_0)
                send_results()
                responded = True
            if time_now - last_response > DEBOUNCE_MILLIS:
                click_count += 1
                print(clk_ + str(click_count))
            last_response = time_now

        if time_now >= stim_cutoff_time and stimulus.duty_cycle > 0:
            stimulus.duty_cycle = 0
            dotstar[0] = (0,0,0)
            print(stm_0)

        if time_now >= trial_cutoff_time:
            if not responded:
                send_results()
            if exp_running:
                next_trial()

        resp_then = resp_now

    while supervisor.runtime.serial_bytes_available:
        new_msg = input()
        parse_msg(new_msg)