
import os
import re
import sys
from datetime import datetime
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


def get_versioned_filename(directory: Path, date: datetime = None) -> str:
    if date is None:
        date = datetime.now()

    date_str = date.strftime("%Y-%m-%d")

    version = 1
    existing_files = []
    if directory.exists():
        existing_files = [f.name for f in directory.glob(f"*_{date_str}.txt")]

    for filename in existing_files:
        match = re.match(r'(\d+)_\d{4}-\d{2}-\d{2}\.txt$', filename)
        if match:
            file_version = int(match.group(1))
            if file_version >= version:
                version = file_version + 1

    return f"{version}_{date_str}.txt"
