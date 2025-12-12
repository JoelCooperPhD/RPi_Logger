"""Allow ``python -m rpi_logger`` to launch the master logger.

When running as a PyInstaller frozen executable, this module also handles
routing to individual module entry points for subprocess spawning.
"""

from __future__ import annotations

import sys
from multiprocessing import freeze_support


def _run_module_subprocess(module_name: str, args: list[str]) -> None:
    """Run a specific module's main function (for frozen subprocess support).

    This allows the frozen executable to spawn module subprocesses by calling
    itself with --run-module <module_name> <args>.
    """
    import asyncio
    from pathlib import Path

    # Map module names to their directory names and main module paths
    module_info = {
        'audio': ('Audio', 'rpi_logger.modules.Audio.main_audio'),
        'cameras': ('Cameras', 'rpi_logger.modules.Cameras.main_cameras'),
        'drt': ('DRT', 'rpi_logger.modules.DRT.main_drt'),
        'eye_tracker': ('EyeTracker', 'rpi_logger.modules.EyeTracker.main_eye_tracker'),
        'gps': ('GPS', 'rpi_logger.modules.GPS.main_gps'),
        'notes': ('Notes', 'rpi_logger.modules.Notes.main_notes'),
        'stub_codex': ('stub (codex)', 'rpi_logger.modules.stub (codex).main_stub_codex'),
    }

    module_key = module_name.lower().replace('-', '_')

    if module_key not in module_info:
        print(f"Unknown module: {module_name}", file=sys.stderr)
        print(f"Available modules: {', '.join(module_info.keys())}", file=sys.stderr)
        sys.exit(1)

    dir_name, module_path = module_info[module_key]

    try:
        # Determine the base path (frozen or normal)
        if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
            base_path = Path(sys._MEIPASS)
        else:
            base_path = Path(__file__).parent.parent

        # Add the module's directory to sys.path so local imports work
        # (modules use "from runtime import ..." style imports)
        module_dir = base_path / 'rpi_logger' / 'modules' / dir_name
        if module_dir.exists() and str(module_dir) not in sys.path:
            sys.path.insert(0, str(module_dir))

        # Also add stub (codex) for vmc imports
        stub_dir = base_path / 'rpi_logger' / 'modules' / 'stub (codex)'
        if stub_dir.exists() and str(stub_dir) not in sys.path:
            sys.path.insert(0, str(stub_dir))

        # Import and run the module's main function
        import importlib
        import signal
        module = importlib.import_module(module_path)

        # Set up signal handlers for graceful shutdown in subprocesses
        def signal_handler(sig, frame):
            raise KeyboardInterrupt

        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)

        if hasattr(module, 'main'):
            # Pass remaining args to the module
            sys.argv = [module_path] + args
            asyncio.run(module.main())
        else:
            print(f"Module {module_path} has no main() function", file=sys.stderr)
            sys.exit(1)

    except Exception as e:
        print(f"Error running module {module_name}: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


def main() -> None:
    # Required for PyInstaller multiprocessing support
    freeze_support()

    # Check if we're being called to run a specific module subprocess
    if len(sys.argv) >= 3 and sys.argv[1] == '--run-module':
        module_name = sys.argv[2]
        module_args = sys.argv[3:]
        _run_module_subprocess(module_name, module_args)
        return

    # Normal execution - run master logger
    from rpi_logger import run
    run(sys.argv[1:])


if __name__ == "__main__":
    main()
