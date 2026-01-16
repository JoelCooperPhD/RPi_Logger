"""Cleanup utilities for orphaned processes and serial ports.

This module provides functions to detect and clean up module processes
that were orphaned from previous logger sessions (e.g., due to crash
or improper shutdown). It also provides utilities to check if serial
ports are held by other processes.
"""

import os
from typing import List, Optional, Set

import psutil

from rpi_logger.core.logging_utils import get_module_logger

logger = get_module_logger("OrphanCleanup")

# Module entry point markers to identify module processes
MODULE_MARKERS = [
    'main_drt.py',
    'main_vog.py',
    'main_audio.py',
    'main_cameras.py',
    'main_notes.py',
    'main_gps.py',
    'main_stub_codex.py',
    '--run-module',  # For frozen executables
]


def find_orphaned_module_processes() -> List[psutil.Process]:
    """Find module processes from previous sessions that are now orphaned.

    An orphaned process is one whose parent has died (parent is None or pid 1)
    and matches known module entry points.

    Returns:
        List of psutil.Process objects for orphaned module processes
    """
    orphaned = []
    current_pid = os.getpid()
    current_ppid = os.getppid()

    for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'ppid']):
        try:
            # Skip current process and its parent
            if proc.pid in (current_pid, current_ppid):
                continue

            cmdline = proc.info.get('cmdline') or []
            cmdline_str = ' '.join(cmdline)

            # Check if this is a module process
            if not any(marker in cmdline_str for marker in MODULE_MARKERS):
                continue

            # Check if orphaned (parent is dead or init)
            try:
                parent = proc.parent()
                if parent is None or parent.pid == 1:
                    orphaned.append(proc)
                    logger.debug(
                        "Found orphaned process: pid=%d, cmd=%s",
                        proc.pid, cmdline_str[:80]
                    )
            except psutil.NoSuchProcess:
                # Parent doesn't exist - definitely orphaned
                orphaned.append(proc)

        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    return orphaned


def cleanup_orphaned_processes(timeout: float = 5.0) -> int:
    """Kill orphaned module processes from previous sessions.

    This should be called during logger startup to clean up any
    processes that weren't properly terminated.

    Args:
        timeout: Seconds to wait for processes to terminate gracefully
                 before force-killing them

    Returns:
        Number of processes killed
    """
    orphaned = find_orphaned_module_processes()
    if not orphaned:
        return 0

    killed = 0
    logger.info("Found %d orphaned module process(es)", len(orphaned))

    # First, try graceful termination
    for proc in orphaned:
        try:
            cmdline = ' '.join(proc.cmdline()[:3]) if proc.cmdline() else 'unknown'
            logger.warning(
                "Terminating orphaned process: pid=%d cmd=%s",
                proc.pid, cmdline
            )
            proc.terminate()
            killed += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    # Wait for graceful termination
    if orphaned:
        gone, alive = psutil.wait_procs(orphaned, timeout=timeout)

        if gone:
            logger.debug("Gracefully terminated %d process(es)", len(gone))

        # Force kill any survivors
        for proc in alive:
            try:
                logger.warning(
                    "Force killing unresponsive process: pid=%d",
                    proc.pid
                )
                proc.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        # Wait briefly for force-killed processes
        if alive:
            psutil.wait_procs(alive, timeout=1.0)

    return killed


def find_busy_serial_ports(patterns: Optional[List[str]] = None) -> Set[str]:
    """Find serial ports that are held open by processes.

    This can be used to check if a port is in use before trying to
    connect, or to identify which ports are blocked.

    Args:
        patterns: List of path prefixes to match (default: ['/dev/ttyACM', '/dev/ttyUSB'])

    Returns:
        Set of serial port paths that are currently open
    """
    if patterns is None:
        patterns = ['/dev/ttyACM', '/dev/ttyUSB']

    busy_ports: Set[str] = set()

    for proc in psutil.process_iter(['pid', 'name']):
        try:
            for f in proc.open_files():
                for pattern in patterns:
                    if f.path.startswith(pattern):
                        busy_ports.add(f.path)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    return busy_ports


def get_port_holder(port: str) -> Optional[psutil.Process]:
    """Get the process holding a specific serial port.

    Args:
        port: The serial port path (e.g., '/dev/ttyACM0')

    Returns:
        The Process object holding the port, or None if not found
    """
    for proc in psutil.process_iter(['pid', 'name']):
        try:
            for f in proc.open_files():
                if f.path == port:
                    return proc
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    return None
