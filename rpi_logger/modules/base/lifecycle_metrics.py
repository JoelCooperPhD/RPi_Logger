
import time
from typing import Dict, Optional

from rpi_logger.core.logging_utils import get_module_logger


class LifecycleTimer:

    def __init__(self, module_name: str):
        self.module_name = module_name
        self.logger = get_module_logger(f"LifecycleTimer.{module_name}")
        self.phases: Dict[str, float] = {}
        self.start_time = time.perf_counter()
        self.mark_phase("process_start")

    def mark_phase(self, phase_name: str) -> None:
        timestamp = time.perf_counter()
        self.phases[phase_name] = timestamp
        elapsed_ms = (timestamp - self.start_time) * 1000
        self.logger.debug("LIFECYCLE [%s] %s at +%.1fms", self.module_name, phase_name, elapsed_ms)

    def get_duration(self, start_phase: str, end_phase: Optional[str] = None) -> float:
        if start_phase not in self.phases:
            self.logger.warning("Start phase '%s' not found", start_phase)
            return 0.0

        start_time = self.phases[start_phase]

        if end_phase is None:
            end_time = time.perf_counter()
        elif end_phase not in self.phases:
            self.logger.warning("End phase '%s' not found", end_phase)
            return 0.0
        else:
            end_time = self.phases[end_phase]

        return (end_time - start_time) * 1000

    def get_elapsed_ms(self) -> float:
        return (time.perf_counter() - self.start_time) * 1000

    def log_summary(self) -> None:
        self.logger.info("=" * 60)
        self.logger.info("LIFECYCLE SUMMARY: %s", self.module_name)
        self.logger.info("=" * 60)
        phase_names = list(self.phases.keys())
        for i, phase in enumerate(phase_names):
            elapsed = (self.phases[phase] - self.start_time) * 1000
            if i > 0:
                duration = (self.phases[phase] - self.phases[phase_names[i-1]]) * 1000
                self.logger.info("  %s: +%.1fms (Δ%.1fms)", phase, elapsed, duration)
            else:
                self.logger.info("  %s: +%.1fms", phase, elapsed)
        self.logger.info("-" * 60)
        self.logger.info("  TOTAL: %.1fms", self.get_elapsed_ms())
        self.logger.info("=" * 60)

    def get_metrics_dict(self) -> Dict[str, float]:
        metrics = {}
        phase_names = list(self.phases.keys())
        for i, phase in enumerate(phase_names):
            elapsed = (self.phases[phase] - self.start_time) * 1000
            metrics[f"{phase}_elapsed_ms"] = round(elapsed, 1)
            if i > 0:
                duration = (self.phases[phase] - self.phases[phase_names[i-1]]) * 1000
                metrics[f"{phase_names[i-1]}_to_{phase}_duration_ms"] = round(duration, 1)
        metrics["total_elapsed_ms"] = round(self.get_elapsed_ms(), 1)
        return metrics
