#!/usr/bin/env python3
"""Simple serial monitor for Raspberry Pi TX/RX pins.

Opens the Pi's primary UART (`/dev/serial0` by default) and prints any bytes
received. Optionally sends a test string on startup so you can confirm the TX
line is active (requires the RX pin to be looped back or a device connected).

Usage examples:
  python3 utils/pi_serial_monitor.py            # monitor /dev/serial0 @ 9600
  python3 utils/pi_serial_monitor.py --baud 4800
  python3 utils/pi_serial_monitor.py --port /dev/ttyUSB0 --write "test" --hex
"""

from __future__ import annotations

import argparse
import binascii
from datetime import datetime
from typing import Optional

try:
    import serial  # type: ignore
except ImportError as exc:  # pragma: no cover - runtime dependency
    raise SystemExit(
        "pyserial is required: pip install pyserial"
    ) from exc


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Lightweight UART monitor")
    parser.add_argument(
        "--port",
        default="/dev/serial0",
        help="Serial device to open (default: /dev/serial0)",
    )
    parser.add_argument(
        "--baud",
        type=int,
        default=9600,
        help="Baud rate to use (default: 9600)",
    )
    parser.add_argument(
        "--write",
        help="Optional ASCII text to send once after opening the port",
    )
    parser.add_argument(
        "--hex",
        action="store_true",
        help="Also print the received bytes as hex",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=1.0,
        help="Read timeout in seconds (default: 1.0)",
    )
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args()

    try:
        ser = serial.Serial(
            port=args.port,
            baudrate=args.baud,
            timeout=args.timeout,
        )
    except serial.SerialException as exc:
        raise SystemExit(f"Failed to open {args.port}: {exc}") from exc

    with ser:
        print(
            f"Monitoring {args.port} @ {args.baud} baud (timeout={args.timeout}s).\n"
            "Press Ctrl+C to stop."
        )

        if args.write is not None:
            payload = args.write.encode("ascii", "ignore")
            if not payload.endswith((b"\r", b"\n")):
                payload += b"\r\n"
            ser.write(payload)
            ser.flush()
            print(f"[TX] {payload!r}")

        try:
            while True:
                chunk = ser.readline()
                if not chunk:
                    continue

                ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                try:
                    text = chunk.decode("ascii").rstrip("\r\n")
                except UnicodeDecodeError:
                    text = chunk.decode("ascii", "replace").rstrip("\r\n")

                if args.hex:
                    hex_repr = binascii.hexlify(chunk).decode("ascii")
                    print(f"[{ts}] RX: {text!r} | 0x{hex_repr}")
                else:
                    print(f"[{ts}] RX: {text!r}")
        except KeyboardInterrupt:
            print("\nStopping monitor...")


if __name__ == "__main__":
    main()
