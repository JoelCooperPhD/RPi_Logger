"""Compatibility shim that proxies to the new packaged runtime."""

from __future__ import annotations

from modules.audio.runtime import AudioRuntime  # noqa: F401

__all__ = ["AudioRuntime"]
