"""Allow ``python -m rpi_logger`` to launch the master logger.

When running as a PyInstaller frozen executable, this module also handles
routing to individual module entry points for subprocess spawning.
"""

from __future__ import annotations

import sys
from multiprocessing import freeze_support
from pathlib import Path

def _setup_module_aliases() -> None:
    """Register module aliases for packages that modules expect as top-level imports.

    This is needed because:
    - vmc package is at rpi_logger/modules/vmc but modules import 'from vmc import ...'
    - notes_runtime is at rpi_logger/modules/Notes/notes_runtime but Notes imports 'from notes_runtime import ...'
    """
    # Register vmc package and all its submodules
    try:
        from rpi_logger.modules import vmc
        sys.modules['vmc'] = vmc

        # Register vmc submodules so 'from vmc.constants import ...' works
        from rpi_logger.modules.vmc import constants as vmc_constants
        from rpi_logger.modules.vmc import runtime as vmc_runtime
        from rpi_logger.modules.vmc import runtime_helpers as vmc_runtime_helpers
        from rpi_logger.modules.vmc import controller as vmc_controller
        from rpi_logger.modules.vmc import model as vmc_model
        from rpi_logger.modules.vmc import view as vmc_view
        from rpi_logger.modules.vmc import preferences as vmc_preferences
        from rpi_logger.modules.vmc import supervisor as vmc_supervisor
        from rpi_logger.modules.vmc import migration as vmc_migration

        sys.modules['vmc.constants'] = vmc_constants
        sys.modules['vmc.runtime'] = vmc_runtime
        sys.modules['vmc.runtime_helpers'] = vmc_runtime_helpers
        sys.modules['vmc.controller'] = vmc_controller
        sys.modules['vmc.model'] = vmc_model
        sys.modules['vmc.view'] = vmc_view
        sys.modules['vmc.preferences'] = vmc_preferences
        sys.modules['vmc.supervisor'] = vmc_supervisor
        sys.modules['vmc.migration'] = vmc_migration
    except ImportError as e:
        print(f"Warning: Could not register vmc module aliases: {e}", file=sys.stderr)

    # Register notes_runtime for the Notes module
    try:
        from rpi_logger.modules.Notes import notes_runtime
        sys.modules['notes_runtime'] = notes_runtime
    except ImportError as e:
        print(f"Warning: Could not register notes_runtime alias: {e}", file=sys.stderr)

    # Register drt package and submodules for DRT module
    try:
        from rpi_logger.modules.DRT import drt as drt_pkg
        from rpi_logger.modules.DRT.drt import runtime as drt_runtime
        from rpi_logger.modules.DRT.drt import view as drt_view
        sys.modules['drt'] = drt_pkg
        sys.modules['drt.runtime'] = drt_runtime
        sys.modules['drt.view'] = drt_view
    except ImportError as e:
        print(f"Warning: Could not register drt module aliases: {e}", file=sys.stderr)

    # Register vog package and submodules for VOG module
    try:
        from rpi_logger.modules.VOG import vog as vog_pkg
        from rpi_logger.modules.VOG.vog import runtime as vog_runtime
        from rpi_logger.modules.VOG.vog import view as vog_view
        sys.modules['vog'] = vog_pkg
        sys.modules['vog.runtime'] = vog_runtime
        sys.modules['vog.view'] = vog_view
    except ImportError as e:
        print(f"Warning: Could not register vog module aliases: {e}", file=sys.stderr)

    # Register gps package and submodules for GPS module
    try:
        from rpi_logger.modules.GPS import gps as gps_pkg
        from rpi_logger.modules.GPS.gps import runtime as gps_runtime
        from rpi_logger.modules.GPS import view as gps_view_module
        sys.modules['gps'] = gps_pkg
        sys.modules['gps.runtime'] = gps_runtime
        sys.modules['view'] = gps_view_module  # GPS imports 'view' directly
    except ImportError as e:
        print(f"Warning: Could not register gps module aliases: {e}", file=sys.stderr)


def _run_module_subprocess(module_name: str, args: list[str]) -> None:
    """Run a specific module's main function (for frozen subprocess support).

    This allows the frozen executable to spawn module subprocesses by calling
    itself with --run-module <module_name> <args>.

    For Nuitka compiled binaries, we use direct imports instead of importlib
    because the modules are compiled into the binary and not available as
    separate importable packages.
    """
    import asyncio
    import signal

    module_key = module_name.lower().replace('-', '_')

    # Set up signal handlers for graceful shutdown in subprocesses
    def signal_handler(sig, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    # Set argv for the module
    sys.argv = [f'rpi_logger.modules.{module_name}'] + args

    try:
        # Direct imports for each module - required for Nuitka compiled binaries
        # where importlib.import_module() doesn't work
        if module_key == 'audio':
            from rpi_logger.modules.Audio.main_audio import main
            asyncio.run(main())
        elif module_key == 'cameras':
            from rpi_logger.modules.Cameras.main_cameras import main
            asyncio.run(main())
        elif module_key == 'drt':
            from rpi_logger.modules.DRT.main_drt import main
            asyncio.run(main())
        elif module_key == 'eye_tracker':
            from rpi_logger.modules.EyeTracker.main_eye_tracker import main
            asyncio.run(main())
        elif module_key == 'gps':
            from rpi_logger.modules.GPS.main_gps import main
            asyncio.run(main())
        elif module_key == 'notes':
            from rpi_logger.modules.Notes.main_notes import main
            asyncio.run(main())
        elif module_key == 'vog':
            from rpi_logger.modules.VOG.main_vog import main
            asyncio.run(main())
        elif module_key == 'cameras_csi2':
            from rpi_logger.modules.Cameras_CSI2.main_cameras_csi2 import main
            asyncio.run(main())
        elif module_key == 'stub_codex':
            # Note: This module has a space in the directory name
            # Python doesn't allow spaces in module names, so this needs special handling
            print(f"Module stub_codex cannot be run in frozen mode", file=sys.stderr)
            sys.exit(1)
        else:
            available = ['audio', 'cameras', 'cameras_csi2', 'drt', 'eye_tracker', 'gps', 'notes', 'vog']
            print(f"Unknown module: {module_name}", file=sys.stderr)
            print(f"Available modules: {', '.join(available)}", file=sys.stderr)
            sys.exit(1)

    except Exception as e:
        print(f"Error running module {module_name}: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


def main() -> None:
    # Required for PyInstaller multiprocessing support
    freeze_support()

    # Set up module aliases for all execution paths
    _setup_module_aliases()

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
