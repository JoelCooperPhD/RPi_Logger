#!/usr/bin/env python3
"""
Window Manager Utility

Calculates optimal window positions and sizes for tiling multiple module windows.
Provides smart layouts based on the number of active modules.
"""

import logging
import math
import tkinter as tk
from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional

logger = logging.getLogger("WindowManager")


@dataclass
class WindowGeometry:
    """Window geometry specification."""
    x: int
    y: int
    width: int
    height: int

    def to_geometry_string(self) -> str:
        """Convert to Tk geometry string format: WIDTHxHEIGHT+X+Y"""
        return f"{self.width}x{self.height}+{self.x}+{self.y}"

    @staticmethod
    def from_geometry_string(geometry: str) -> Optional['WindowGeometry']:
        """Parse Tk geometry string format: WIDTHxHEIGHT+X+Y"""
        try:
            # Split into size and position
            if '+' not in geometry and '-' not in geometry:
                return None

            # Handle negative positions
            size_part = geometry.split('+')[0].split('-')[0]
            pos_part = geometry[len(size_part):]

            # Parse size
            width, height = map(int, size_part.split('x'))

            # Parse position
            x_str, y_str = pos_part.replace('+', ' ').replace('-', ' -').split()
            x = int(x_str)
            y = int(y_str)

            return WindowGeometry(x=x, y=y, width=width, height=height)
        except Exception as e:
            logger.warning("Failed to parse geometry string '%s': %s", geometry, e)
            return None


class WindowManager:
    """
    Manages window positioning and tiling for multiple module windows.

    Features:
    - Calculates optimal tiling layouts
    - Detects screen resolution
    - Provides fallback positions
    - Respects saved window positions from config
    """

    def __init__(self):
        """Initialize window manager."""
        self.screen_width, self.screen_height = self._get_screen_resolution()
        self.taskbar_height = 40  # Estimated taskbar/menu height
        self.window_gap = 5  # Gap between tiled windows
        self.min_window_width = 400
        self.min_window_height = 300

        logger.info("Screen resolution: %dx%d", self.screen_width, self.screen_height)

    def _get_screen_resolution(self) -> Tuple[int, int]:
        """
        Get screen resolution using tkinter.

        Returns:
            Tuple of (width, height) in pixels
        """
        try:
            # Create temporary root to get screen info
            root = tk.Tk()
            root.withdraw()  # Hide the window
            width = root.winfo_screenwidth()
            height = root.winfo_screenheight()
            root.destroy()
            return width, height
        except Exception as e:
            logger.warning("Failed to detect screen resolution: %s. Using default 1920x1080", e)
            return 1920, 1080

    def calculate_tiling_layout(
        self,
        num_modules: int,
        saved_geometries: Optional[Dict[str, WindowGeometry]] = None
    ) -> Dict[str, WindowGeometry]:
        """
        Calculate optimal window positions for N modules.

        Args:
            num_modules: Number of modules to tile
            saved_geometries: Optional dict of saved geometries from config

        Returns:
            Dict mapping module index (as string) to WindowGeometry
        """
        if num_modules <= 0:
            return {}

        # If we have saved geometries for all modules, use them
        if saved_geometries and len(saved_geometries) == num_modules:
            logger.info("Using saved window geometries for %d modules", num_modules)
            return saved_geometries

        logger.info("Calculating tiling layout for %d modules", num_modules)

        # Calculate grid dimensions
        grid_cols, grid_rows = self._calculate_grid_dimensions(num_modules)

        # Calculate available space (accounting for taskbar)
        available_width = self.screen_width
        available_height = self.screen_height - self.taskbar_height

        # Calculate window dimensions
        window_width = (available_width - (grid_cols + 1) * self.window_gap) // grid_cols
        window_height = (available_height - (grid_rows + 1) * self.window_gap) // grid_rows

        # Enforce minimum sizes
        window_width = max(window_width, self.min_window_width)
        window_height = max(window_height, self.min_window_height)

        # Calculate positions
        geometries = {}
        for i in range(num_modules):
            row = i // grid_cols
            col = i % grid_cols

            x = self.window_gap + col * (window_width + self.window_gap)
            y = self.window_gap + row * (window_height + self.window_gap)

            geometries[str(i)] = WindowGeometry(
                x=x,
                y=y,
                width=window_width,
                height=window_height
            )

        logger.info("Calculated %dx%d grid layout", grid_cols, grid_rows)
        return geometries

    def _calculate_grid_dimensions(self, num_modules: int) -> Tuple[int, int]:
        """
        Calculate optimal grid dimensions (columns, rows) for N modules.

        Optimizes for:
        - Balanced aspect ratio (close to 16:9 or 4:3)
        - Minimal wasted space
        - Good visibility of each window

        Args:
            num_modules: Number of modules to arrange

        Returns:
            Tuple of (columns, rows)
        """
        if num_modules == 1:
            return (1, 1)
        elif num_modules == 2:
            # Side by side (better for wide screens)
            return (2, 1)
        elif num_modules == 3:
            # 2 on top, 1 on bottom (or 3 in a row if screen is wide enough)
            if self.screen_width >= 2400:
                return (3, 1)
            return (2, 2)  # Will leave one empty spot
        elif num_modules == 4:
            return (2, 2)
        elif num_modules == 5 or num_modules == 6:
            return (3, 2)
        elif num_modules <= 9:
            return (3, 3)
        elif num_modules <= 12:
            return (4, 3)
        else:
            # For many modules, calculate square-ish grid
            cols = math.ceil(math.sqrt(num_modules))
            rows = math.ceil(num_modules / cols)
            return (cols, rows)

    def get_centered_geometry(self, width: int, height: int) -> WindowGeometry:
        """
        Get geometry for a centered window.

        Args:
            width: Window width
            height: Window height

        Returns:
            WindowGeometry centered on screen
        """
        x = (self.screen_width - width) // 2
        y = (self.screen_height - self.taskbar_height - height) // 2

        return WindowGeometry(x=x, y=y, width=width, height=height)

    def get_default_geometry(self, module_index: int = 0) -> WindowGeometry:
        """
        Get default geometry for a module when no saved geometry exists.

        Args:
            module_index: Module index for offset positioning

        Returns:
            WindowGeometry with default size and cascading position
        """
        # Default size (reasonable for most modules)
        width = 800
        height = 600

        # Cascade windows slightly offset
        offset = module_index * 30
        x = 50 + offset
        y = 50 + offset

        return WindowGeometry(x=x, y=y, width=width, height=height)


if __name__ == "__main__":
    # Test the window manager
    logging.basicConfig(level=logging.INFO)

    wm = WindowManager()

    # Test different numbers of modules
    for n in [1, 2, 3, 4, 5, 6, 9]:
        print(f"\n=== Layout for {n} modules ===")
        geometries = wm.calculate_tiling_layout(n)
        for idx, geo in geometries.items():
            print(f"  Module {idx}: {geo.to_geometry_string()}")
