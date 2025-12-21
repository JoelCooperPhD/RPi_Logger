"""
Session Manager - Handles recording session and trial control.

This module provides centralized management of recording sessions,
including session start/stop and trial recording control.
"""

import asyncio
from rpi_logger.core.logging_utils import get_module_logger
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
        self.logger = get_module_logger("SessionManager")
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
        task_modules = []

        for module_name, process in module_processes.items():
            if not process.is_running():
                self.logger.warning("Module %s not running, skipping session start", module_name)
                results[module_name] = False
            elif not process.is_initialized():
                self.logger.warning("Module %s not initialized, skipping session start", module_name)
                results[module_name] = False
            else:
                task_modules.append(module_name)
                tasks.append(self._start_session_module(module_name, process))

        if tasks:
            task_results = await asyncio.gather(*tasks, return_exceptions=True)
            for module_name, result in zip(task_modules, task_results):
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
        task_modules = []

        for module_name, process in module_processes.items():
            if not process.is_running():
                self.logger.warning("Module %s not running, skipping session stop", module_name)
                results[module_name] = False
            elif not process.is_initialized():
                self.logger.warning("Module %s not initialized, skipping session stop", module_name)
                results[module_name] = False
            else:
                task_modules.append(module_name)
                tasks.append(self._stop_session_module(module_name, process))

        if tasks:
            task_results = await asyncio.gather(*tasks, return_exceptions=True)
            for module_name, result in zip(task_modules, task_results):
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

        if self.recording or self.is_any_recording(module_processes):
            self.logger.warning("Already recording")
            self.recording = True
            return {}

        # Update output directory for all modules
        for module_name, process in module_processes.items():
            process.output_dir = session_dir

        results = {}
        tasks = []
        task_modules = []

        for module_name, process in module_processes.items():
            if not process.is_running():
                self.logger.warning("Module %s not running, skipping", module_name)
                results[module_name] = False
            elif not process.is_initialized():
                self.logger.warning("Module %s not initialized, skipping recording", module_name)
                results[module_name] = False
            else:
                task_modules.append(module_name)
                tasks.append(self._record_module(module_name, process, trial_number, trial_label))

        if tasks:
            task_results = await asyncio.gather(*tasks, return_exceptions=True)
            for module_name, result in zip(task_modules, task_results):
                if isinstance(result, Exception):
                    self.logger.error("Error starting recording for %s: %s", module_name, result)
                    results[module_name] = False
                else:
                    results[module_name] = result

        self.recording = any(results.values())
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

        if not self.recording and not self.is_any_recording(module_processes):
            self.logger.warning("Not recording")
            return {}

        results = {}
        tasks = []
        task_modules = []

        for module_name, process in module_processes.items():
            if not process.is_running():
                self.logger.warning("Module %s not running, skipping pause", module_name)
                results[module_name] = False
            elif not process.is_initialized():
                self.logger.warning("Module %s not initialized, skipping pause", module_name)
                results[module_name] = False
            else:
                task_modules.append(module_name)
                tasks.append(self._pause_module(module_name, process))

        if tasks:
            task_results = await asyncio.gather(*tasks, return_exceptions=True)
            for module_name, result in zip(task_modules, task_results):
                if isinstance(result, Exception):
                    self.logger.error("Error pausing recording for %s: %s", module_name, result)
                    results[module_name] = False
                else:
                    results[module_name] = result

        if any(results.values()):
            self.recording = False
        else:
            self.recording = self.is_any_recording(module_processes)
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
