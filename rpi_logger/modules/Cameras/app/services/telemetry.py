"""Telemetry helpers (placeholder)."""

from __future__ import annotations

from typing import Any, Dict


def build_snapshot(metrics: Dict[str, Any]) -> Dict[str, Any]:
    """Return metrics payload for telemetry/logging."""

    return dict(metrics)

