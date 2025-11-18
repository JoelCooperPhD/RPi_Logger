#!/usr/bin/env python3
"""Download offline map tiles for the GPS module."""

from pathlib import Path

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

print("Downloading tiles for GPS module:")
print(f"  Region: {TOP_LEFT} -> {BOTTOM_RIGHT}")
print(f"  Zoom levels: {ZOOM_MIN}-{ZOOM_MAX}")
print(f"  Output: {DATABASE_PATH}")
print()

loader = OfflineLoader(
    path=str(DATABASE_PATH),
    tile_server="https://a.tile.openstreetmap.org/{z}/{x}/{y}.png",
)
loader.save_offline_tiles(TOP_LEFT, BOTTOM_RIGHT, ZOOM_MIN, ZOOM_MAX)
print("Done! Offline tiles saved to", DATABASE_PATH)
print("Loaded sections:")
loader.print_loaded_sections()
