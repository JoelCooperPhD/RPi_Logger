"""Allow ``python -m rpi_logger`` to launch the master logger."""

from __future__ import annotations

import sys

from . import run


def main() -> None:
    run(sys.argv[1:])


if __name__ == "__main__":
    main()
