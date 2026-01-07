# Cameras-USB2 Module Entry Point
# Task: P7.1

import asyncio
import argparse
from pathlib import Path

MODULE_DISPLAY_NAME = "Cameras-USB2"
MODULE_ID = "cameras_usb2"


def parse_args():
    parser = argparse.ArgumentParser(description=MODULE_DISPLAY_NAME)
    parser.add_argument("--config", type=Path, help="Config file path")
    parser.add_argument("--output-dir", type=Path, help="Output directory")
    parser.add_argument("--session-prefix", type=str, default="recording")
    parser.add_argument("--no-console", action="store_true", help="Disable console logging")
    return parser.parse_args()


async def main():
    args = parse_args()

    from .config import CamerasConfig
    config = CamerasConfig.from_preferences({}, {
        "output_dir": args.output_dir,
    })

    from .bridge import CamerasRuntime
    runtime = CamerasRuntime(config=config)

    await runtime.initialize()

    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        await runtime.shutdown()


def run():
    asyncio.run(main())


if __name__ == "__main__":
    run()
