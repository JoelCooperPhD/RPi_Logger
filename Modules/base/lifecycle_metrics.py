
import logging
import time
from typing import Dict, Optional


class LifecycleTimer:

    def __init__(self, module_name: str):
        self.module_name = module_name
        self.logger = logging.getLogger(f"LifecycleTimer.{module_name}")
        self.phases: Dict[str, float] = {}
        self.start_time = time.perf_counter()
        self.mark_phase("process_start")

    def mark_phase(self, phase_name: str) -> None:
        timestamp = time.perf_counter()
        self.phases[phase_name] = timestamp
        elapsed_ms = (timestamp - self.start_time) * 1000
        self.logger.info("LIFECYCLE [%s] %s at +%.1fms", self.module_name, phase_name, elapsed_ms)

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
                prev_phase = phase_names[i-1]
                duration = (self.phases[phase] - self.phases[prev_phase]) * 1000
                self.logger.info("  %s: +%.1fms (Δ%.1fms)", phase, elapsed, duration)
            else:
                self.logger.info("  %s: +%.1fms", phase, elapsed)

        total_elapsed = self.get_elapsed_ms()
        self.logger.info("-" * 60)
        self.logger.info("  TOTAL: %.1fms", total_elapsed)
        self.logger.info("=" * 60)

    def get_metrics_dict(self) -> Dict[str, float]:
        metrics = {}
        phase_names = list(self.phases.keys())

        for i, phase in enumerate(phase_names):
            elapsed = (self.phases[phase] - self.start_time) * 1000
            metrics[f"{phase}_elapsed_ms"] = round(elapsed, 1)

            if i > 0:
                prev_phase = phase_names[i-1]
                duration = (self.phases[phase] - self.phases[prev_phase]) * 1000
                metrics[f"{prev_phase}_to_{phase}_duration_ms"] = round(duration, 1)

        metrics["total_elapsed_ms"] = round(self.get_elapsed_ms(), 1)

        return metrics
