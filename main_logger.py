#!/usr/bin/env python3
"""Convenience entrypoint so existing scripts can run ``main_logger.py``."""

from __future__ import annotations

import sys

def main() -> int:
    from rpi_logger.app.master import run as _run_master
    return _run_master(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
