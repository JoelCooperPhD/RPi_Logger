from wVOG import controller
from uasyncio import run, get_event_loop

async def wVOG():
    wVOG = controller.WirelessVOG()
    Loop = get_event_loop()
    await Loop.run_forever()

if __name__ is '__main__':
    run(wVOG())