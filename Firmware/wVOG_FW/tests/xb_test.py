import uasyncio as asyncio
from wVOG import xb


class XbTest:
    def __init__(self, verbose=True):
        self._xb = xb.XB(debug=False)
        self._xb.register_incoming_message_cb(self._handle_xb_msg)
        self._results = []
        self._verbose = verbose

    async def run_test(self, repeats=5):
        if self._verbose:
            print(f"Running XBee test {repeats} times")
            print("Messages sent to the device during testing will be printed to the screen\n")

        xb_run = asyncio.create_task(self._xb._listen_for_new_messages())

        await asyncio.sleep(0.1)
        await asyncio.create_task(self._send_commands(repeats))

        xb_run.cancel()

        if self._verbose:
            result = "PASS" if sum(self._results) == repeats else "FAIL"
            print(f"\nXBee test result: {result}")

        return result

    async def _send_commands(self, repeats):
        for i in range(repeats):
            msg = f"Transmit attempt: {i + 1}"
            asyncio.create_task(self._xb.transmit(str(i)))

            await asyncio.sleep(1)
            self._results.append(self._xb.ACK)

            if self._verbose:
                outcome = "success" if self._xb.ACK else "fail"
                print(f"{msg} {outcome}")

    async def _handle_xb_msg(self, msg):
        if self._verbose:
            print("Listening for new messages...")
        print(msg)


if __name__ == "__main__":
    async def main():
        xbt = XbTest()
        await xbt.run_test()

    asyncio.run(main())