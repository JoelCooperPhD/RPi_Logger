"""
Camera worker subprocess entry point.

This module is invoked as: python -m rpi_logger.modules.Cameras.worker

The worker receives pipe file descriptors via command line arguments and
communicates with the main process using pickle-serialized messages.
"""
from __future__ import annotations

import asyncio
import sys
import os
from multiprocessing.connection import Connection


def main() -> int:
    if len(sys.argv) < 3:
        print("Usage: python -m rpi_logger.modules.Cameras.worker <cmd_fd> <resp_fd>", file=sys.stderr)
        return 1

    cmd_fd = int(sys.argv[1])
    resp_fd = int(sys.argv[2])

    # Reconstruct Connection objects from file descriptors
    cmd_conn = Connection(cmd_fd, readable=True, writable=False)
    resp_conn = Connection(resp_fd, readable=False, writable=True)

    from .main import run_worker
    try:
        asyncio.run(run_worker(cmd_conn, resp_conn))
    except KeyboardInterrupt:
        pass
    finally:
        cmd_conn.close()
        resp_conn.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
