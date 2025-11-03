#!/usr/bin/env python3
"""Read a few lines from /dev/serial0 to verify GPS output."""

import argparse
import sys
from typing import Optional

try:
    import serial  # type: ignore
except ImportError as exc:  # pragma: no cover
    sys.exit("pyserial required: pip install pyserial")


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Quick serial read test")
    parser.add_argument("--port", default="/dev/serial0", help="Serial device")
    parser.add_argument("--baud", type=int, default=9600, help="Baud rate")
    parser.add_argument("--count", type=int, default=5, help="Number of lines to read")
    parser.add_argument("--timeout", type=float, default=1.0, help="Read timeout (seconds)")
    return parser.parse_args(argv)


def main() -> int:
    args = parse_args()

    try:
        ser = serial.Serial(args.port, args.baud, timeout=args.timeout)
    except serial.SerialException as exc:
        print(f"Failed to open {args.port}: {exc}", file=sys.stderr)
        return 1

    with ser:
        print(f"Reading up to {args.count} line(s) from {args.port} @ {args.baud} baud...")
        read = 0
        while read < args.count:
            line = ser.readline()
            if not line:
                print("(timeout)")
                break
            decoded = line.decode("ascii", errors="replace").rstrip("\r\n")
            print(f"{read+1}: {decoded}")
            read += 1

        if read == 0:
            print("No data received.")
        else:
            print(f"Received {read} line(s).")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
