
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
    is_command_mode: bool = False
) -> Tuple[Path, str]:
    if is_command_mode:
        session_dir = output_dir
        session_name = session_dir.name

    else:
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

        prefix = sanitize_path_component(session_prefix).rstrip("_")
        session_name = f"{prefix}_{timestamp}" if prefix else timestamp
        session_root_dir = output_dir / session_name

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

        session_dir = session_root_dir

    return session_dir, session_name


def setup_session_from_args(
    args,
    default_prefix: str = 'session'
) -> Tuple[Path, str, bool]:
    is_command_mode = detect_command_mode(args)

    session_prefix = getattr(args, 'session_prefix', default_prefix)

    session_dir, session_name = create_session_directory(
        output_dir=args.output_dir,
        session_prefix=session_prefix,
        is_command_mode=is_command_mode
    )

    return session_dir, session_name, is_command_mode
