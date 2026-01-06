#!/usr/bin/env python3
"""Download offline map tiles for the GPS module."""

import logging
from pathlib import Path

from rpi_logger.core.logging_config import configure_logging
from rpi_logger.core.logging_utils import get_module_logger

configure_logging(level=logging.INFO, console=True)
logger = get_module_logger("GPS.DownloadTiles")

try:
    from tkintermapview import OfflineLoader
except Exception as exc:  # pragma: no cover - optional dependency
    raise SystemExit(f"tkintermapview is required: {exc}") from exc

MODULE_DIR = Path(__file__).parent
DATABASE_PATH = MODULE_DIR / "offline_tiles.db"

# Salt Lake City / Tooele region
TOP_LEFT = (40.95, -112.5)
BOTTOM_RIGHT = (40.4, -111.7)
ZOOM_MIN = 0
ZOOM_MAX = 15

logger.info("Downloading tiles for GPS module:")
logger.info("  Region: %s -> %s", TOP_LEFT, BOTTOM_RIGHT)
logger.info("  Zoom levels: %d-%d", ZOOM_MIN, ZOOM_MAX)
logger.info("  Output: %s", DATABASE_PATH)
logger.info("")

loader = OfflineLoader(
    path=str(DATABASE_PATH),
    tile_server="https://a.tile.openstreetmap.org/{z}/{x}/{y}.png",
)
loader.save_offline_tiles(TOP_LEFT, BOTTOM_RIGHT, ZOOM_MIN, ZOOM_MAX)
logger.info("Done! Offline tiles saved to %s", DATABASE_PATH)
logger.info("Loaded sections:")
loader.print_loaded_sections()
