"""
Instance Geometry Store - Persists window geometry per device instance.

Stores geometry in ~/.rpi_logger/instance_geometry.json

This centralizes window geometry persistence for multi-instance modules,
allowing each device instance (e.g., DRT:ACM0, DRT:ACM1) to have its own
saved window position and size.

Example content:
{
  "DRT:ACM0": {"x": 100, "y": 50, "width": 800, "height": 600},
  "DRT:ACM1": {"x": 920, "y": 50, "width": 800, "height": 600},
  "main_window": {"x": 0, "y": 0, "width": 802, "height": 510}
}
"""

import os
import json
import tempfile
from pathlib import Path
from typing import Dict, Optional

from .paths import USER_STATE_DIR
from .window_manager import WindowGeometry
from .logging_utils import get_module_logger

logger = get_module_logger("InstanceGeometryStore")

GEOMETRY_FILE = USER_STATE_DIR / "instance_geometry.json"


class InstanceGeometryStore:
    """Manages per-instance window geometry persistence."""

    def __init__(self, file_path: Path = GEOMETRY_FILE):
        self._file_path = file_path
        self._cache: Dict[str, WindowGeometry] = {}
        self._load()

    def _load(self) -> None:
        """Load geometry data from file."""
        if not self._file_path.exists():
            logger.debug("No instance geometry file found at %s", self._file_path)
            return

        try:
            with open(self._file_path, 'r') as f:
                data = json.load(f)

            for instance_id, geom_dict in data.items():
                self._cache[instance_id] = WindowGeometry(
                    x=geom_dict.get('x', 0),
                    y=geom_dict.get('y', 0),
                    width=geom_dict.get('width', 800),
                    height=geom_dict.get('height', 600),
                )
            logger.info("Loaded geometry for %d instances", len(self._cache))
        except json.JSONDecodeError as e:
            logger.error("Invalid JSON in instance geometry file: %s", e)
        except Exception as e:
            logger.error("Failed to load instance geometry: %s", e)

    def _save(self) -> None:
        """Save geometry data to file."""
        try:
            self._file_path.parent.mkdir(parents=True, exist_ok=True)

            data = {
                instance_id: {
                    'x': geom.x,
                    'y': geom.y,
                    'width': geom.width,
                    'height': geom.height,
                }
                for instance_id, geom in self._cache.items()
            }

            tmp_path: Optional[Path] = None
            try:
                with tempfile.NamedTemporaryFile(
                    "w",
                    dir=str(self._file_path.parent),
                    delete=False,
                    encoding="utf-8",
                ) as tmp:
                    tmp_path = Path(tmp.name)
                    json.dump(data, tmp, indent=2)
                    tmp.flush()
                    os.fsync(tmp.fileno())

                os.replace(tmp_path, self._file_path)
            finally:
                if tmp_path is not None:
                    try:
                        tmp_path.unlink()
                    except FileNotFoundError:
                        pass

            logger.debug("Saved geometry for %d instances", len(self._cache))
        except Exception as e:
            logger.error("Failed to save instance geometry: %s", e)

    def get(self, instance_id: str) -> Optional[WindowGeometry]:
        """Get geometry for an instance.

        Args:
            instance_id: Instance ID like "DRT:ACM0" or "main_window"

        Returns:
            WindowGeometry if found, None otherwise
        """
        return self._cache.get(instance_id)

    def set(self, instance_id: str, geometry: WindowGeometry) -> None:
        """Set geometry for an instance.

        Args:
            instance_id: Instance ID like "DRT:ACM0" or "main_window"
            geometry: Window geometry to save
        """
        self._cache[instance_id] = geometry
        self._save()
        logger.debug("Stored geometry for %s: %s", instance_id, geometry.to_geometry_string())

    def remove(self, instance_id: str) -> bool:
        """Remove geometry for an instance.

        Args:
            instance_id: Instance ID to remove

        Returns:
            True if removed, False if not found
        """
        if instance_id in self._cache:
            del self._cache[instance_id]
            self._save()
            return True
        return False

    def get_all(self) -> Dict[str, WindowGeometry]:
        """Get all stored geometries."""
        return dict(self._cache)

    def clear(self) -> None:
        """Clear all stored geometries."""
        self._cache.clear()
        self._save()


# Singleton instance
_store: Optional[InstanceGeometryStore] = None


def get_instance_geometry_store() -> InstanceGeometryStore:
    """Get the singleton instance geometry store."""
    global _store
    if _store is None:
        _store = InstanceGeometryStore()
    return _store
