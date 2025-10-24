
import psutil
from typing import Tuple


class SystemMonitor:

    @staticmethod
    def get_cpu_percent() -> float:
        return psutil.cpu_percent(interval=0.1)

    @staticmethod
    def get_memory_percent() -> float:
        return psutil.virtual_memory().percent

    @staticmethod
    def get_disk_space() -> Tuple[float, float, float]:
        disk = psutil.disk_usage('/')
        total_gb = disk.total / (1024**3)
        used_gb = disk.used / (1024**3)
        free_gb = disk.free / (1024**3)
        return total_gb, used_gb, free_gb

    @staticmethod
    def get_disk_percent() -> float:
        return psutil.disk_usage('/').percent
