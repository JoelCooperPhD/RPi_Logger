#!/usr/bin/env python3
"""
Download offline map tiles for GPS2 module.

This creates a database of offline tiles that can be used without internet.
Adjust the coordinates and zoom levels for your region.
"""

import tkintermapview
from pathlib import Path

# Salt Lake City and Tooele, Utah area
# Covers SLC (40.76°N, 111.89°W) to Tooele (40.53°N, 112.30°W)
top_left_position = (40.95, -112.5)      # Northwest corner
bottom_right_position = (40.4, -111.7)   # Southeast corner

# Zoom levels - higher = more detail but larger file
zoom_min = 0   # World view
zoom_max = 15  # Street level detail (reduced to 15 to save space)

# Output path
script_dir = Path(__file__).parent
database_path = script_dir / "offline_tiles.db"

print(f"Downloading tiles for region:")
print(f"  Top-left: {top_left_position}")
print(f"  Bottom-right: {bottom_right_position}")
print(f"  Zoom levels: {zoom_min}-{zoom_max}")
print(f"  Output: {database_path}")
print()
print("This may take several minutes and download ~100MB...")
print()

# Create OfflineLoader instance
loader = tkintermapview.OfflineLoader(
    path=str(database_path),
    tile_server="https://a.tile.openstreetmap.org/{z}/{x}/{y}.png"
)

# Download the tiles
loader.save_offline_tiles(top_left_position, bottom_right_position, zoom_min, zoom_max)

# Print summary
print()
print("Download complete!")
print()
print("Loaded regions:")
loader.print_loaded_sections()
