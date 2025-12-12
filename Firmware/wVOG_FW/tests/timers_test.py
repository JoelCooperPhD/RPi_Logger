import uasyncio as asyncio
from wVOG.timers import Stopwatch, Countdown, ABTimeAccumulator

class TimerTest:
    def __init__(self):
        pass

    async def run_test(self):
        await self.test_stopwatch()
        print()
        await self.test_countdown()
        print()
        await self.test_ab_time_accumulator()

    async def test_stopwatch(self):
        sw = Stopwatch()

        sw.start()
        await asyncio.sleep(2)
        elapsed_time = sw.read()
        expected_time = 2000
        precision = 1
        passed = abs(elapsed_time - expected_time) <= precision
        print(f"Stopwatch test 1: {'PASSED' if passed else 'FAILED'} - Elapsed time (expected around 2000ms): {elapsed_time}ms")

        await asyncio.sleep(3)
        elapsed_time = sw.stop()
        expected_time = 5000
        passed = abs(elapsed_time - expected_time) <= precision
        print(f"Stopwatch test 2: {'PASSED' if passed else 'FAILED'} - Total elapsed time (expected around 5000ms): {elapsed_time}ms")

    def countdown_callback(self, elapsed):
        expected_time = 3000
        precision = 1
        passed = abs(elapsed - expected_time) <= precision
        print(f"Countdown test: {'PASSED' if passed else 'FAILED'} - Elapsed time: {elapsed}ms")

    async def test_countdown(self):
        cd = Countdown(self.countdown_callback, duration=3000)
        await cd.start()

    async def test_ab_time_accumulator(self):
        ab = ABTimeAccumulator()

        state = ab.start()

        await asyncio.sleep(1)
        state = ab.toggle()
        precision = 1
        passed = abs(state[2] - 1000) <= precision
        print(f"ABTimeAccumulator test 1: {'PASSED' if passed else 'FAILED'} - State after 1 second: {state}")

        await asyncio.sleep(2)
        state = ab.toggle()
        passed = abs(state[2] - 3000) <= precision
        print(f"ABTimeAccumulator test 2: {'PASSED' if passed else 'FAILED'} - State after 2 more seconds: {state}")

        await asyncio.sleep(3)
        state = ab.stop()

if __name__ == "__main__":
    async def main():
        timer_test = TimerTest()
        await timer_test.run_test()

    asyncio.run(main())