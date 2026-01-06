"""Offline map tile rendering for GPS preview.

This module handles all map rendering using offline SQLite tile databases.
It supports trajectory visualization, compass rose, and scale bar overlays.
"""

from __future__ import annotations

import io
import math
import sqlite3
from collections import deque
from pathlib import Path
from typing import Deque, Optional, Tuple

from PIL import Image, ImageDraw

from rpi_logger.core.logging_utils import get_module_logger
from ...constants import (
    TILE_SIZE,
    GRID_SIZE,
    MIN_ZOOM_LEVEL,
    MAX_ZOOM_LEVEL,
)
from ...parsers.nmea_types import GPSFixSnapshot

logger = get_module_logger(__name__)


class GPSMapRenderer:
    """Renders offline map tiles with GPS position overlay.

    Responsibilities:
    - Load tiles from SQLite database
    - Render tile mosaic centered on position
    - Draw position marker with heading arrow
    - Draw compass rose and scale bar
    - Support zoom controls
    - Track and render trajectory history

    Example:
        renderer = GPSMapRenderer(Path("offline_tiles.db"))
        renderer.set_center(48.1173, 11.5166)
        renderer.set_zoom(13)
        image = renderer.render(fix)
    """

    def __init__(
        self,
        offline_db_path: Path,
        max_trajectory_points: int = 500,
    ):
        """Initialize the map renderer.

        Args:
            offline_db_path: Path to SQLite tile database
            max_trajectory_points: Maximum number of trajectory points to keep
        """
        self.db_path = offline_db_path
        self._current_zoom: float = 13.0
        self._center: Tuple[float, float] = (0.0, 0.0)
        self._trajectory: Deque[Tuple[float, float]] = deque(maxlen=max_trajectory_points)
        self._trajectory_enabled = True

    @property
    def center(self) -> Tuple[float, float]:
        """Current map center (latitude, longitude)."""
        return self._center

    @property
    def zoom(self) -> float:
        """Current zoom level."""
        return self._current_zoom

    @property
    def trajectory_enabled(self) -> bool:
        """Whether trajectory drawing is enabled."""
        return self._trajectory_enabled

    @trajectory_enabled.setter
    def trajectory_enabled(self, value: bool) -> None:
        """Enable or disable trajectory drawing."""
        self._trajectory_enabled = value

    def set_center(self, lat: float, lon: float) -> None:
        """Update map center position.

        Args:
            lat: Latitude in decimal degrees
            lon: Longitude in decimal degrees
        """
        self._center = (lat, lon)

    def set_zoom(self, zoom: float) -> None:
        """Set zoom level (clamped to valid range).

        Args:
            zoom: Zoom level (10.0 - 15.0)
        """
        self._current_zoom = max(MIN_ZOOM_LEVEL, min(MAX_ZOOM_LEVEL, zoom))

    def adjust_zoom(self, delta: float) -> float:
        """Adjust zoom by delta and return new level.

        Args:
            delta: Amount to change zoom (positive = zoom in)

        Returns:
            New zoom level after adjustment
        """
        self.set_zoom(self._current_zoom + delta)
        return self._current_zoom

    def can_zoom_in(self) -> bool:
        return self._current_zoom < MAX_ZOOM_LEVEL

    def can_zoom_out(self) -> bool:
        return self._current_zoom > MIN_ZOOM_LEVEL

    def add_position_to_trajectory(self, lat: float, lon: float) -> None:
        """Add position to trajectory history.

        Args:
            lat: Latitude in decimal degrees
            lon: Longitude in decimal degrees
        """
        if self._trajectory_enabled:
            self._trajectory.append((lat, lon))

    def clear_trajectory(self) -> None:
        """Clear trajectory history."""
        self._trajectory.clear()

    def render(self, fix: Optional[GPSFixSnapshot] = None) -> Tuple[Image.Image, str]:
        """Render map image with current position marked.

        Args:
            fix: Current GPS fix data for marker rendering (optional)

        Returns:
            Tuple of (PIL Image of rendered map, info string)
        """
        lat, lon = self._center
        return self._render_tile_mosaic(lat, lon, self._current_zoom, fix)

    def _render_tile_mosaic(
        self,
        lat: float,
        lon: float,
        zoom: float,
        fix: Optional[GPSFixSnapshot] = None,
    ) -> Tuple[Image.Image, str]:
        """Render a tile mosaic centered on the given position.

        Args:
            lat: Center latitude
            lon: Center longitude
            zoom: Zoom level
            fix: GPS fix for marker (optional)

        Returns:
            Tuple of (rendered image, info string)
        """
        zoom_int = max(int(MIN_ZOOM_LEVEL), min(int(MAX_ZOOM_LEVEL), int(round(zoom))))
        display_grid = GRID_SIZE
        load_grid = display_grid + 2
        display_size = display_grid * TILE_SIZE
        load_size = load_grid * TILE_SIZE
        image = Image.new("RGB", (load_size, load_size), "#dcdcdc")

        xtile, ytile = self._latlon_to_tile(lat, lon, zoom_int)
        base_x = int(math.floor(xtile)) - load_grid // 2
        base_y = int(math.floor(ytile)) - load_grid // 2

        total_loaded = 0
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        n = 2 ** zoom_int

        try:
            for gx in range(load_grid):
                for gy in range(load_grid):
                    tx = (base_x + gx) % max(1, n)
                    ty = min(max(base_y + gy, 0), max(n - 1, 0))
                    tile = self._load_tile_image(cur, zoom_int, tx, ty)
                    if tile is None:
                        tile = Image.new("RGB", (TILE_SIZE, TILE_SIZE), "#b9c1c9")
                    else:
                        total_loaded += 1
                    image.paste(tile, (gx * TILE_SIZE, gy * TILE_SIZE))
        finally:
            conn.close()

        # Calculate center position in pixel coordinates
        tile_center_x = (xtile - base_x) * TILE_SIZE
        tile_center_y = (ytile - base_y) * TILE_SIZE

        # Crop to display size, centered on position
        crop_left = tile_center_x - (display_size / 2)
        crop_top = tile_center_y - (display_size / 2)
        max_offset = load_size - display_size
        crop_left = int(round(max(0.0, min(max_offset, crop_left))))
        crop_top = int(round(max(0.0, min(max_offset, crop_top))))
        image = image.crop((crop_left, crop_top, crop_left + display_size, crop_top + display_size))

        center_x = tile_center_x - crop_left
        center_y = tile_center_y - crop_top

        # Draw trajectory
        if self._trajectory_enabled and len(self._trajectory) > 1:
            self._draw_trajectory(image, zoom_int, base_x, base_y, crop_left, crop_top)

        # Draw position marker
        self._draw_center_marker(image, center_x, center_y, fix)

        # Draw compass rose
        draw = ImageDraw.Draw(image)
        self._draw_compass_rose(draw, image.width - 40, 40)

        # Draw scale bar
        self._draw_scale_bar(draw, image.width, image.height, zoom_int, lat)

        info = f"{total_loaded}/{load_grid * load_grid} tiles (zoom={zoom_int})"
        return image, info

    def _load_tile_image(self, cursor, zoom: int, x: int, y: int) -> Optional[Image.Image]:
        """Load a single tile from the database.

        Args:
            cursor: Database cursor
            zoom: Zoom level
            x: Tile X coordinate
            y: Tile Y coordinate

        Returns:
            PIL Image or None if not found
        """
        cursor.execute(
            "SELECT tile_image FROM tiles WHERE zoom=? AND x=? AND y=? LIMIT 1",
            (zoom, x, y),
        )
        row = cursor.fetchone()
        if not row:
            return None
        try:
            return Image.open(io.BytesIO(row[0])).convert("RGB")
        except Exception:
            return None

    def _latlon_to_tile(self, lat: float, lon: float, zoom: int) -> Tuple[float, float]:
        """Convert lat/lon to tile coordinates.

        Args:
            lat: Latitude in decimal degrees
            lon: Longitude in decimal degrees
            zoom: Zoom level

        Returns:
            Tuple of (x_tile, y_tile) as floats
        """
        lat_rad = math.radians(lat)
        n = 2 ** zoom
        xtile = (lon + 180.0) / 360.0 * n
        ytile = (1.0 - math.log(math.tan(lat_rad) + (1 / math.cos(lat_rad))) / math.pi) / 2.0 * n
        return xtile, ytile

    def _latlon_to_pixel(
        self,
        lat: float,
        lon: float,
        zoom: int,
        base_x: int,
        base_y: int,
        crop_left: int,
        crop_top: int,
    ) -> Tuple[float, float]:
        """Convert lat/lon to pixel coordinates within the cropped image.

        Args:
            lat: Latitude
            lon: Longitude
            zoom: Zoom level
            base_x: Base tile X
            base_y: Base tile Y
            crop_left: Crop offset X
            crop_top: Crop offset Y

        Returns:
            Tuple of (pixel_x, pixel_y)
        """
        xtile, ytile = self._latlon_to_tile(lat, lon, zoom)
        pixel_x = (xtile - base_x) * TILE_SIZE - crop_left
        pixel_y = (ytile - base_y) * TILE_SIZE - crop_top
        return pixel_x, pixel_y

    def _draw_trajectory(
        self,
        image: Image.Image,
        zoom: int,
        base_x: int,
        base_y: int,
        crop_left: int,
        crop_top: int,
    ) -> None:
        """Draw trajectory line on map.

        Args:
            image: Image to draw on
            zoom: Current zoom level
            base_x: Base tile X coordinate
            base_y: Base tile Y coordinate
            crop_left: Crop offset X
            crop_top: Crop offset Y
        """
        if len(self._trajectory) < 2:
            return

        draw = ImageDraw.Draw(image)
        points = []

        for lat, lon in self._trajectory:
            x, y = self._latlon_to_pixel(lat, lon, zoom, base_x, base_y, crop_left, crop_top)
            # Only include points within or near the visible area
            if -100 < x < image.width + 100 and -100 < y < image.height + 100:
                points.append((x, y))

        if len(points) >= 2:
            # Draw as connected line with gradient effect
            draw.line(points, fill="#3498db", width=3)

            # Draw dots at trajectory points (every N points for performance)
            step = max(1, len(points) // 50)
            for i in range(0, len(points), step):
                x, y = points[i]
                draw.ellipse((x - 2, y - 2, x + 2, y + 2), fill="#2980b9")

    def _draw_center_marker(
        self,
        image: Image.Image,
        x: float,
        y: float,
        fix: Optional[GPSFixSnapshot] = None,
    ) -> None:
        """Draw GPS position marker at the given coordinates.

        Args:
            image: Image to draw on
            x: Pixel X coordinate
            y: Pixel Y coordinate
            fix: GPS fix data for styling (optional)
        """
        draw = ImageDraw.Draw(image)

        # Determine marker color based on fix validity
        if fix and fix.fix_valid:
            marker_color = "#2ecc71"  # Green
        else:
            marker_color = "#ff4d4f"  # Red

        # Outer ring
        radius = 8
        draw.ellipse(
            (x - radius, y - radius, x + radius, y + radius),
            outline=marker_color,
            width=3,
        )

        # Inner dot
        inner_radius = 3
        draw.ellipse(
            (x - inner_radius, y - inner_radius, x + inner_radius, y + inner_radius),
            fill=marker_color,
        )

        # Direction arrow (if we have heading data and are moving)
        if fix and fix.course_deg is not None and fix.speed_kmh and fix.speed_kmh > 1.0:
            angle_rad = math.radians(fix.course_deg - 90)  # Convert to math angle
            arrow_len = 20
            end_x = x + arrow_len * math.cos(angle_rad)
            end_y = y + arrow_len * math.sin(angle_rad)

            # Draw direction line
            draw.line((x, y, end_x, end_y), fill=marker_color, width=2)

            # Draw arrowhead
            arrow_size = 6
            left_angle = angle_rad + math.pi * 0.8
            right_angle = angle_rad - math.pi * 0.8
            left_x = end_x + arrow_size * math.cos(left_angle)
            left_y = end_y + arrow_size * math.sin(left_angle)
            right_x = end_x + arrow_size * math.cos(right_angle)
            right_y = end_y + arrow_size * math.sin(right_angle)
            draw.polygon([(end_x, end_y), (left_x, left_y), (right_x, right_y)], fill=marker_color)

    def _draw_compass_rose(self, draw: ImageDraw.Draw, cx: float, cy: float) -> None:
        """Draw a compass rose at the given center position.

        Args:
            draw: ImageDraw object
            cx: Center X coordinate
            cy: Center Y coordinate
        """
        # Colors
        bg_color = "#2b2b2b"
        border_color = "#404055"
        north_color = "#e74c3c"  # Red for North
        text_color = "#ecf0f1"

        radius = 28

        # Background circle
        draw.ellipse(
            (cx - radius, cy - radius, cx + radius, cy + radius),
            fill=bg_color,
            outline=border_color,
            width=2,
        )

        # Cardinal direction markers
        directions = [
            ("N", 0, north_color),
            ("E", 90, text_color),
            ("S", 180, text_color),
            ("W", 270, text_color),
        ]

        for label, angle, color in directions:
            angle_rad = math.radians(angle - 90)  # 0 is up
            inner_r = 10
            outer_r = radius - 4
            x1 = cx + inner_r * math.cos(angle_rad)
            y1 = cy + inner_r * math.sin(angle_rad)
            x2 = cx + outer_r * math.cos(angle_rad)
            y2 = cy + outer_r * math.sin(angle_rad)
            draw.line((x1, y1, x2, y2), fill=color, width=2 if label == "N" else 1)

        # North indicator arrow
        arrow_len = radius - 6
        arrow_end_y = cy - arrow_len
        draw.polygon(
            [(cx, arrow_end_y), (cx - 5, cy - arrow_len + 10), (cx + 5, cy - arrow_len + 10)],
            fill=north_color,
        )

    def _draw_scale_bar(
        self,
        draw: ImageDraw.Draw,
        image_width: int,
        image_height: int,
        zoom: int,
        lat: float,
    ) -> None:
        """Draw a scale bar in the bottom-left corner of the map.

        Args:
            draw: ImageDraw object
            image_width: Image width in pixels
            image_height: Image height in pixels
            zoom: Current zoom level
            lat: Center latitude (affects scale)
        """
        # Calculate meters per pixel at current zoom level
        # At zoom 0, the whole world (40075 km) fits in 256 pixels
        # Each zoom level doubles the resolution
        meters_per_pixel = 40075016.686 * math.cos(math.radians(lat)) / (256 * (2 ** zoom))

        # Choose a nice round distance for the scale bar
        target_pixels = 100
        target_meters = meters_per_pixel * target_pixels

        # Find the nearest nice round number
        nice_distances = [10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000, 50000]
        scale_meters = min(nice_distances, key=lambda d: abs(d - target_meters))
        scale_pixels = int(scale_meters / meters_per_pixel)

        # Position in bottom-left
        x = 10
        y = image_height - 20

        # Colors
        bg_color = "#2b2b2b"
        bar_color = "#ecf0f1"

        # Background
        draw.rectangle(
            (x - 4, y - 16, x + scale_pixels + 10, y + 6),
            fill=bg_color,
        )

        # Scale bar
        draw.rectangle((x, y - 4, x + scale_pixels, y), fill=bar_color)

        # End caps
        draw.rectangle((x, y - 8, x + 2, y), fill=bar_color)
        draw.rectangle((x + scale_pixels - 2, y - 8, x + scale_pixels, y), fill=bar_color)

        # Label
        if scale_meters >= 1000:
            label = f"{scale_meters // 1000} km"
        else:
            label = f"{scale_meters} m"

        draw.text((x + scale_pixels // 2, y - 12), label, fill=bar_color, anchor="mm")

    def database_exists(self) -> bool:
        """Check if the offline database file exists.

        Returns:
            True if database file exists
        """
        return self.db_path.exists()
