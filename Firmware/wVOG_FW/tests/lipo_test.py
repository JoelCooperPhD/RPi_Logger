import pyb
import uasyncio as asyncio
from wVOG.battery import LipoReader

class LipoReaderTest:
    def __init__(self):
        self.lipo = LipoReader(pin='X8')
        self.lipo.vref = 3.3
        self.lipo.vcut = 3.3
        self.lipo.max_adc = 4000

    async def run_test(self, repeats=5):
        for i in range(repeats):
            voltage = self.lipo.voltage()
            percent = self.lipo.percent()
            print()
            print("Running test on lipo battery")
            print("Test iteration:", i + 1)
            print("Battery voltage:", voltage, "V")
            print("Battery percentage:", percent, "%")
            print("-------------------")
            await asyncio.sleep(5)  # Wait for 5 seconds before the next iteration

# Run the test if the script is executed directly
if __name__ == "__main__":
    async def main():
        lipo_reader_test = LipoReaderTest()
        await lipo_reader_test.run_test()

    asyncio.run(main())