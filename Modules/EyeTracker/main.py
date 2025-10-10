#!/usr/bin/env python3
"""Compatibility shim that delegates to main_eye_tracker."""

import asyncio

from main_eye_tracker import main as async_main


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
