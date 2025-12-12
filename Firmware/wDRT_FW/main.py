from uasyncio import run

from main import controller
from main.wireless_drt import drt

def run_device():
    controller_ = controller.RSDeviceController(drt.BaseDRT)
    run(controller_.run_controller())


if __name__ is '__main__':
    run_device()