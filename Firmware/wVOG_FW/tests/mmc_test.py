from wVOG.mmc import MMC
import uasyncio as asyncio

class MMCWriteTest:
    def __init__(self):
        self.mmc = MMC()

    async def run_test(self):
        # Wait for 1 second before initializing the file
        await asyncio.sleep(1)
        self.mmc.init("Test File Header\n")

        # Write data to the file
        self.mmc.write("Data line 1\n")
        self.mmc.write("Data line 2\n")
        self.mmc.write("Data line 3\n")

        # Read the file contents to verify that the data was written correctly
        with open(self.mmc.filename, 'r') as infile:
            file_contents = infile.read()

        if file_contents == "Test File Header\nData line 1\nData line 2\nData line 3\n":
            print("MMC write test passed")
        else:
            print("MMC write test failed")

if __name__ == '__main__':
    async def main():
        mmc_write_test = MMCWriteTest()
        await mmc_write_test.run_test()

    asyncio.run(main())