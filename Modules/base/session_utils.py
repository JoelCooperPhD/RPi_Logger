
import datetime
import logging
import sys
from pathlib import Path
from typing import Optional, Tuple

from .io_utils import sanitize_path_component

logger = logging.getLogger(__name__)


def detect_command_mode(args) -> bool:
    mode = getattr(args, 'mode', None)
    if mode == 'slave':
        return True

    if getattr(args, 'enable_commands', False):
        return True

    if not sys.stdin.isatty():
        return True

    return False


def create_session_directory(
    output_dir: Path,
    session_prefix: str = 'session',
    is_command_mode: bool = False,
    module_name: Optional[str] = None
) -> Tuple[Path, str, Path]:
    if is_command_mode:
        session_dir = output_dir
        session_name = session_dir.name  # Use directory name as session name

        if module_name:
            log_file = session_dir / f"{module_name}.log"
        else:
            log_file = session_dir / "module.log"

    else:
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

        # Sanitize session prefix to prevent path traversal attacks
        prefix = sanitize_path_component(session_prefix).rstrip("_")
        session_name = f"{prefix}_{timestamp}" if prefix else timestamp
        session_root_dir = output_dir / session_name

        # Validate that session_dir is actually within output_dir (prevent path traversal)
        try:
            session_dir_resolved = session_root_dir.resolve()
            output_dir_resolved = output_dir.resolve()
            if not str(session_dir_resolved).startswith(str(output_dir_resolved)):
                logger.error("Security violation: session directory escapes output directory")
                raise ValueError("Invalid session directory path")
        except (OSError, ValueError) as e:
            logger.error("Failed to validate session directory: %s", e)
            raise

        session_root_dir.mkdir(parents=True, exist_ok=True)

        if module_name:
            module_dir_map = {
                'camera': 'Camera',
                'audio': 'Audio',
                'eyetracker': 'EyeTracker'
            }
            module_dir_name = module_dir_map.get(module_name.lower(), module_name.capitalize())
            session_dir = session_root_dir / module_dir_name
            session_dir.mkdir(exist_ok=True)
            log_file = session_dir / f"{module_name}.log"
        else:
            session_dir = session_root_dir
            log_file = session_dir / "session.log"

    return session_dir, session_name, log_file


def setup_session_from_args(
    args,
    module_name: Optional[str] = None,
    default_prefix: str = 'session'
) -> Tuple[Path, str, Path, bool]:
    is_command_mode = detect_command_mode(args)

    session_prefix = getattr(args, 'session_prefix', default_prefix)

    session_dir, session_name, log_file = create_session_directory(
        output_dir=args.output_dir,
        session_prefix=session_prefix,
        is_command_mode=is_command_mode,
        module_name=module_name
    )

    return session_dir, session_name, log_file, is_command_mode
