"""Unit tests for utils in base module."""

import time
from unittest.mock import patch

import pytest


class TestRollingFPS:
    """Test RollingFPS class."""

    def test_init_default(self):
        from rpi_logger.modules.base.utils import RollingFPS

        fps = RollingFPS()

        assert fps.window_seconds == 5.0
        assert fps.frame_count == 0
        assert fps.get_fps() == 0.0

    def test_init_custom_window(self):
        from rpi_logger.modules.base.utils import RollingFPS

        fps = RollingFPS(window_seconds=10.0)

        assert fps.window_seconds == 10.0

    def test_add_frame_increments_count(self):
        from rpi_logger.modules.base.utils import RollingFPS

        fps = RollingFPS()
        fps.add_frame(timestamp=0.0)
        fps.add_frame(timestamp=0.1)
        fps.add_frame(timestamp=0.2)

        assert fps.frame_count == 3

    def test_get_fps_single_frame(self):
        from rpi_logger.modules.base.utils import RollingFPS

        fps = RollingFPS()
        fps.add_frame(timestamp=0.0)

        assert fps.get_fps() == 0.0

    def test_get_fps_basic(self):
        from rpi_logger.modules.base.utils import RollingFPS

        fps = RollingFPS(window_seconds=5.0)

        # Add 11 frames over 1 second (10 intervals)
        for i in range(11):
            fps.add_frame(timestamp=i * 0.1)

        # 10 intervals in 1 second = 10 FPS
        with patch('time.time', return_value=1.0):
            result = fps.get_fps()

        assert result == pytest.approx(10.0, rel=0.1)

    def test_get_fps_respects_window(self):
        from rpi_logger.modules.base.utils import RollingFPS

        fps = RollingFPS(window_seconds=1.0)

        # Add frames that will be outside window
        fps.add_frame(timestamp=0.0)
        fps.add_frame(timestamp=0.1)

        # Add frames inside window
        fps.add_frame(timestamp=5.0)
        fps.add_frame(timestamp=5.5)
        fps.add_frame(timestamp=6.0)

        with patch('time.time', return_value=6.0):
            result = fps.get_fps()

        # Only frames from 5.0 to 6.0 should count
        assert result == pytest.approx(2.0, rel=0.2)

    def test_reset(self):
        from rpi_logger.modules.base.utils import RollingFPS

        fps = RollingFPS()
        fps.add_frame(timestamp=0.0)
        fps.add_frame(timestamp=0.1)

        assert fps.frame_count == 2

        fps.reset()

        assert fps.frame_count == 0
        assert fps.get_fps() == 0.0

    def test_window_duration_empty(self):
        from rpi_logger.modules.base.utils import RollingFPS

        fps = RollingFPS()

        assert fps.window_duration == 0.0

    def test_window_duration_single_frame(self):
        from rpi_logger.modules.base.utils import RollingFPS

        fps = RollingFPS()
        fps.add_frame(timestamp=0.0)

        assert fps.window_duration == 0.0

    def test_window_duration_multiple_frames(self):
        from rpi_logger.modules.base.utils import RollingFPS

        fps = RollingFPS()
        fps.add_frame(timestamp=0.0)
        fps.add_frame(timestamp=0.5)
        fps.add_frame(timestamp=1.0)

        assert fps.window_duration == pytest.approx(1.0)

    def test_bounded_deque_prevents_memory_exhaustion(self):
        from rpi_logger.modules.base.utils import RollingFPS

        fps = RollingFPS(window_seconds=1.0, max_fps=100.0)

        # Add more frames than the deque can hold
        for i in range(200):
            fps.add_frame(timestamp=i * 0.001)

        # Should be bounded
        assert fps.frame_count <= 100

    def test_add_frame_with_auto_timestamp(self):
        from rpi_logger.modules.base.utils import RollingFPS

        fps = RollingFPS()

        with patch('time.time', return_value=1.0):
            fps.add_frame()

        assert fps.frame_count == 1

    def test_fps_calculation_zero_time_span(self):
        from rpi_logger.modules.base.utils import RollingFPS

        fps = RollingFPS()

        # Add multiple frames at same timestamp
        fps.add_frame(timestamp=1.0)
        fps.add_frame(timestamp=1.0)
        fps.add_frame(timestamp=1.0)

        with patch('time.time', return_value=1.0):
            result = fps.get_fps()

        assert result == 0.0
