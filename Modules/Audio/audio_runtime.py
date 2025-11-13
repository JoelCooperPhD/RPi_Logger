"""Compatibility shim that proxies to the new packaged runtime."""

from __future__ import annotations

from Modules.Audio.runtime import AudioRuntime  # noqa: F401

__all__ = ["AudioRuntime"]
