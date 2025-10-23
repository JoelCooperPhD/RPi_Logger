
import os
import re
import sys
from pathlib import Path
from typing import TextIO, Union


class AnsiStripWriter:

    def __init__(self, file_obj: TextIO):
        self.file = file_obj
        self.ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')

    def write(self, data: str) -> int:
        if '\x1B' in data:
            clean_data = self.ansi_escape.sub('', data)
            return self.file.write(clean_data)
        else:
            return self.file.write(data)

    def flush(self) -> None:
        return self.file.flush()

    def fileno(self) -> int:
        return self.file.fileno()


def sanitize_path_component(name: str) -> str:
    name = name.replace('\0', '')

    name = name.replace('/', '_').replace('\\', '_')
    name = name.replace('..', '__')

    name = re.sub(r'[^a-zA-Z0-9_\-.]', '_', name)

    if name.startswith('.'):
        name = '_' + name[1:]

    if not name or name.isspace():
        name = 'default'

    return name


def redirect_stderr_stdout(log_file_path: Path) -> TextIO:
    # We need to duplicate the file descriptor before redirecting
    original_stdout_fd = os.dup(sys.stdout.fileno())
    original_stdout = os.fdopen(original_stdout_fd, 'w', buffering=1)

    # Open log file in append mode (synchronous - required before event loop)
    log_file = open(log_file_path, 'a', buffering=1)

    clean_log = AnsiStripWriter(log_file)

    log_fd = log_file.fileno()

    os.dup2(log_fd, sys.stderr.fileno())
    os.dup2(log_fd, sys.stdout.fileno())

    sys.stderr = clean_log
    sys.stdout = clean_log

    return original_stdout


def sanitize_error_message(
    error: Union[Exception, str],
    max_length: int = 200
) -> str:
    msg = str(error)

    # Remove absolute paths (anything starting with / or drive letter on Windows)
    msg = re.sub(r'/[^\s]*', '[path]', msg)
    msg = re.sub(r'[A-Z]:\\[^\s]*', '[path]', msg)

    msg = re.sub(r'\.\.?/[^\s]*', '[path]', msg)

    if len(msg) > max_length:
        msg = msg[:max_length - 3] + '...'

    return msg
