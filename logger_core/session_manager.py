"""
Session Manager - Handles recording session and trial control.

This module provides centralized management of recording sessions,
including session start/stop and trial recording control.
"""

import asyncio
import logging
from pathlib import Path
from typing import Dict, Optional

from .module_process import ModuleProcess, ModuleState


class SessionManager:
    """
    Manages recording sessions and trials.

    Responsibilities:
    - Control session start/stop across modules
    - Control trial recording across modules
    - Track recording state
    """

    def __init__(self):
        self.logger = logging.getLogger("SessionManager")
        self.recording = False

    async def start_session_all(
        self,
        module_processes: Dict[str, ModuleProcess],
        session_dir: Path
    ) -> Dict[str, bool]:
        """
        Start session on all running modules.

        Args:
            module_processes: Dict of module name -> ModuleProcess
            session_dir: Directory for session data

        Returns:
            Dict mapping module name -> success status
        """
        self.logger.info("Starting session on all modules")

        # Update output directory for all modules
        for module_name, process in module_processes.items():
            process.output_dir = session_dir
            self.logger.info("Updated %s output_dir to: %s", module_name, session_dir)

        results = {}
        tasks = []

        for module_name, process in module_processes.items():
            if process.is_running():
                tasks.append(self._start_session_module(module_name, process))
            else:
                self.logger.warning("Module %s not running, skipping session start", module_name)
                results[module_name] = False

        if tasks:
            task_results = await asyncio.gather(*tasks, return_exceptions=True)
            for module_name, result in zip(module_processes.keys(), task_results):
                if isinstance(result, Exception):
                    self.logger.error("Error starting session for %s: %s", module_name, result)
                    results[module_name] = False
                else:
                    results[module_name] = result

        return results

    async def _start_session_module(self, module_name: str, process: ModuleProcess) -> bool:
        """Start session on a single module."""
        try:
            await process.start_session()
            self.logger.info("Sent start_session to %s", module_name)
            return True
        except Exception as e:
            self.logger.error("Error starting session for %s: %s", module_name, e)
            return False

    async def stop_session_all(
        self,
        module_processes: Dict[str, ModuleProcess]
    ) -> Dict[str, bool]:
        """
        Stop session on all running modules.

        Args:
            module_processes: Dict of module name -> ModuleProcess

        Returns:
            Dict mapping module name -> success status
        """
        self.logger.info("Stopping session on all modules")

        results = {}
        tasks = []

        for module_name, process in module_processes.items():
            if process.is_running():
                tasks.append(self._stop_session_module(module_name, process))
            else:
                self.logger.warning("Module %s not running, skipping session stop", module_name)
                results[module_name] = False

        if tasks:
            task_results = await asyncio.gather(*tasks, return_exceptions=True)
            for module_name, result in zip(module_processes.keys(), task_results):
                if isinstance(result, Exception):
                    self.logger.error("Error stopping session for %s: %s", module_name, result)
                    results[module_name] = False
                else:
                    results[module_name] = result

        return results

    async def _stop_session_module(self, module_name: str, process: ModuleProcess) -> bool:
        """Stop session on a single module."""
        try:
            await process.stop_session()
            self.logger.info("Sent stop_session to %s", module_name)
            return True
        except Exception as e:
            self.logger.error("Error stopping session for %s: %s", module_name, e)
            return False

    async def record_all(
        self,
        module_processes: Dict[str, ModuleProcess],
        session_dir: Path,
        trial_number: Optional[int] = None,
        trial_label: Optional[str] = None
    ) -> Dict[str, bool]:
        """
        Start recording on all running modules.

        Args:
            module_processes: Dict of module name -> ModuleProcess
            session_dir: Directory for session data
            trial_number: Optional trial number
            trial_label: Optional trial label

        Returns:
            Dict mapping module name -> success status
        """
        self.logger.info("Starting recording on all modules (trial %s, label: %s)",
                        trial_number if trial_number else "N/A",
                        trial_label if trial_label else "N/A")

        if self.recording:
            self.logger.warning("Already recording")
            return {}

        # Update output directory for all modules
        for module_name, process in module_processes.items():
            process.output_dir = session_dir

        results = {}
        tasks = []

        for module_name, process in module_processes.items():
            if process.is_running():
                tasks.append(self._record_module(module_name, process, trial_number, trial_label))
            else:
                self.logger.warning("Module %s not running, skipping", module_name)
                results[module_name] = False

        if tasks:
            task_results = await asyncio.gather(*tasks, return_exceptions=True)
            for module_name, result in zip(module_processes.keys(), task_results):
                if isinstance(result, Exception):
                    self.logger.error("Error starting recording for %s: %s", module_name, result)
                    results[module_name] = False
                else:
                    results[module_name] = result

        self.recording = True
        return results

    async def _record_module(
        self,
        module_name: str,
        process: ModuleProcess,
        trial_number: Optional[int] = None,
        trial_label: Optional[str] = None
    ) -> bool:
        """Start recording on a single module."""
        try:
            await process.record(trial_number, trial_label)
            self.logger.info("Sent record to %s (trial %s, label: %s)",
                           module_name,
                           trial_number if trial_number else "N/A",
                           trial_label if trial_label else "N/A")
            return True
        except Exception as e:
            self.logger.error("Error starting recording for %s: %s", module_name, e)
            return False

    async def pause_all(self, module_processes: Dict[str, ModuleProcess]) -> Dict[str, bool]:
        """
        Pause recording on all running modules.

        Args:
            module_processes: Dict of module name -> ModuleProcess

        Returns:
            Dict mapping module name -> success status
        """
        self.logger.info("Pausing recording on all modules")

        if not self.recording:
            self.logger.warning("Not recording")
            return {}

        results = {}
        tasks = []

        for module_name, process in module_processes.items():
            if process.is_running():
                tasks.append(self._pause_module(module_name, process))
            else:
                results[module_name] = False

        if tasks:
            task_results = await asyncio.gather(*tasks, return_exceptions=True)
            for module_name, result in zip(module_processes.keys(), task_results):
                if isinstance(result, Exception):
                    self.logger.error("Error pausing recording for %s: %s", module_name, result)
                    results[module_name] = False
                else:
                    results[module_name] = result

        self.recording = False
        return results

    async def _pause_module(self, module_name: str, process: ModuleProcess) -> bool:
        """Pause recording on a single module."""
        try:
            await process.pause()
            self.logger.info("Sent pause to %s", module_name)
            return True
        except Exception as e:
            self.logger.error("Error pausing recording for %s: %s", module_name, e)
            return False

    async def get_status_all(
        self,
        module_processes: Dict[str, ModuleProcess]
    ) -> Dict[str, ModuleState]:
        """
        Get status from all modules.

        Args:
            module_processes: Dict of module name -> ModuleProcess

        Returns:
            Dict mapping module name -> ModuleState
        """
        results = {}

        for module_name, process in module_processes.items():
            if process.is_running():
                try:
                    await process.get_status()
                    results[module_name] = process.get_state()
                except Exception as e:
                    self.logger.error("Error getting status from %s: %s", module_name, e)
                    results[module_name] = ModuleState.ERROR
            else:
                results[module_name] = process.get_state()

        return results

    def is_any_recording(self, module_processes: Dict[str, ModuleProcess]) -> bool:
        """Check if any module is currently recording."""
        return any(p.is_recording() for p in module_processes.values())
