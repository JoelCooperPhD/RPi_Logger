"""Compatibility shim that proxies to the new packaged runtime."""

from __future__ import annotations

from .adapter import AudioRuntime  # noqa: F401

__all__ = ["AudioRuntime"]
