
from rpi_logger.core.logging_utils import get_module_logger
import math
import tkinter as tk
from dataclasses import dataclass
from typing import Dict, Tuple, Optional

from .logging_config import configure_logging

logger = get_module_logger("WindowManager")


@dataclass
class WindowGeometry:
    x: int
    y: int
    width: int
    height: int

    def to_geometry_string(self) -> str:
        return f"{self.width}x{self.height}+{self.x}+{self.y}"

    @staticmethod
    def from_geometry_string(geometry: str) -> Optional['WindowGeometry']:
        try:
            if '+' not in geometry and '-' not in geometry:
                return None

            size_part = geometry.split('+')[0].split('-')[0]
            pos_part = geometry[len(size_part):]

            width, height = map(int, size_part.split('x'))

            x_str, y_str = pos_part.replace('+', ' ').replace('-', ' -').split()
            x = int(x_str)
            y = int(y_str)

            return WindowGeometry(x=x, y=y, width=width, height=height)
        except Exception as e:
            logger.warning("Failed to parse geometry string '%s': %s", geometry, e)
            return None


class WindowManager:

    def __init__(self):
        self.screen_width, self.screen_height = self._get_screen_resolution()
        self.taskbar_height = 40  # Estimated taskbar/menu height
        self.window_gap = 5  # Gap between tiled windows
        self.min_window_width = 400
        self.min_window_height = 300

        logger.info("Screen resolution: %dx%d", self.screen_width, self.screen_height)

    def _get_screen_resolution(self) -> Tuple[int, int]:
        try:
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
        if num_modules <= 0:
            return {}

        if saved_geometries and len(saved_geometries) == num_modules:
            logger.info("Using saved window geometries for %d modules", num_modules)
            return saved_geometries

        logger.info("Calculating tiling layout for %d modules", num_modules)

        grid_cols, grid_rows = self._calculate_grid_dimensions(num_modules)

        available_width = self.screen_width
        available_height = self.screen_height - self.taskbar_height

        window_width = (available_width - (grid_cols + 1) * self.window_gap) // grid_cols
        window_height = (available_height - (grid_rows + 1) * self.window_gap) // grid_rows

        window_width = max(window_width, self.min_window_width)
        window_height = max(window_height, self.min_window_height)

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
        if num_modules == 1:
            return (1, 1)
        elif num_modules == 2:
            return (2, 1)
        elif num_modules == 3:
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
            cols = math.ceil(math.sqrt(num_modules))
            rows = math.ceil(num_modules / cols)
            return (cols, rows)

    def get_centered_geometry(self, width: int, height: int) -> WindowGeometry:
        x = (self.screen_width - width) // 2
        y = (self.screen_height - self.taskbar_height - height) // 2

        return WindowGeometry(x=x, y=y, width=width, height=height)

    def get_default_geometry(self, module_index: int = 0) -> WindowGeometry:
        width = 800
        height = 600

        # Cascade windows slightly offset
        offset = module_index * 30
        x = 50 + offset
        y = 50 + offset

        return WindowGeometry(x=x, y=y, width=width, height=height)


if __name__ == "__main__":
    configure_logging(level=logging.INFO, force=True)

    wm = WindowManager()

    for n in [1, 2, 3, 4, 5, 6, 9]:
        print(f"\n=== Layout for {n} modules ===")
        geometries = wm.calculate_tiling_layout(n)
        for idx, geo in geometries.items():
            print(f"  Module {idx}: {geo.to_geometry_string()}")
