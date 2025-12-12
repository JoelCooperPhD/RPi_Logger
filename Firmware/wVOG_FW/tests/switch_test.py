from pyb import Pin
import uasyncio as asyncio
from utime import ticks_ms, ticks_diff, sleep_ms
from wVOG.switch import DebouncedSwitch

class SwitchTest:
    def __init__(self, test_duration=10000, min_interval=200):
        self.switch = DebouncedSwitch()
        self.test_duration = test_duration
        self.min_interval = min_interval

        self.valid_presses = 0
        self.invalid_presses = 0

    def switch_callback(self, state, time, down_cnt, up_cnt):
        if state == 0:
            elapsed = ticks_diff(ticks_ms(), self.last_press_time)
            if elapsed >= self.min_interval:
                self.valid_presses += 1
                print("Valid press detected.")
            else:
                self.invalid_presses += 1
                print("Invalid press detected.")
            self.last_press_time = ticks_ms()

    async def run_test(self):
        self.switch.reset_counters()
        self.switch._open_close_cb = self.switch_callback
        self.last_press_time = ticks_ms()

        print("Test started. Press the switch as fast as you can for the next {} seconds.".format(self.test_duration // 1000))
        print("A valid press should be at least {} milliseconds apart.".format(self.min_interval))

        start_time = ticks_ms()
        switch_update_task = asyncio.create_task(self.switch.update())

        while ticks_diff(ticks_ms(), start_time) < self.test_duration:
            await asyncio.sleep(0)

        switch_update_task.cancel()

        return {
            'valid_presses': self.valid_presses,
            'invalid_presses': self.invalid_presses
        }

if __name__ == "__main__":
    test = SwitchTest(test_duration=10000, min_interval=200)
    result = asyncio.run(test.run_test())

    print("\nTest results:")
    print(f"Valid presses: {result['valid_presses']}")
    print(f"Invalid presses: {result['invalid_presses']}")