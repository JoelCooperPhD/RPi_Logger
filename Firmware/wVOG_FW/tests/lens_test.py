import uasyncio as asyncio
from wVOG.lenses import Lenses

class LensTest:
    def __init__(self, verbose=False, delay=.4):
        self._verbose = verbose
        self._lenses = Lenses()
        self._delay = delay
    
    async def run_test(self, repeats=2):
        print("Initiating lens test\n")

        scenarios = [
            ("Toggle both lenses", ['a', 'b']),
            ("Toggle lens A", 'a'),
            ("Toggle lens B", 'b'),
        ]

        for description, lens in scenarios:
            print(f"Scenario: {description}")
            await self._toggle(times=repeats, lens=lens)
            print()

        print("\nLens test complete\n")

    async def _toggle(self, times, lens):
        for i in range(times):
            if self._verbose:
                print(f"Toggle {lens}: {i+1} / {times}")

            self._lenses.update_lens(lens, 1)
            await asyncio.sleep(self._delay)

            self._lenses.update_lens(lens, 0)
            await asyncio.sleep(self._delay)

if __name__ == "__main__":
    asyncio.run(LensTest(verbose=True, delay=.4).run_test(5))