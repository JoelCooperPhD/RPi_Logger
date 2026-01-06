"""Unit tests for async_utils in base module."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestSaveFileAsync:
    """Test save_file_async function."""

    @pytest.mark.asyncio
    async def test_save_file_success(self, tmp_path):
        from rpi_logger.modules.base.async_utils import save_file_async

        filepath = tmp_path / "test.txt"
        def write_func(path, content):
            path.write_text(content)

        result = await save_file_async(filepath, write_func, "test content")

        assert result == filepath
        assert filepath.read_text() == "test content"

    @pytest.mark.asyncio
    async def test_save_file_failure(self, tmp_path):
        from rpi_logger.modules.base.async_utils import save_file_async

        filepath = tmp_path / "nonexistent" / "test.txt"
        def write_func(path, content):
            path.write_text(content)

        result = await save_file_async(filepath, write_func, "test content")

        assert result is None


class TestGatherWithLogging:
    """Test gather_with_logging function."""

    @pytest.mark.asyncio
    async def test_gather_empty_tasks(self):
        from rpi_logger.modules.base.async_utils import gather_with_logging

        results = await gather_with_logging([], "test_operation")

        assert results == []

    @pytest.mark.asyncio
    async def test_gather_success(self):
        from rpi_logger.modules.base.async_utils import gather_with_logging

        async def task1():
            return "result1"

        async def task2():
            return "result2"

        tasks = [asyncio.create_task(task1()), asyncio.create_task(task2())]
        results = await gather_with_logging(tasks, "test_operation")

        assert len(results) == 2
        assert "result1" in results
        assert "result2" in results

    @pytest.mark.asyncio
    async def test_gather_with_exception(self):
        from rpi_logger.modules.base.async_utils import gather_with_logging

        async def success_task():
            return "success"

        async def fail_task():
            raise ValueError("test error")

        tasks = [
            asyncio.create_task(success_task()),
            asyncio.create_task(fail_task())
        ]
        results = await gather_with_logging(tasks, "test_operation")

        assert len(results) == 2
        assert "success" in results
        assert any(isinstance(r, ValueError) for r in results)


class TestGatherWithTimeout:
    """Test gather_with_timeout function."""

    @pytest.mark.asyncio
    async def test_gather_within_timeout(self):
        from rpi_logger.modules.base.async_utils import gather_with_timeout

        async def quick_task():
            return "done"

        tasks = [asyncio.create_task(quick_task())]
        results = await gather_with_timeout(tasks, 5.0, "test_operation")

        assert results == ["done"]

    @pytest.mark.asyncio
    async def test_gather_timeout_exceeded(self):
        from rpi_logger.modules.base.async_utils import gather_with_timeout

        async def slow_task():
            await asyncio.sleep(10)
            return "done"

        tasks = [asyncio.create_task(slow_task())]

        with pytest.raises(asyncio.TimeoutError):
            await gather_with_timeout(tasks, 0.1, "test_operation")


class TestRunWithRetries:
    """Test run_with_retries function."""

    @pytest.mark.asyncio
    async def test_success_first_try(self):
        from rpi_logger.modules.base.async_utils import run_with_retries

        call_count = 0

        async def success_func():
            nonlocal call_count
            call_count += 1
            return "success"

        result = await run_with_retries(success_func, max_retries=3)

        assert result == "success"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_success_after_retries(self):
        from rpi_logger.modules.base.async_utils import run_with_retries

        call_count = 0

        async def eventual_success():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("not yet")
            return "success"

        result = await run_with_retries(
            eventual_success,
            max_retries=3,
            delay=0.01,
            operation_name="test"
        )

        assert result == "success"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_all_retries_fail(self):
        from rpi_logger.modules.base.async_utils import run_with_retries

        async def always_fail():
            raise ValueError("always fails")

        with pytest.raises(ValueError, match="always fails"):
            await run_with_retries(
                always_fail,
                max_retries=2,
                delay=0.01,
                operation_name="test"
            )


class TestCancelTaskSafely:
    """Test cancel_task_safely function."""

    @pytest.mark.asyncio
    async def test_cancel_none_task(self):
        from rpi_logger.modules.base.async_utils import cancel_task_safely

        result = await cancel_task_safely(None, "test_task")

        assert result is True

    @pytest.mark.asyncio
    async def test_cancel_done_task(self):
        from rpi_logger.modules.base.async_utils import cancel_task_safely

        async def quick_task():
            return "done"

        task = asyncio.create_task(quick_task())
        await task  # Wait for completion

        result = await cancel_task_safely(task, "test_task")

        assert result is True

    @pytest.mark.asyncio
    async def test_cancel_running_task(self):
        from rpi_logger.modules.base.async_utils import cancel_task_safely

        async def long_task():
            await asyncio.sleep(10)

        task = asyncio.create_task(long_task())
        await asyncio.sleep(0.01)  # Let it start

        result = await cancel_task_safely(task, "test_task", timeout=1.0)

        assert result is True
        assert task.cancelled()

    @pytest.mark.asyncio
    async def test_cancel_timeout(self):
        from rpi_logger.modules.base.async_utils import cancel_task_safely

        async def stubborn_task():
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                await asyncio.sleep(10)  # Ignore cancellation
                raise

        task = asyncio.create_task(stubborn_task())
        await asyncio.sleep(0.01)

        result = await cancel_task_safely(task, "test_task", timeout=0.1)

        assert result is False
        task.cancel()  # Clean up
        try:
            await task
        except asyncio.CancelledError:
            pass
