"""Hardware detection tests.

This module tests the hardware availability detection functionality that
identifies which physical hardware modules are available for testing.
"""

from __future__ import annotations

from tests.infrastructure.schemas.hardware_detection import HardwareAvailability


class TestHardwareDetection:
    """Tests for hardware availability detection."""

    def test_hardware_detection_runs(self):
        """Test hardware detection completes without error."""
        hw = HardwareAvailability()
        hw.detect_all()
        # Should have detected Notes (always available)
        assert hw.is_available("Notes")

    def test_availability_matrix_format(self):
        """Test availability matrix produces valid output."""
        hw = HardwareAvailability()
        hw.detect_all()
        matrix = hw.availability_matrix()

        assert "HARDWARE AVAILABILITY MATRIX" in matrix
        assert "TESTABLE MODULES:" in matrix
        assert "UNTESTABLE MODULES:" in matrix

    def test_notes_always_available(self):
        """Test Notes module is always marked as available."""
        hw = HardwareAvailability()
        hw.detect_all()
        avail = hw.get_availability("Notes")
        assert avail.available
        assert "No hardware required" in avail.reason
