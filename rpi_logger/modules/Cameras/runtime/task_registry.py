"""Centralized task lifecycle management for Cameras runtime."""

from __future__ import annotations

import asyncio
import contextlib
from typing import Dict, Optional


class TaskRegistry:
    """
    Unified registry for managing async tasks with proper lifecycle handling.

    Supports both named singleton tasks and keyed task groups (e.g., per-camera tasks).
    Provides consistent cancellation patterns across all task types.
    """

    def __init__(self) -> None:
        self._tasks: Dict[str, asyncio.Task] = {}
        self._groups: Dict[str, Dict[str, asyncio.Task]] = {}

    # ------------------------------------------------------------------ Singleton Tasks

    def register(self, name: str, task: asyncio.Task) -> None:
        """Register a named singleton task, cancelling any existing task with that name."""
        existing = self._tasks.get(name)
        if existing and not existing.done():
            existing.cancel()
        self._tasks[name] = task

    def get(self, name: str) -> Optional[asyncio.Task]:
        """Get a singleton task by name."""
        return self._tasks.get(name)

    async def cancel(self, name: str) -> None:
        """Cancel and await a singleton task."""
        task = self._tasks.pop(name, None)
        if task and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    # ------------------------------------------------------------------ Keyed Task Groups

    def register_keyed(self, group: str, key: str, task: asyncio.Task) -> None:
        """Register a task in a keyed group, cancelling any existing task for that key."""
        if group not in self._groups:
            self._groups[group] = {}

        existing = self._groups[group].get(key)
        if existing and not existing.done():
            existing.cancel()
        self._groups[group][key] = task

    def get_keyed(self, group: str, key: str) -> Optional[asyncio.Task]:
        """Get a task from a keyed group."""
        return self._groups.get(group, {}).get(key)

    async def cancel_keyed(self, group: str, key: str) -> None:
        """Cancel and await a specific task from a keyed group."""
        if group not in self._groups:
            return
        task = self._groups[group].pop(key, None)
        if task and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def cancel_group(self, group: str) -> None:
        """Cancel and await all tasks in a group."""
        if group not in self._groups:
            return
        tasks = list(self._groups[group].items())
        self._groups[group].clear()

        for key, task in tasks:
            if not task.done():
                task.cancel()

        for key, task in tasks:
            if not task.done():
                with contextlib.suppress(asyncio.CancelledError):
                    await task

    # ------------------------------------------------------------------ Bulk Operations

    async def cancel_all(self) -> None:
        """Cancel and await all registered tasks (singleton and grouped)."""
        # Cancel singleton tasks
        singleton_tasks = list(self._tasks.items())
        self._tasks.clear()

        for name, task in singleton_tasks:
            if not task.done():
                task.cancel()

        for name, task in singleton_tasks:
            if not task.done():
                with contextlib.suppress(asyncio.CancelledError):
                    await task

        # Cancel grouped tasks
        all_groups = list(self._groups.keys())
        for group in all_groups:
            await self.cancel_group(group)

    def task_count(self) -> int:
        """Return total number of registered tasks."""
        count = len(self._tasks)
        for group in self._groups.values():
            count += len(group)
        return count

    def group_keys(self, group: str) -> list[str]:
        """Return all keys in a group."""
        return list(self._groups.get(group, {}).keys())


__all__ = ["TaskRegistry"]
