import pytest
import asyncio
import tempfile
from pathlib import Path
from dataclasses import dataclass
import time

from recording.timing_writer import TimingCSVWriter


@dataclass
class MockFrame:
    """Mock frame for testing timing writer."""
    wall_time: float
    monotonic_time: float  # time.perf_counter() for cross-module sync
    sensor_timestamp_ns: int
    data: bytes = b""
    size: tuple[int, int] = (100, 100)
    color_format: str = "rgb"


class TestTimingWriterPersistence:
    """Tests that would have caught the timing CSV buffering bug.

    Bug: Data was buffered in memory and only written to disk when stop()
    was called. If recording stopped abnormally, data was lost.
    """

    @pytest.mark.asyncio
    async def test_header_written_immediately_on_start(self):
        """Header should be on disk immediately after start(), not buffered."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "timing.csv"
            writer = TimingCSVWriter(path, trial_number=1, device_id="test_cam")

            await writer.start()

            # Check file exists and has content WITHOUT calling stop()
            assert path.exists(), "File should exist after start()"
            content = path.read_text()
            assert len(content) > 0, "Header should be written immediately"
            assert "trial,module,device_id" in content, "Header should be present"

            await writer.stop()

    @pytest.mark.asyncio
    async def test_frame_data_persisted_without_stop(self):
        """Frame data should be on disk after write_frame(), even without stop().

        This is the critical test that would have caught the buffering bug.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "timing.csv"
            writer = TimingCSVWriter(path, trial_number=1, device_id="test_cam")

            await writer.start()

            # Write a frame
            frame = MockFrame(
                wall_time=time.time(),
                monotonic_time=time.perf_counter(),
                sensor_timestamp_ns=12345678
            )
            await writer.write_frame(frame)

            # Check data is on disk WITHOUT calling stop()
            content = path.read_text()
            lines = content.strip().split('\n')

            assert len(lines) >= 2, \
                f"Expected header + data row, got {len(lines)} lines. " \
                "Data may be buffered and not flushed!"

            await writer.stop()

    @pytest.mark.asyncio
    async def test_multiple_frames_persisted_incrementally(self):
        """Each frame should be persisted immediately, not batched."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "timing.csv"
            writer = TimingCSVWriter(path, trial_number=1, device_id="test_cam")

            await writer.start()

            for i in range(5):
                frame = MockFrame(
                    wall_time=time.time(),
                    monotonic_time=time.perf_counter(),
                    sensor_timestamp_ns=i * 1000000
                )
                await writer.write_frame(frame)

                # Check after EACH write
                content = path.read_text()
                lines = content.strip().split('\n')
                expected_lines = 1 + (i + 1)  # header + frames written so far

                assert len(lines) == expected_lines, \
                    f"After frame {i+1}, expected {expected_lines} lines, got {len(lines)}. " \
                    "Writes may be batched instead of immediate!"

            await writer.stop()

    @pytest.mark.asyncio
    async def test_data_survives_crash_simulation(self):
        """Data written before 'crash' (no stop()) should be recoverable."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "timing.csv"
            writer = TimingCSVWriter(path, trial_number=1, device_id="test_cam")

            await writer.start()

            # Write frames
            for i in range(3):
                frame = MockFrame(
                    wall_time=time.time(),
                    monotonic_time=time.perf_counter(),
                    sensor_timestamp_ns=i * 1000000
                )
                await writer.write_frame(frame)

            # Simulate crash: don't call stop(), just abandon the writer
            # In real scenario, process would exit here

            # Verify data is on disk
            content = path.read_text()
            lines = content.strip().split('\n')

            assert len(lines) == 4, \
                f"Expected 4 lines (1 header + 3 frames), got {len(lines)}. " \
                "Data was lost due to buffering!"


class TestTimingWriterContent:
    """Tests for timing CSV content correctness."""

    @pytest.mark.asyncio
    async def test_csv_format_is_valid(self):
        """CSV should be parseable with correct columns."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "timing.csv"
            writer = TimingCSVWriter(path, trial_number=1, device_id="test_cam")

            await writer.start()

            frame = MockFrame(
                wall_time=1234567890.123456,
                monotonic_time=9876.54321,  # seconds, matching perf_counter() format
                sensor_timestamp_ns=111222333
            )
            await writer.write_frame(frame)
            await writer.stop()

            import csv
            with open(path) as f:
                reader = csv.DictReader(f)
                rows = list(reader)

            assert len(rows) == 1
            row = rows[0]
            assert row['trial'] == '1'
            assert row['device_id'] == 'test_cam'
            assert row['sensor_timestamp_ns'] == '111222333'

    @pytest.mark.asyncio
    async def test_frame_index_increments(self):
        """Frame indices should increment correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "timing.csv"
            writer = TimingCSVWriter(path, trial_number=1, device_id="test_cam")

            await writer.start()

            for i in range(3):
                frame = MockFrame(
                    wall_time=time.time(),
                    monotonic_time=time.perf_counter(),
                    sensor_timestamp_ns=i
                )
                await writer.write_frame(frame)

            await writer.stop()

            import csv
            with open(path) as f:
                reader = csv.DictReader(f)
                rows = list(reader)

            indices = [int(row['frame_index']) for row in rows]
            assert indices == [1, 2, 3]


class TestTimingWriterEdgeCases:
    """Edge case tests."""

    @pytest.mark.asyncio
    async def test_write_before_start_is_safe(self):
        """Writing before start() should not crash."""
        writer = TimingCSVWriter(Path("/tmp/fake.csv"), 1, "test")

        frame = MockFrame(
            wall_time=time.time(),
            monotonic_time=time.perf_counter(),
            sensor_timestamp_ns=0
        )

        # Should not raise
        await writer.write_frame(frame)

    @pytest.mark.asyncio
    async def test_stop_without_start_is_safe(self):
        """Stopping without starting should not crash."""
        writer = TimingCSVWriter(Path("/tmp/fake.csv"), 1, "test")
        await writer.stop()  # Should not raise

    @pytest.mark.asyncio
    async def test_double_stop_is_safe(self):
        """Calling stop() twice should not crash."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "timing.csv"
            writer = TimingCSVWriter(path, trial_number=1, device_id="test")

            await writer.start()
            await writer.stop()
            await writer.stop()  # Should not raise
