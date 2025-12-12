import board
import digitalio
import storage

switch = digitalio.DigitalInOut(board.D0)
switch.direction = digitalio.Direction.INPUT
switch.pull = digitalio.Pull.UP

switch_not_pressed = switch.value
if switch_not_pressed:
    storage.disable_usb_drive()

storage.remount("/", not switch.value)
