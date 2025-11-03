import asyncio
import contextlib
from pathlib import Path
from typing import Optional, TextIO


class AsyncCSVWriter:
    """Asynchronous CSV writer with internal buffering."""

    def __init__(
        self,
        *,
        header: Optional[str] = None,
        flush_threshold: int = 64,
        queue_size: int = 512,
    ) -> None:
        self._header = header
        self._flush_threshold = max(1, flush_threshold)
        self._queue_size = max(1, queue_size)

        self._queue: Optional[asyncio.Queue[str]] = None
        self._task: Optional[asyncio.Task] = None
        self._file: Optional[TextIO] = None
        self._sentinel: object = object()
        self._path: Optional[Path] = None

    async def start(self, path: Path) -> None:
        """Open the target file and start the background writer."""
        exists = await asyncio.to_thread(path.exists)
        mode = "a" if exists else "w"

        self._path = path
        self._file = await asyncio.to_thread(open, path, mode, encoding="utf-8")
        if not exists and self._header:
            await asyncio.to_thread(self._file.write, self._header + "\n")

        self._queue = asyncio.Queue(maxsize=self._queue_size)
        self._task = asyncio.create_task(self._writer_loop())

    def enqueue(self, line: str) -> None:
        """Queue a CSV line for writing."""
        if self._queue is None:
            raise RuntimeError("CSV writer not started")

        try:
            self._queue.put_nowait(line)
        except asyncio.QueueFull:
            with contextlib.suppress(asyncio.QueueEmpty):
                _ = self._queue.get_nowait()
            self._queue.put_nowait(line)

    async def stop(self) -> None:
        """Flush outstanding data and close the file."""
        if self._queue is None:
            await self._close_file()
            return

        await self._queue.put(self._sentinel)

        if self._task is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        self._task = None
        self._queue = None

        await self._close_file()

    async def cleanup(self) -> None:
        await self.stop()

    async def _writer_loop(self) -> None:
        assert self._queue is not None
        buffer: list[str] = []

        while True:
            line = await self._queue.get()
            if line is self._sentinel:
                break
            buffer.append(line)
            if len(buffer) >= self._flush_threshold:
                await self._flush(buffer)
                buffer.clear()

        if buffer:
            await self._flush(buffer)

    async def _flush(self, lines: list[str]) -> None:
        if not lines or self._file is None:
            return
        await asyncio.to_thread(self._file.writelines, lines)
        await asyncio.to_thread(self._file.flush)

    async def _close_file(self) -> None:
        if self._file is None:
            return
        await asyncio.to_thread(self._file.flush)
        await asyncio.to_thread(self._file.close)
        self._file = None

    @property
    def path(self) -> Optional[Path]:
        return self._path
