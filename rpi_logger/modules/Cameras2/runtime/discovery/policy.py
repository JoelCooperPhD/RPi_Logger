"""Discovery policy helpers."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional


@dataclass(slots=True)
class DiscoveryPolicy:
    max_failures_before_backoff: int = 3
    backoff_cap_ms: int = 60_000
    capabilities_refresh_interval_ms: int = 10 * 60_000
    prefer_cache_until_reboot: bool = False
    ignore_flapping_threshold_ms: int = 1_000

    def should_probe(self, last_probe_ts_ms: Optional[float], cache_timestamp_ms: Optional[float]) -> bool:
        """Return True if we should probe capabilities now."""

        now_ms = time.time() * 1000
        if last_probe_ts_ms is None:
            return True
        if cache_timestamp_ms and self.prefer_cache_until_reboot:
            return False
        return (now_ms - last_probe_ts_ms) >= self.capabilities_refresh_interval_ms

    def next_probe_delay_ms(self, failure_count: int) -> int:
        """Exponential backoff delay in ms."""

        if failure_count <= 0:
            return 0
        exp = min(failure_count - 1, 5)
        delay = (2**exp) * 1000
        return min(delay, self.backoff_cap_ms)

    def should_disable(self, failure_count: int) -> bool:
        return failure_count >= self.max_failures_before_backoff
