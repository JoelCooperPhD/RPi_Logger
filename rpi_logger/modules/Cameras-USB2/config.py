# Configuration system
# Task: P1.2

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class PreviewSettings:
    resolution: tuple[int, int] = (640, 480)
    fps_cap: int = 15
    pixel_format: str = "MJPG"
    overlay: bool = False


@dataclass
class RecordSettings:
    resolution: tuple[int, int] = (1280, 720)
    fps_cap: int = 30
    pixel_format: str = "MJPG"
    overlay: bool = True
    jpeg_quality: int = 80


@dataclass
class StorageSettings:
    base_path: Path = field(default_factory=Path.cwd)
    per_camera_subdir: bool = False


@dataclass
class GuardSettings:
    disk_free_gb_min: float = 1.0
    check_interval_ms: int = 5000


@dataclass
class TelemetrySettings:
    emit_interval_ms: int = 2000
    include_metrics: bool = True


@dataclass
class CamerasConfig:
    preview: PreviewSettings = field(default_factory=PreviewSettings)
    record: RecordSettings = field(default_factory=RecordSettings)
    storage: StorageSettings = field(default_factory=StorageSettings)
    guard: GuardSettings = field(default_factory=GuardSettings)
    telemetry: TelemetrySettings = field(default_factory=TelemetrySettings)
    log_level: str = "INFO"

    @classmethod
    def from_preferences(cls, prefs: dict, cli_overrides: dict | None = None) -> "CamerasConfig":
        # TODO: Implement full loading - Task P1.2
        config = cls()
        if cli_overrides and "output_dir" in cli_overrides and cli_overrides["output_dir"]:
            config.storage.base_path = Path(cli_overrides["output_dir"])
        return config

    def to_dict(self) -> dict:
        # TODO: Implement - Task P1.2
        return {}
